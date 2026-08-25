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


def get_client() -> anthropic.Anthropic:
    """Lazily build a shared client (thread-safe, reused across CVs)."""
    global _client
    with _client_lock:
        if _client is None:
            if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
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
            except (anthropic.BadRequestError, TypeError):
                # Beta not available on this account - stop trying for this process.
                _use_fallbacks = False
                response = client.messages.parse(**kwargs)
        else:
            response = client.messages.parse(**kwargs)

    except anthropic.AuthenticationError as exc:
        raise ClassificationError(f"Authentication failed: {exc}") from exc
    except anthropic.NotFoundError as exc:
        raise ClassificationError(
            f"Model '{settings.model}' is not available to this account: {exc}"
        ) from exc
    except anthropic.RateLimitError as exc:
        raise ClassificationError(f"Rate limited after retries: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise ClassificationError(f"API error {exc.status_code}: {exc}") from exc
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
