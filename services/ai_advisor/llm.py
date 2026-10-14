"""LLM providers. All return plain text; the advisor parses and validates it.

ollama    - local open-source model, runs fully offline (default, started by docker compose)
anthropic - Claude via the Anthropic API (set ANTHROPIC_API_KEY in .env)
rules     - no LLM; deterministic answer built from the retrieved knowledge base
"""
import requests

from common import config
from common.log import get_logger

log = get_logger("llm")


class LLMUnavailable(RuntimeError):
    pass


def ollama_ready() -> bool:
    try:
        tags = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=3).json()
        names = {m.get("name", "") for m in tags.get("models", [])}
        return any(n == config.OLLAMA_MODEL or n.startswith(config.OLLAMA_MODEL + ":") for n in names)
    except (requests.RequestException, ValueError):
        return False


def complete(system: str, prompt: str, want_json: bool = True, max_tokens: int = 700) -> tuple[str, str]:
    """Returns (text, provider_label). Raises LLMUnavailable to trigger the rules fallback."""
    provider = config.LLM_PROVIDER.lower()
    if provider == "anthropic":
        if not config.ANTHROPIC_API_KEY:
            raise LLMUnavailable("ANTHROPIC_API_KEY not set")
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": config.ANTHROPIC_MODEL, "max_tokens": max_tokens, "system": system,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=60,
            )
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
            return text, f"anthropic:{config.ANTHROPIC_MODEL}"
        except requests.RequestException as exc:
            raise LLMUnavailable(f"Anthropic API error: {exc}") from exc
    if provider == "ollama":
        if not ollama_ready():
            raise LLMUnavailable(f"Ollama model {config.OLLAMA_MODEL} not available (yet)")
        try:
            body = {"model": config.OLLAMA_MODEL, "stream": False, "options": {"temperature": 0.2},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
            if want_json:
                body["format"] = "json"
            r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=body, timeout=180)
            r.raise_for_status()
            return r.json()["message"]["content"], f"ollama:{config.OLLAMA_MODEL}"
        except (requests.RequestException, KeyError, ValueError) as exc:
            raise LLMUnavailable(f"Ollama error: {exc}") from exc
    raise LLMUnavailable("LLM_PROVIDER=rules")
