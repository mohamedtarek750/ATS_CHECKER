"""Anthropic Claude backend. Paid, and the strongest at the AI-generation call."""

from __future__ import annotations

import base64
import os
import threading

from ..extract import ExtractedDoc
from ..prompts import build_system_prompt, build_user_prompt
from ..schema import Verdict
from .base import (
    MAX_TEXT_CHARS,
    ClassificationError,
    FatalScreeningError,
    Provider,
)

MAX_PDF_BYTES = 30 * 1024 * 1024

# Substrings that identify an account-level problem inside a 400. The API returns
# these as invalid_request_error, which is otherwise a per-request failure.
_FATAL_400_MARKERS = ("credit balance is too low", "billing", "quota")


class ClaudeProvider(Provider):
    name = "Anthropic Claude"
    models = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5")
    credential_env = "ANTHROPIC_API_KEY"

    def __init__(self) -> None:
        self._client = None
        self._lock = threading.Lock()
        # Flipped off permanently if the account rejects the fallback beta, so we do
        # not pay a failed round-trip per CV.
        self._use_fallbacks = os.getenv("ATS_SERVER_FALLBACKS", "1") not in {
            "0",
            "false",
            "False",
        }

    def has_credentials(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))

    def _get_client(self):
        with self._lock:
            if self._client is None:
                if not self.has_credentials():
                    raise FatalScreeningError(self.missing_credentials_message())
                import anthropic

                self._client = anthropic.Anthropic(max_retries=3, timeout=180.0)
            return self._client

    @staticmethod
    def _as_screening_error(exc) -> ClassificationError:
        message = str(exc)
        if any(marker in message.lower() for marker in _FATAL_400_MARKERS):
            return FatalScreeningError(
                "Your Anthropic account has no credits, so no CV can be screened. "
                "Add credits at console.anthropic.com -> Plans & Billing, then run "
                "again - or switch to the free Gemini provider with ATS_PROVIDER=gemini."
            )
        return ClassificationError(f"API error {exc.status_code}: {message}")

    @staticmethod
    def _content_blocks(doc: ExtractedDoc) -> list[dict]:
        """Build the user content: the PDF itself when there is no text layer."""
        if doc.needs_vision and doc.path.suffix.lower() == ".pdf":
            raw = doc.path.read_bytes()
            if len(raw) > MAX_PDF_BYTES:
                raise ClassificationError(
                    "PDF has no text layer and is too large to send"
                )
            return [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(raw).decode("ascii"),
                    },
                },
                {
                    "type": "text",
                    "text": build_user_prompt(
                        filename=doc.path.name,
                        text="(No text layer in this PDF - read the attached file directly.)",
                        metadata_flags=doc.metadata_flags,
                        page_count=doc.page_count,
                    ),
                },
            ]

        return [
            {
                "type": "text",
                "text": build_user_prompt(
                    filename=doc.path.name,
                    text=doc.text[:MAX_TEXT_CHARS],
                    metadata_flags=doc.metadata_flags,
                    page_count=doc.page_count,
                ),
            }
        ]

    def _request_kwargs(self, doc: ExtractedDoc, settings) -> dict:
        return {
            "model": settings.model,
            "max_tokens": settings.max_tokens,
            # Identical for every CV, so cache it - after the first call each
            # screening reads it from cache instead of re-billing ~2k tokens.
            "system": [
                {
                    "type": "text",
                    "text": build_system_prompt(),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": self._content_blocks(doc)}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": settings.effort},
            "output_format": Verdict,
        }

    def structured(self, system: str, user: str, schema, settings):
        """One structured call with an arbitrary schema."""
        return self._call(
            {
                "model": settings.model,
                "max_tokens": settings.max_tokens,
                "system": [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": user}],
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": settings.effort},
                "output_format": schema,
            },
            settings,
        )

    def screen(self, doc: ExtractedDoc, settings) -> Verdict:
        return self._call(self._request_kwargs(doc, settings), settings)

    def _call(self, kwargs: dict, settings):
        import anthropic

        client = self._get_client()

        try:
            if self._use_fallbacks:
                try:
                    response = client.beta.messages.parse(
                        **kwargs,
                        betas=["server-side-fallback-2026-07-01"],
                        fallbacks="default",
                    )
                except (anthropic.BadRequestError, TypeError) as exc:
                    # Only a beta-related 400 means "retry without it". Anything
                    # else (no credits, malformed request) must not be masked.
                    if isinstance(exc, anthropic.BadRequestError) and not any(
                        marker in str(exc).lower() for marker in ("beta", "fallback")
                    ):
                        raise
                    self._use_fallbacks = False
                    response = client.messages.parse(**kwargs)
            else:
                response = client.messages.parse(**kwargs)

        except anthropic.AuthenticationError as exc:
            raise FatalScreeningError(
                f"Authentication failed - check ANTHROPIC_API_KEY in your .env: {exc}"
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise FatalScreeningError(
                f"This API key is not permitted to do that: {exc}"
            ) from exc
        except anthropic.NotFoundError as exc:
            raise FatalScreeningError(
                f"Model '{settings.model}' is not available to this account: {exc}"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ClassificationError(f"Rate limited after retries: {exc}") from exc
        except anthropic.APIStatusError as exc:
            raise self._as_screening_error(exc) from exc
        except anthropic.APIConnectionError as exc:
            raise ClassificationError(f"Could not reach the Anthropic API: {exc}") from exc

        if getattr(response, "stop_reason", None) == "refusal":
            detail = getattr(response, "stop_details", None)
            raise ClassificationError(
                f"Claude declined to screen this document "
                f"({getattr(detail, 'category', 'unknown')})."
            )

        verdict = response.parsed_output
        if verdict is None:
            raise ClassificationError("Claude returned no parseable verdict")
        return verdict
