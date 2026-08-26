"""A model running on your own machine, through Ollama. No key, no quota, no limit.

This is the honest answer to "we need to handle thousands of CVs and the free tier
gives us twenty a day". Not training a model from scratch — that is months of work
and millions in hardware to end up worse than something you can download — but
running a pre-trained open model locally.

What it costs instead of money is time. On a CPU an 8B model takes roughly a minute
per CV; a 3B model perhaps fifteen seconds. Nothing leaves the machine, which also
settles the question of sending applicants' personal data to a free tier.

Requires Ollama (ollama.com) and a pulled model:

    ollama pull qwen3:4b
    ATS_PROVIDER=ollama  ATS_MODEL=qwen3:4b
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..extract import ExtractedDoc
from ..prompts import build_system_prompt, build_user_prompt
from ..schema import Verdict
from .base import (
    MAX_TEXT_CHARS,
    ClassificationError,
    FatalScreeningError,
    Provider,
)

DEFAULT_HOST = "http://localhost:11434"
#: A local model is slow, not rate limited. The timeout has to allow for a CPU
#: chewing through a long CV, or every screening looks like a failure.
TIMEOUT_SECONDS = int(os.getenv("ATS_OLLAMA_TIMEOUT", "600"))


class OllamaProvider(Provider):
    name = "Ollama (local)"
    models = (
        "qwen3:4b",          # good quality/speed trade-off on a CPU
        "llama3.2:3b",       # fastest of these
        "qwen3:8b",
        "mistral:7b",
    )
    credential_env = "ATS_OLLAMA_HOST"

    @staticmethod
    def host() -> str:
        return os.getenv("ATS_OLLAMA_HOST", DEFAULT_HOST).rstrip("/")

    def has_credentials(self) -> bool:
        """There is no key. What matters is whether Ollama is actually running."""
        try:
            with urllib.request.urlopen(f"{self.host()}/api/tags", timeout=3):
                return True
        except Exception:
            return False

    def missing_credentials_message(self) -> str:
        return (
            f"Ollama is not responding at {self.host()}. Install it from ollama.com, "
            f"then run `ollama pull qwen3:4b`. Ollama needs no API key and has no "
            f"quota - it runs the model on this machine."
        )

    def list_models(self) -> list[str]:
        """What is actually pulled locally, rather than what we hope is there."""
        try:
            with urllib.request.urlopen(f"{self.host()}/api/tags", timeout=10) as response:
                data = json.loads(response.read())
        except Exception as exc:  # noqa: BLE001
            raise ClassificationError(f"Could not reach Ollama: {exc}") from exc
        return sorted(m.get("name", "") for m in data.get("models", []) if m.get("name"))

    # -- the call ----------------------------------------------------------
    def _chat(self, system: str, user: str, schema, settings):
        payload = {
            "model": settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # Ollama accepts a JSON schema here and constrains generation to it,
            # which is what makes a small local model usable for extraction.
            "format": schema.model_json_schema(),
            "options": {"temperature": 0, "num_ctx": 8192},
        }
        request = urllib.request.Request(
            f"{self.host()}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code == 404:
                raise FatalScreeningError(
                    f"Ollama does not have '{settings.model}'. Pull it first:  "
                    f"ollama pull {settings.model}"
                ) from exc
            raise ClassificationError(f"Ollama error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise FatalScreeningError(
                f"Lost contact with Ollama at {self.host()}: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise ClassificationError(
                f"Ollama did not answer within {TIMEOUT_SECONDS}s. A smaller model "
                f"(llama3.2:3b) or a longer ATS_OLLAMA_TIMEOUT will help."
            ) from exc

        content = (body.get("message") or {}).get("content", "").strip()
        if not content:
            raise ClassificationError("Ollama returned an empty response.")
        try:
            return schema.model_validate_json(content)
        except Exception as exc:  # noqa: BLE001
            raise ClassificationError(
                f"Could not parse the local model's output: {exc}"
            ) from exc

    def structured(self, system: str, user: str, schema, settings):
        return self._chat(system, user, schema, settings)

    def screen(self, doc: ExtractedDoc, settings) -> Verdict:
        return self._chat(
            build_system_prompt(),
            build_user_prompt(
                filename=doc.path.name,
                text=doc.text[:MAX_TEXT_CHARS],
                metadata_flags=doc.metadata_flags,
                page_count=doc.page_count,
            ),
            Verdict,
            settings,
        )
