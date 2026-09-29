"""OpenAI-package based LLM helpers for Azure/OpenAI-compatible chat completions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

DEFAULT_HTTP_TIMEOUT = 60
DEFAULT_TEMPERATURE = 1.0

Message = Dict[str, Any]


@dataclass
class AzureLLMConfig:
    endpoint: str = ""
    api_key: str = ""
    deployment_id: str = "gpt-5.4-mini"
    api_version: str = ""  # kept for backward compatibility; intentionally unused

    def __post_init__(self) -> None:
        if not self.endpoint:
            raise ValueError("Azure OpenAI endpoint must be provided.")
        if not self.api_key:
            raise ValueError("Azure OpenAI api_key must be provided.")
        self.endpoint = _normalize_openai_endpoint(self.endpoint)


def _normalize_openai_endpoint(endpoint: str) -> str:
    raw = (endpoint or "").strip().rstrip("/")
    if not raw:
        raise ValueError("Azure OpenAI endpoint must be provided.")

    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    if not parsed.netloc:
        raise ValueError(f"Invalid Azure endpoint: {endpoint}")

    scheme = parsed.scheme or "https"
    host = parsed.netloc

    path = (parsed.path or "").rstrip("/")

    for suffix in ("/chat/completions", "/responses"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]

    if "/openai/v1" in path:
        prefix = path.split("/openai/v1", 1)[0]
        normalized_path = f"{prefix}/openai/v1"
    elif "/api/projects/" in path:
        prefix = path.split("/api/projects/", 1)[0]
        normalized_path = f"{prefix}/openai/v1"
    elif path.startswith("/openai/deployments") or path in {"", "/", "/openai"}:
        normalized_path = "/openai/v1"
    else:
        normalized_path = "/openai/v1"

    return f"{scheme}://{host}{normalized_path}".rstrip("/")


def build_user_message(content: str, *, name: Optional[str] = None) -> Message:
    message: Message = {"role": "user", "content": content}
    if name:
        message["name"] = name
    return message


def send_prompt(
    prompt: str,
    config: AzureLLMConfig,
    *,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = 4096,
    stop: Optional[List[str]] = None,
) -> Dict[str, Any]:
    messages = [build_user_message(prompt)]
    return send_messages(
        config,
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stop=stop,
    )


def send_messages(
    config: AzureLLMConfig,
    messages: List[Message],
    *,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = 4096,
    stop: Optional[List[str]] = None,
    timeout: int = DEFAULT_HTTP_TIMEOUT,
) -> Dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai package is required for RAG LLM calls. Install with `pip install openai`.") from exc

    client = OpenAI(api_key=config.api_key, base_url=config.endpoint)

    payload: Dict[str, Any] = {
        "messages": messages,
        "model": config.deployment_id,
        "max_completion_tokens": max_tokens,
        "temperature": temperature,
    }
    if stop:
        payload["stop"] = stop

    response = client.chat.completions.create(**payload, timeout=timeout)

    if hasattr(response, "model_dump"):
        raw: Dict[str, Any] = response.model_dump()
    else:
        raw = dict(response)

    return {"text": _collect_output_text(raw), "raw": raw}


def _append_text_fragments(fragments: List[str], value: Any) -> None:
    if value is None:
        return

    if isinstance(value, str):
        text = value.strip()
        if text:
            fragments.append(text)
        return

    if isinstance(value, list):
        for item in value:
            _append_text_fragments(fragments, item)
        return

    if isinstance(value, dict):
        for key in ("output_text", "text", "content", "value"):
            if key in value:
                _append_text_fragments(fragments, value.get(key))
        return


def _collect_output_text(payload: Dict[str, Any]) -> str:
    fragments: List[str] = []

    _append_text_fragments(fragments, payload.get("output_text"))
    _append_text_fragments(fragments, payload.get("text"))
    for output in payload.get("output", []):
        if isinstance(output, dict):
            _append_text_fragments(fragments, output.get("content"))
            _append_text_fragments(fragments, output.get("text"))
        else:
            _append_text_fragments(fragments, output)

    for choice in payload.get("choices", []):
        if not isinstance(choice, dict):
            _append_text_fragments(fragments, choice)
            continue

        _append_text_fragments(fragments, choice.get("text"))
        _append_text_fragments(fragments, choice.get("message"))
        _append_text_fragments(fragments, choice.get("delta"))

    if isinstance(payload.get("response"), dict):
        response_payload = payload["response"]
        _append_text_fragments(fragments, response_payload.get("output_text"))
        _append_text_fragments(fragments, response_payload.get("output"))

    deduped: List[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        cleaned = fragment.rstrip()
        if cleaned and cleaned not in seen:
            deduped.append(cleaned)
            seen.add(cleaned)

    return "\n".join(deduped).strip()
