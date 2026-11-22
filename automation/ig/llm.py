"""Model access for the real-time path (replies, DMs) and drafting.

Two ways this is used, and they are different:

* Interactive/scheduled generation (scripts, carousels, captions) normally runs
  through the skills in `.claude/skills/` inside the agent, where a human sees
  the draft. That path needs no key from this file.
* Replies and DMs cannot wait for a human to open an editor, so they need a
  model call from the server, behind the policy gate in `social.py`.

Defaults to any OpenAI-compatible endpoint, so this works with OpenAI, Azure
OpenAI, OpenRouter, Groq, Together, vLLM or Ollama with only env changes.
Standard library only: `http.client` and `json` are enough for a chat call.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Sequence

from . import config


class LLMError(RuntimeError):
    pass


@dataclass
class Message:
    role: str   # system | user | assistant
    content: str

    def as_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


def available() -> bool:
    return bool(config.env("OPENAI_API_KEY") or config.env("LLM_BASE_URL"))


def complete(messages: Sequence[Message], *, temperature: float = 0.6,
             max_tokens: int = 900, json_mode: bool = False,
             model: str | None = None) -> str:
    """One chat completion. Raises LLMError with something actionable."""
    base = (config.env("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    key = config.env("OPENAI_API_KEY") or config.env("LLM_API_KEY")
    if not key and "localhost" not in base and "127.0.0.1" not in base:
        raise LLMError(
            "No model configured for the real-time path. Set OPENAI_API_KEY (and "
            "optionally LLM_MODEL / LLM_BASE_URL) in automation/.env. Without it the "
            "agent can still draft through the Claude skills, but it cannot answer a "
            "DM in the 24-hour window.")
    model = model or config.env("LLM_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini"

    body: dict[str, Any] = {
        "model": model,
        "messages": [m.as_dict() for m in messages],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions", data=data,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {key}"} if key else {})})

    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode())
            return payload["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            last = LLMError(f"model call failed HTTP {exc.code}: {detail}")
            if exc.code in {429, 500, 502, 503, 504}:
                time.sleep(2 ** attempt * 2)
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = LLMError(f"model call failed: {exc}")
            time.sleep(2 ** attempt * 2)
    raise last or LLMError("model call failed with no detail")


def complete_json(messages: Sequence[Message], *, temperature: float = 0.3,
                  max_tokens: int = 900, model: str | None = None) -> dict:
    """A completion that must be JSON. Retries once with a repair instruction."""
    raw = complete(messages, temperature=temperature, max_tokens=max_tokens,
                   json_mode=True, model=model)
    for candidate in (raw, _extract_json(raw)):
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            continue
    repair = list(messages) + [
        Message("assistant", raw),
        Message("user", "That was not valid JSON. Return only the JSON object, no prose, "
                        "no code fences."),
    ]
    raw2 = complete(repair, temperature=0, max_tokens=max_tokens, json_mode=True, model=model)
    try:
        return json.loads(_extract_json(raw2))
    except ValueError:
        raise LLMError(f"model would not return JSON: {raw2[:300]}") from None


def _extract_json(text: str) -> str:
    """Pull the outermost {...} out of a response that wrapped it in prose."""
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text
