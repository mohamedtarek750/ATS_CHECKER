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
    FatalScreeningError,
    Provider,
    RateLimiter,
)

# Free-tier requests per minute. Deliberately under the published limit so a run
# does not spend its life in backoff.
DEFAULT_RPM = 10
MAX_ATTEMPTS = 4

# Substrings that mean "this will fail the same way for every remaining CV".
_FATAL_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "permission_denied",
    "billing",
    "is not found for api version",
    "not supported for",
)
# A spent daily allowance is fatal; a per-minute burst is not.
_DAILY_QUOTA_MARKERS = ("perday", "per day", "requests per day", "daily")


class GeminiProvider(Provider):
    name = "Google Gemini"
    models = (
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.0-flash",
        "gemini-2.5-flash-lite",
    )
    credential_env = "GEMINI_API_KEY"

    def __init__(self) -> None:
        self._client = None
        self._lock = threading.Lock()
        self._limiter = RateLimiter(int(os.getenv("ATS_GEMINI_RPM", DEFAULT_RPM)))

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

        if any(marker in text for marker in _FATAL_MARKERS):
            if "api key" in text or "api_key" in text:
                return FatalScreeningError(
                    "Gemini rejected the API key. Check GEMINI_API_KEY in your .env - "
                    "get a fresh one at aistudio.google.com/apikey."
                )
            return FatalScreeningError(f"Gemini refused the request: {exc}")

        if status == 429 or "resource_exhausted" in text or "quota" in text:
            if any(marker in text for marker in _DAILY_QUOTA_MARKERS):
                return FatalScreeningError(
                    "The Gemini free-tier daily quota is used up. It resets at "
                    "midnight Pacific time - re-run the unscreened files then, or "
                    "switch ATS_MODEL to gemini-2.0-flash which has a larger daily "
                    "allowance."
                )
            return ClassificationError(f"Rate limited after {MAX_ATTEMPTS} attempts: {exc}")

        return ClassificationError(f"Gemini error: {exc}")

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
    def screen(self, doc: ExtractedDoc, settings) -> Verdict:
        from google.genai import errors, types

        client = self._get_client()
        config = types.GenerateContentConfig(
            system_instruction=build_system_prompt(),
            response_mime_type="application/json",
            response_schema=Verdict,
            temperature=0.0,        # screening should be reproducible
            max_output_tokens=settings.max_tokens,
        )
        contents = self._contents(doc)

        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            self._limiter.wait()
            try:
                response = client.models.generate_content(
                    model=settings.model, contents=contents, config=config
                )
                break
            except errors.APIError as exc:
                last = exc
                if not self._is_retryable(exc) or attempt == MAX_ATTEMPTS - 1:
                    raise self._classify_error(exc) from exc
                # Exponential backoff with jitter so parallel workers desynchronise.
                time.sleep((2**attempt) + random.uniform(0, 1))
            except Exception as exc:  # noqa: BLE001 - transport/parse failures
                raise ClassificationError(f"Gemini call failed: {exc}") from exc
        else:  # pragma: no cover - loop always breaks or raises
            raise self._classify_error(last or RuntimeError("unknown failure"))

        verdict = getattr(response, "parsed", None)
        if isinstance(verdict, Verdict):
            return verdict

        # Structured output is requested, but a truncated or blocked response can
        # still arrive without one. Say why rather than returning junk.
        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ClassificationError(f"Gemini blocked this document: {feedback.block_reason}")

        raw = (getattr(response, "text", "") or "").strip()
        if not raw:
            raise ClassificationError(
                "Gemini returned an empty response - the CV may have exceeded "
                "max_output_tokens, or the response was filtered."
            )
        try:
            return Verdict.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001
            raise ClassificationError(f"Could not parse Gemini's verdict: {exc}") from exc
