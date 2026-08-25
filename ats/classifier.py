"""Dispatches one document to the configured LLM provider.

The vendor-specific code lives in `ats.providers`. Everything above this line
(pipeline, decision, routing, reporting) is provider-agnostic.
"""

from __future__ import annotations

from .config import Settings
from .extract import ExtractedDoc
from .providers import (
    ClassificationError,
    DailyQuotaExhausted,
    FatalScreeningError,
    get_provider,
)
from .schema import Verdict


def has_credentials(settings: Settings | None = None) -> bool:
    """True when the configured provider can authenticate."""
    settings = settings or Settings()
    try:
        return get_provider(settings.provider).has_credentials()
    except KeyError:
        return False


def credentials_message(settings: Settings | None = None) -> str:
    """What to tell the user when credentials are missing or the provider is wrong."""
    settings = settings or Settings()
    try:
        return get_provider(settings.provider).missing_credentials_message()
    except KeyError as exc:
        return str(exc).strip("\"'")


def active_model(settings: Settings) -> str:
    """The model actually in use. Failover can move a run onto a different one."""
    try:
        provider = get_provider(settings.provider)
    except KeyError:
        return settings.model
    return getattr(provider, "active_model", None) or settings.model


def classify(doc: ExtractedDoc, settings: Settings) -> Verdict:
    """Screen one extracted document. Raises ClassificationError on failure."""
    try:
        provider = get_provider(settings.provider)
    except KeyError as exc:
        raise FatalScreeningError(str(exc).strip("\"'")) from exc
    return provider.screen(doc, settings)


__all__ = [
    "ClassificationError",
    "DailyQuotaExhausted",
    "active_model",
    "FatalScreeningError",
    "classify",
    "credentials_message",
    "has_credentials",
]
