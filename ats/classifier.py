"""The Claude call that turns an extracted document into a Verdict."""

from __future__ import annotations

import base64
import os
import threading

import anthropic

from .config import Settings
from .extract import ExtractedDoc
from .prompts import build_system_prompt, build_user_prompt
from .schema import Verdict

MAX_TEXT_CHARS = 60_000      # ~15k tokens; CVs are never close to this
MAX_PDF_BYTES = 30 * 1024 * 1024

_client: anthropic.Anthropic | None = None
_client_lock = threading.Lock()

# Flipped off permanently if the account/endpoint rejects the fallback beta, so we
# do not pay a failed round-trip per CV.
_use_fallbacks = os.getenv("ATS_SERVER_FALLBACKS", "1") not in {"0", "false", "False"}


class ClassificationError(RuntimeError):
    """Raised when Claude could not produce a verdict for a document."""


class FatalScreeningError(ClassificationError):
    """An account-level failure that will hit every CV in the batch identically.

    No credits, a bad key, a model the account cannot use. Retrying the remaining
    files just burns time, so the pipeline stops the whole run on this.
    """


# Substrings that identify an account-level problem inside a 400. The API returns
# these as invalid_request_error, which is otherwise a per-request failure.
_FATAL_400_MARKERS = (
    "credit balance is too low",
    "billing",
    "quota",
)


def _as_screening_error(exc: anthropic.APIStatusError) -> ClassificationError:
    """Turn an API status error into a fatal or per-file error with clear advice."""
    message = str(exc)
    lowered = message.lower()

    if any(marker in lowered for marker in _FATAL_400_MARKERS):
        return FatalScreeningError(
            "Your Anthropic account has no credits, so no CV can be screened. "
            "Add credits at console.anthropic.com -> Plans & Billing, then run again."
        )
    return ClassificationError(f"API error {exc.status_code}: {message}")


def has_credentials() -> bool:
    """True when the SDK will find something to authenticate with."""
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def get_client() -> anthropic.Anthropic:
    """Lazily build a shared client (thread-safe, reused across CVs)."""
    global _client
    with _client_lock:
        if _client is None:
            if not has_credentials():
                raise ClassificationError(
                    "No Anthropic credentials found. Set ANTHROPIC_API_KEY in your "
                    "environment or in a .env file next to this project."
                )
            _client = anthropic.Anthropic(max_retries=3, timeout=180.0)
        return _client


def _content_blocks(doc: ExtractedDoc) -> list[dict]:
    """Build the user content: the PDF itself when there is no text layer."""
    if doc.needs_vision and doc.path.suffix.lower() == ".pdf":
        raw = doc.path.read_bytes()
        if len(raw) > MAX_PDF_BYTES:
            raise ClassificationError("PDF has no text layer and is too large to send")
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


def _request_kwargs(doc: ExtractedDoc, settings: Settings) -> dict:
    return {
        "model": settings.model,
        "max_tokens": settings.max_tokens,
        # The system prompt is identical for every CV, so cache it - after the first
        # call each screening reads it from cache instead of re-billing ~2k tokens.
        "system": [
            {
                "type": "text",
                "text": build_system_prompt(),
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": _content_blocks(doc)}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": settings.effort},
        "output_format": Verdict,
    }


def classify(doc: ExtractedDoc, settings: Settings) -> Verdict:
    """Ask Claude to screen one extracted document. Raises ClassificationError."""
    global _use_fallbacks

    client = get_client()
    kwargs = _request_kwargs(doc, settings)

    try:
        if _use_fallbacks:
            try:
                response = client.beta.messages.parse(
                    **kwargs,
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                )
            except (anthropic.BadRequestError, TypeError) as exc:
                # Only a beta-related 400 means "retry without it". Anything else
                # (no credits, malformed request) must not be masked as one.
                if isinstance(exc, anthropic.BadRequestError) and not any(
                    marker in str(exc).lower() for marker in ("beta", "fallback")
                ):
                    raise
                _use_fallbacks = False
                response = client.messages.parse(**kwargs)
        else:
            response = client.messages.parse(**kwargs)

    except anthropic.AuthenticationError as exc:
        raise FatalScreeningError(
            f"Authentication failed - check ANTHROPIC_API_KEY in your .env: {exc}"
        ) from exc
    except anthropic.PermissionDeniedError as exc:
        raise FatalScreeningError(f"This API key is not permitted to do that: {exc}") from exc
    except anthropic.NotFoundError as exc:
        raise FatalScreeningError(
            f"Model '{settings.model}' is not available to this account: {exc}"
        ) from exc
    except anthropic.RateLimitError as exc:
        raise ClassificationError(f"Rate limited after retries: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise _as_screening_error(exc) from exc
    except anthropic.APIConnectionError as exc:
        raise ClassificationError(f"Could not reach the Anthropic API: {exc}") from exc

    if getattr(response, "stop_reason", None) == "refusal":
        detail = getattr(response, "stop_details", None)
        raise ClassificationError(
            f"Claude declined to screen this document ({getattr(detail, 'category', 'unknown')})."
        )

    verdict = response.parsed_output
    if verdict is None:
        raise ClassificationError("Claude returned no parseable verdict")
    return verdict
