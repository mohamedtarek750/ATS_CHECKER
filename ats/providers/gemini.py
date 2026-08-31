"""Google Gemini backend. Runs on the free tier.

Free-tier caveat worth knowing before you point this at real applicants: Google's
free tier uses submitted content to improve their models. For genuine CVs that is a
data-protection decision, not a technical one - use a paid tier or a local model if
that matters to you.
"""

from __future__ import annotations

import os
import random
import threading
import time

from ..extract import ExtractedDoc
from ..prompts import build_system_prompt, build_user_prompt
from ..schema import Verdict
from .base import (
    MAX_FILE_BYTES,
    MAX_TEXT_CHARS,
    ClassificationError,
    DailyQuotaExhausted,
    FatalScreeningError,
    Provider,
    RateLimiter,
)

# Free-tier requests per minute. Deliberately under the published limit so a run
# does not spend its life in backoff.
DEFAULT_RPM = 10
MAX_ATTEMPTS = 4

# Substrings that mean "this will fail the same way for every remaining CV".
# NOTE: "billing" is deliberately NOT here. Google's ordinary 429 body says
# "please check your plan and billing details", so matching it swallowed every
# rate-limit as a generic account failure.
_FATAL_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "permission_denied",
    "not supported for",
)

# A wrong or retired model name. Google closes older models to new API keys, so a
# model that worked last month can start returning 404 with no other change.
_BAD_MODEL_MARKERS = (
    "is not found for api version",
    "no longer available",
    "not found for api version",
    "is not supported",
)
# A spent daily allowance is fatal; a per-minute burst is not. Google names the
# quota in the error body, e.g. GenerateRequestsPerDayPerProjectPerModel-FreeTier.
_DAILY_QUOTA_MARKERS = ("perday", "per day", "requests per day", "daily")

# Free-tier daily request caps, for the "you have run out" message. These are small
# and Google changes them, so treat as a hint, not a contract.
_KNOWN_DAILY_CAPS = {"gemini-3.6-flash": 20}


