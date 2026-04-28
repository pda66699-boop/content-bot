from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request


OPENAI_API_URL = "https://api.openai.com/v1/responses"

# --- Model routing constants (read from env, with sensible defaults) ----------
# Writer drafts get a stronger model; everything else uses the cheaper default.
DEFAULT_MODEL = os.getenv("CONTENT_BOT_LLM_MODEL", "gpt-4o-mini")
WRITER_MODEL = os.getenv("CONTENT_BOT_WRITER_MODEL", "gpt-4o")

DEFAULT_REASONING_EFFORT = os.getenv("CONTENT_BOT_LLM_REASONING_EFFORT", "low")
WRITER_REASONING_EFFORT = os.getenv("CONTENT_BOT_WRITER_REASONING_EFFORT", "low")

DEFAULT_MAX_OUTPUT_TOKENS = 4000
WEB_SEARCH_MAX_OUTPUT_TOKENS = 3200
DEFAULT_REQUEST_TIMEOUT_SECONDS = 90
WEB_SEARCH_TIMEOUT_SECONDS = 35
LOGGER = logging.getLogger(__name__)


def llm_mode() -> str:
    return os.environ.get("CONTENT_BOT_LLM_MODE", "off").strip().lower()


def llm_enabled() -> bool:
    return llm_mode() in {"hybrid", "on", "llm"}


def get_model() -> str:
    """Return the default (cheap) model, overridable via env."""
    return os.environ.get("CONTENT_BOT_LLM_MODEL", "").strip() or DEFAULT_MODEL


def get_api_key() -> str | None:
    return os.environ.get("OPENAI_API_KEY", "").strip() or None


def get_reasoning_effort() -> str:
    """Return the default reasoning effort for non-writer calls."""
    return os.environ.get("CONTENT_BOT_LLM_REASONING_EFFORT", DEFAULT_REASONING_EFFORT).strip() or DEFAULT_REASONING_EFFORT


def get_max_output_tokens() -> int:
    raw_value = os.environ.get("CONTENT_BOT_LLM_MAX_OUTPUT_TOKENS", "").strip()
    if not raw_value:
        return DEFAULT_MAX_OUTPUT_TOKENS
    try:
        return max(256, int(raw_value))
    except ValueError:
        return DEFAULT_MAX_OUTPUT_TOKENS


def resolve_max_output_tokens(tools: list[dict] | None = None) -> int:
    if tools and any(tool.get("type") == "web_search" for tool in tools):
        return min(get_max_output_tokens(), WEB_SEARCH_MAX_OUTPUT_TOKENS)
    return get_max_output_tokens()


def resolve_request_timeout_seconds(tools: list[dict] | None = None) -> int:
    if tools and any(tool.get("type") == "web_search" for tool in tools):
        return WEB_SEARCH_TIMEOUT_SECONDS
    return DEFAULT_REQUEST_TIMEOUT_SECONDS


def model_supports_temperature(model: str | None, reasoning_effort: str) -> bool:
    """True when the model accepts a temperature parameter in the Responses API."""
    if not model:
        return False
    normalized = model.strip().lower()
    # o-series / gpt-5* reasoning models only support temperature when effort=="none"
    if normalized.startswith("gpt-5") or normalized.startswith("o1") or normalized.startswith("o3"):
        if normalized.startswith("gpt-5.1") or normalized.startswith("gpt-5.2"):
            return reasoning_effort == "none"
        return False
    # gpt-4o, gpt-4o-mini and all other standard models support temperature freely
    return True


def resolve_reasoning_effort(
    tools: list[dict] | None = None,
    effort_override: str | None = None,
) -> str:
    """Return the reasoning effort to use for a call.

    effort_override — if set, takes precedence over the env default.
    For web_search calls, 'minimal' is bumped to 'low' automatically
    (only when no override is in effect).
    """
    if effort_override:
        return effort_override
    effort = get_reasoning_effort()
    if tools and any(tool.get("type") == "web_search" for tool in tools):
        if effort == "minimal":
            return "low"
    return effort


