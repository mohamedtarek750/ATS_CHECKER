"""Shared contract every LLM backend implements.

Only this layer knows which vendor is being called. Extraction, the accept/reject
policy, routing and reporting are all provider-agnostic and never import a vendor
SDK.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

from ..extract import ExtractedDoc
from ..schema import Verdict

MAX_TEXT_CHARS = 60_000     # ~15k tokens; CVs are never close to this
MAX_FILE_BYTES = 18 * 1024 * 1024


class ClassificationError(RuntimeError):
    """Raised when the model could not produce a verdict for one document."""


class FatalScreeningError(ClassificationError):
    """An account-level failure that will hit every CV in the batch identically.

    No credits, a bad key, a model the account cannot use, a daily quota that is
    spent. Retrying the remaining files just burns time, so the pipeline stops the
    whole run on this.
    """


class DailyQuotaExhausted(FatalScreeningError):
    """This model's free daily allowance is spent.

    Fatal for the model, not necessarily for the run: providers whose models carry
    separate quotas can fail over to the next one.
    """


class RateLimiter:
    """Minimum spacing between requests, shared across worker threads.

    Free tiers are measured in requests per minute, not concurrency, so spacing is
    what keeps a run inside the limit no matter how many workers are configured.
    """

    def __init__(self, requests_per_minute: int) -> None:
        self._interval = 60.0 / requests_per_minute if requests_per_minute > 0 else 0.0
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self._interval
        if delay:
            time.sleep(delay)


class Provider(ABC):
    """One LLM backend."""

    name: str = "provider"
    #: Set when failover has moved the run onto a different model.
    active_model: str | None = None

    #: Human-readable models this provider accepts, best first.
    models: tuple[str, ...] = ()
    #: Env var holding the credential, shown in error messages.
    credential_env: str = ""

    @abstractmethod
    def has_credentials(self) -> bool:
        """True when this provider will be able to authenticate."""

    @abstractmethod
    def screen(self, doc: ExtractedDoc, settings) -> Verdict:
        """Return a verdict, or raise ClassificationError / FatalScreeningError."""

    def missing_credentials_message(self) -> str:
        return (
            f"No {self.name} credentials found. Set {self.credential_env} in your "
            f"environment or in a .env file next to this project, then run again."
        )