class GeminiProvider(Provider):
    name = "Google Gemini"
    # Ordered failover list. Each model carries its OWN free-tier daily quota, so
    # when one is spent the run continues on the next instead of stopping. All four
    # were verified callable on 25 Aug 2026.
    models = (
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
    )
    credential_env = "GEMINI_API_KEY"

    def __init__(self) -> None:
        self._client = None
        self._lock = threading.Lock()
        self._limiter = RateLimiter(int(os.getenv("ATS_GEMINI_RPM", DEFAULT_RPM)))
        # Model failover state, shared by every worker in a run.
        self._model_lock = threading.Lock()
        self._exhausted: set[str] = set()
        self._active_model: str | None = None
        self.switches: list[str] = []

    @property
    def active_model(self) -> str | None:
        """The model actually in use, which failover may have changed mid-run."""
        return self._active_model

    def _resolve_model(self, configured: str) -> str:
        with self._model_lock:
            if self._active_model and self._active_model not in self._exhausted:
                return self._active_model
            if configured not in self._exhausted:
                self._active_model = configured
                return configured
            for candidate in self.models:
                if candidate not in self._exhausted:
                    self._active_model = candidate
                    return candidate
            return configured

    def _retire(self, model: str) -> str | None:
        """Mark a model's daily quota spent and return the next one to try."""
        with self._model_lock:
            self._exhausted.add(model)
            for candidate in (self._active_model or "", *self.models):
                if candidate and candidate not in self._exhausted:
                    self._active_model = candidate
                    self.switches.append(f"{model} -> {candidate}")
                    return candidate
            return None

    # -- credentials -------------------------------------------------------
    @staticmethod
    def _api_key() -> str:
        return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

    def has_credentials(self) -> bool:
        return bool(self._api_key())

    def missing_credentials_message(self) -> str:
        return (
            "No Gemini API key found. Get a free one at aistudio.google.com/apikey, "
            "then put GEMINI_API_KEY=... in the .env file next to this project."
        )

    def _get_client(self):
        with self._lock:
            if self._client is None:
                if not self.has_credentials():
                    raise FatalScreeningError(self.missing_credentials_message())
                from google import genai

                self._client = genai.Client(api_key=self._api_key())
            return self._client

    def list_models(self) -> list[str]:
        """Model ids this key can actually call. Keeps a stale list from biting."""
        client = self._get_client()
        names = []
        for model in client.models.list():
            actions = getattr(model, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                names.append(model.name.replace("models/", ""))
        return sorted(names)

    # -- request building --------------------------------------------------
    @staticmethod
    def _contents(doc: ExtractedDoc):
        from google.genai import types

        # A PDF with no text layer: hand Gemini the file and let it read the pages.
        if doc.needs_vision and doc.path.suffix.lower() == ".pdf":
            raw = doc.path.read_bytes()
            if len(raw) > MAX_FILE_BYTES:
                raise ClassificationError(
                    "PDF has no text layer and is too large to send"
                )
            prompt = build_user_prompt(
                filename=doc.path.name,
                text="(No text layer in this PDF - read the attached file directly.)",
                metadata_flags=doc.metadata_flags,
                page_count=doc.page_count,
            )
            return [
                types.Part.from_bytes(data=raw, mime_type="application/pdf"),
                types.Part.from_text(text=prompt),
            ]

        return build_user_prompt(
            filename=doc.path.name,
            text=doc.text[:MAX_TEXT_CHARS],
            metadata_flags=doc.metadata_flags,
            page_count=doc.page_count,
        )

    # -- error mapping -----------------------------------------------------
    @staticmethod
    def _classify_error(exc: Exception) -> ClassificationError:
        text = str(exc).lower()
        status = getattr(exc, "code", None) or getattr(exc, "status_code", None)

        if status == 404 or any(marker in text for marker in _BAD_MODEL_MARKERS):
            suggested = ", ".join(GeminiProvider.models[:3])
            return FatalScreeningError(
                f"Gemini rejected the model name. Set ATS_MODEL to one of "
                f"{suggested}, or run `python ats_cli.py --list-models` to see what "
                f"this key can actually use. Original error: {exc}"
            )

        if "api key" in text or "api_key" in text:
            return FatalScreeningError(
                "Gemini rejected the API key. Check GEMINI_API_KEY in your .env - "
                "get a fresh one at aistudio.google.com/apikey."
            )

        # Rate limits are checked BEFORE the generic account markers, because the
        # 429 body mentions billing and would otherwise be misread as one.
        if status == 429 or "resource_exhausted" in text or "quota" in text:
            if any(marker in text for marker in _DAILY_QUOTA_MARKERS):
                return DailyQuotaExhausted(GeminiProvider._daily_quota_message(text))
            return ClassificationError(
                f"Rate limited, still throttled after {MAX_ATTEMPTS} attempts. "
                f"Lower ATS_GEMINI_RPM or re-run this file later. {exc}"
            )

        if any(marker in text for marker in _FATAL_MARKERS):
            return FatalScreeningError(f"Gemini refused the request: {exc}")

        return ClassificationError(f"Gemini error: {exc}")

    @staticmethod
    def _daily_quota_message(text: str) -> str:
        """Name the model and its cap - "quota exceeded" alone tells you nothing."""
        model = ""
        for known in _KNOWN_DAILY_CAPS:
            if known in text:
                model = known
                break
        cap = f" (only {_KNOWN_DAILY_CAPS[model]} requests/day)" if model else ""
        named = f" for {model}{cap}" if model else ""
        return (
            f"The Gemini free-tier DAILY quota{named} is used up, so no more CVs can "
            f"be screened today. It resets at midnight Pacific time. Each model has "
            f"its own separate daily allowance, so switching ATS_MODEL to another "
            f"one (see `python ats_cli.py --list-models`) gives you a fresh budget "
            f"right now. Files held in _unscreened/ can be re-run either way."
        )

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        text = str(exc).lower()
        status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        if any(marker in text for marker in _DAILY_QUOTA_MARKERS):
            return False        # a spent day will not recover in 8 seconds
        if status == 429 or "resource_exhausted" in text:
            return True
        return isinstance(status, int) and status >= 500

    # -- the call ----------------------------------------------------------
    def _generate(self, client, model: str, contents, config, schema=Verdict):
        """One model, with retries for throttling and transient server errors."""
        from google.genai import errors

        for attempt in range(MAX_ATTEMPTS):
            self._limiter.wait()
            try:
                response = client.models.generate_content(
                    model=model, contents=contents, config=config
                )
                return self._parse(response, schema)
            except errors.APIError as exc:
                if not self._is_retryable(exc) or attempt == MAX_ATTEMPTS - 1:
                    raise self._classify_error(exc) from exc
                # Exponential backoff with jitter so parallel workers desynchronise.
                time.sleep((2**attempt) + random.uniform(0, 1))
            except ClassificationError:
                raise
            except Exception as exc:  # noqa: BLE001 - transport/parse failures
                raise ClassificationError(f"Gemini call failed: {exc}") from exc

        raise ClassificationError("Gemini did not respond")  # pragma: no cover

    def structured(self, system: str, user: str, schema, settings):
        """One structured call with an arbitrary schema, same failover and pacing.

        Reading an advert into a checklist is close to transcription: the words
        are on the page, and the judgement needed is which ones are requirements.
        Left at its default the reasoning model spends ~2,000 thinking tokens and
        half a minute on that, which the recruiter experiences as the page having
        hung. Capping the deliberation cuts it to under ten seconds and, measured
        on a real advert, extracted MORE requirements rather than fewer.
        """
        from google.genai import types

        client = self._get_client()

        def build(brief: bool):
            extra = (
                {"thinking_config": types.ThinkingConfig(thinking_level="low")}
                if brief
                else {}
            )
            return types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.0,
                max_output_tokens=settings.max_tokens,
                **extra,
            )

        # Not every model accepts a thinking level. Rather than maintain a list of
        # which ones do, ask for it and drop it if the API says no.
        brief = True
        while True:
            model = self._resolve_model(settings.model)
            try:
                return self._generate(client, model, user, build(brief), schema)
            except DailyQuotaExhausted:
                if self._retire(model) is None:
                    raise
            except ClassificationError:
                if not brief:
                    raise
                brief = False

    def screen(self, doc: ExtractedDoc, settings) -> Verdict:
        from google.genai import types

        client = self._get_client()
        config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(),
            response_mime_type="application/json",
            response_schema=Verdict,
            temperature=0.0,        # screening should be reproducible
            max_output_tokens=settings.max_tokens,
        )
        contents = self._contents(doc)

        # Free-tier daily quotas are per model, so a spent one does not end the run:
        # move to the next model and keep going. Only when every model is spent is
        # the failure genuinely fatal.
        while True:
            model = self._resolve_model(settings.model)
            try:
                return self._generate(client, model, contents, config)
            except DailyQuotaExhausted:
                if self._retire(model) is None:
                    raise DailyQuotaExhausted(
                        "Every Gemini model's free daily quota is spent "
                        f"({', '.join(sorted(self._exhausted))}). They reset at "
                        "midnight Pacific time - re-run the files held in "
                        "_unscreened/ then."
                    ) from None

    @staticmethod
    def _parse(response, schema=Verdict):
        verdict = getattr(response, "parsed", None)
        if isinstance(verdict, schema):
            return verdict

        # Structured output is requested, but a truncated or blocked response can
        # still arrive without one. Say why rather than returning junk.
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ClassificationError(
                f"Gemini blocked this document: {feedback.block_reason}"
            )

        raw = (getattr(response, "text", "") or "").strip()
        if not raw:
            raise ClassificationError(
                "Gemini returned an empty response - the CV may have exceeded "
                "max_output_tokens, or the response was filtered."
            )
        try:
            return schema.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            raise ClassificationError(f"Could not parse Gemini's verdict: {exc}") from exc