def llm_available() -> bool:
    return llm_enabled() and bool(get_model()) and bool(get_api_key())


def extract_output_text(response: dict) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content_item in item.get("content") or []:
            if not isinstance(content_item, dict):
                continue
            if content_item.get("type") == "output_text":
                text = content_item.get("text", "")
                if text:
                    parts.append(text)
    return "\n".join(part for part in parts if part)


def extract_json_blob(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def complete_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    model_override: str | None = None,
    reasoning_effort_override: str | None = None,
) -> dict | None:
    return _complete_json_request(
        system_prompt,
        user_prompt,
        temperature=temperature,
        tools=None,
        model_override=model_override,
        reasoning_effort_override=reasoning_effort_override,
    )


def complete_json_with_web_search(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
) -> dict | None:
    return _complete_json_request(
        system_prompt,
        user_prompt,
        temperature=temperature,
        tools=[{"type": "web_search"}],
    )


def _complete_json_request(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    tools: list[dict] | None = None,
    model_override: str | None = None,
    reasoning_effort_override: str | None = None,
) -> dict | None:
    if not llm_available():
        LOGGER.info("LLM fallback: unavailable (mode=%s, model=%s, has_key=%s)", llm_mode(), get_model(), bool(get_api_key()))
        return None

    model = model_override or get_model()
    effort = resolve_reasoning_effort(tools, effort_override=reasoning_effort_override)
    request_kind = "web_search" if tools else "json"
    started_at = time.monotonic()
    LOGGER.debug("LLM request started kind=%s model=%s reasoning=%s", request_kind, model, effort)

    payload = {
        "model": model,
        "instructions": system_prompt,
        "max_output_tokens": resolve_max_output_tokens(tools),
        "store": False,
        "reasoning": {
            "effort": effort,
        },
        "text": {
            "format": {
                "type": "json_schema",
                "name": "content_bot_json_response",
                "description": "JSON response for the content bot pipeline",
                "strict": False,
                "schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
            }
        },
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": user_prompt,
                    }
                ],
            }
        ],
    }
    if model_supports_temperature(model, effort):
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = tools
    print(f"[LLM] model={model}, kind={request_kind}, effort={effort}, prompt_chars={len(system_prompt)}, payload_keys={list(payload.keys())}", flush=True)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        OPENAI_API_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {get_api_key()}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=resolve_request_timeout_seconds(tools)) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            detail = ""
        LOGGER.warning("LLM fallback: HTTPError %s %s — kind=%s model=%s elapsed=%.2fs", exc.code, detail[:1000], request_kind, model, time.monotonic() - started_at)
        return None
    except urllib.error.URLError as exc:
        LOGGER.warning("LLM fallback: URLError %s — kind=%s model=%s elapsed=%.2fs", exc.reason, request_kind, model, time.monotonic() - started_at)
        return None
    except TimeoutError:
        LOGGER.warning("LLM fallback: request timed out — kind=%s model=%s elapsed=%.2fs", request_kind, model, time.monotonic() - started_at)
        return None

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        LOGGER.warning("LLM fallback: invalid JSON body from API")
        return None

    if parsed.get("error"):
        LOGGER.warning("LLM fallback: API returned error payload %s", parsed.get("error"))
        return None

    content = extract_output_text(parsed)
    result = extract_json_blob(content)
    if parsed.get("status") == "incomplete":
        if result is not None:
            LOGGER.warning("LLM response incomplete, but partial JSON was recovered — kind=%s model=%s elapsed=%.2fs", request_kind, model, time.monotonic() - started_at)
            return result
        LOGGER.warning("LLM fallback: response status incomplete")
        return None
    if result is None:
        LOGGER.warning("LLM fallback: could not extract JSON blob — kind=%s model=%s elapsed=%.2fs", request_kind, model, time.monotonic() - started_at)
        return None
    LOGGER.debug("LLM request finished ok — kind=%s model=%s elapsed=%.2fs", request_kind, model, time.monotonic() - started_at)
    return result
