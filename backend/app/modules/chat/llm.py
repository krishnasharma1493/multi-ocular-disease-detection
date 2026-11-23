"""Language-model providers for the chat. Server-side only: the API key never reaches the browser.

    provider = get_provider()
    reply = provider.generate(system, [{"role": "user", "content": "…"}, {"role": "assistant", "content": "…"}])
    # -> {"in_scope": bool, "answer": str, "sources_used": ["S1", …]}

Any failure (no key, timeout, HTTP error, blocked prompt, empty or invalid reply) raises LLMUnavailable;
an unparseable reply raises its subclass LLMInvalidOutput, which the router retries once.
"""
import json
import logging
from typing import Any, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMUnavailable(RuntimeError):
    """The provider could not produce an answer. The message is for logs, never shown to the patient."""


class LLMInvalidOutput(LLMUnavailable):
    """The provider answered, but not with the JSON object we asked for."""


class LLMProvider(Protocol):
    def generate(self, system: str, turns: list[dict[str, str]]) -> dict[str, Any]: ...


def parse_reply(text: str) -> dict[str, Any]:
    """Validate the model's JSON: {"in_scope": bool, "answer": non-empty str, "sources_used": [str]}."""
    cleaned = text.strip()
    if cleaned.startswith("```"):  # tolerate a fenced block despite responseMimeType
        cleaned = cleaned.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMInvalidOutput(f"reply is not JSON: {exc}") from None
    if not isinstance(data, dict):
        raise LLMInvalidOutput("reply is not a JSON object")
    answer, in_scope, used = data.get("answer"), data.get("in_scope"), data.get("sources_used", [])
    if not isinstance(answer, str) or not answer.strip():
        raise LLMInvalidOutput("reply has no answer")
    if not isinstance(in_scope, bool):
        raise LLMInvalidOutput("reply has no boolean in_scope")
    if not isinstance(used, list) or not all(isinstance(s, str) for s in used):
        raise LLMInvalidOutput("sources_used is not a list of strings")
    return {"in_scope": in_scope, "answer": answer.strip(), "sources_used": used}


class GeminiProvider:
    """Gemini generateContent over REST (v1beta), with JSON output and a low temperature."""

    def __init__(self, api_key: str, model: str, timeout_s: float) -> None:
        self.api_key, self.model, self.timeout_s = api_key, model, timeout_s

    def request_body(self, system: str, turns: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "model" if t["role"] == "assistant" else "user", "parts": [{"text": t["content"]}]}
                         for t in turns],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }

    def generate(self, system: str, turns: list[dict[str, str]]) -> dict[str, Any]:
        if not self.api_key:
            raise LLMUnavailable("GEMINI_API_KEY is not set")
        try:
            resp = httpx.post(GEMINI_URL.format(model=self.model), json=self.request_body(system, turns),
                              headers={"x-goog-api-key": self.api_key}, timeout=self.timeout_s)
        except httpx.TimeoutException:
            raise LLMUnavailable(f"Gemini timed out after {self.timeout_s}s") from None
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Gemini request failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            # The body may echo the request; log only the status and Google's short error status
            try:
                status = resp.json().get("error", {}).get("status", "")
            except ValueError:
                status = ""
            raise LLMUnavailable(f"Gemini HTTP {resp.status_code} {status}".strip())
        return parse_reply(self._text(resp))

    @staticmethod
    def _text(resp: httpx.Response) -> str:
        try:
            data = resp.json()
        except ValueError:
            raise LLMUnavailable("Gemini returned a non-JSON body") from None
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise LLMUnavailable(f"Gemini blocked the prompt: {block}")
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMUnavailable("Gemini returned no candidates")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        # Skip "thought" parts that thinking models may return before the answer
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise LLMUnavailable(f"Gemini returned no text (finishReason {candidates[0].get('finishReason')})")
        return text


def get_provider() -> LLMProvider:
    """The configured provider. Tests monkeypatch this function."""
    if settings.LLM_PROVIDER == "gemini":
        return GeminiProvider(settings.GEMINI_API_KEY, settings.GEMINI_MODEL, settings.LLM_TIMEOUT_S)
    raise LLMUnavailable(f"Unknown LLM_PROVIDER {settings.LLM_PROVIDER!r}")
