from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OpenAICompatibleProfile:
    profile_name: str
    model: str
    base_url: str
    api_key_env: str = "OPENAI_API_KEY"
    target_api_key_env: str = "OPENAI_API_KEY"
    model_class: str = "litellm"
    custom_llm_provider: str = "openai"
    temperature: float | None = 0.0
    max_tokens: int | None = None
    timeout_seconds: int = 120
    max_retries: int = 2
    require_api_key: bool = True
    cost_tracking: str = "ignore_errors"
    chat_completions_path: str = "/chat/completions"
    model_kwargs: dict[str, Any] = field(default_factory=dict)
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/" + self.chat_completions_path.lstrip("/")

    def redacted_snapshot(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "target_api_key_env": self.target_api_key_env,
            "model_class": self.model_class,
            "custom_llm_provider": self.custom_llm_provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "require_api_key": self.require_api_key,
            "cost_tracking": self.cost_tracking,
            "chat_completions_path": self.chat_completions_path,
            "model_kwargs": _redact_sensitive(self.model_kwargs),
            "extra_headers": sorted(self.extra_headers),
            "extra_body": _redact_sensitive(self.extra_body),
        }

    def stable_hash(self) -> str:
        payload = json.dumps(
            self.redacted_snapshot(),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def env_for_subprocess(self, base_env: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(base_env or os.environ)
        api_key = env.get(self.api_key_env, "")
        if self.require_api_key and not api_key:
            raise EnvironmentError(
                f"Missing API key environment variable: {self.api_key_env}. "
                "Set it in the shell; do not write secrets into model JSON."
            )
        if api_key:
            env[self.target_api_key_env] = api_key
            env.setdefault(self.api_key_env, api_key)
        return env

    def mini_sweagent_config_specs(self) -> list[str]:
        specs = [
            _kv("model.model_name", self.model),
            _kv("model.model_class", self.model_class),
            _kv("model.cost_tracking", self.cost_tracking),
        ]
        model_kwargs = dict(self.model_kwargs)
        if self.base_url:
            model_kwargs.setdefault("api_base", self.base_url)
        if self.custom_llm_provider:
            model_kwargs.setdefault("custom_llm_provider", self.custom_llm_provider)
        if self.temperature is not None:
            model_kwargs.setdefault("temperature", self.temperature)
        if self.max_tokens is not None:
            model_kwargs.setdefault("max_tokens", self.max_tokens)
        if self.timeout_seconds > 0:
            model_kwargs.setdefault("timeout", self.timeout_seconds)
        if self.max_retries >= 0:
            model_kwargs.setdefault("num_retries", self.max_retries)
        if self.extra_headers:
            model_kwargs.setdefault("extra_headers", self.extra_headers)
        if self.extra_body:
            model_kwargs.setdefault("extra_body", self.extra_body)
        for key, value in sorted(model_kwargs.items()):
            specs.append(_kv(f"model.model_kwargs.{key}", value))
        return specs


class OpenAICompatibleClient:
    def __init__(self, profile: OpenAICompatibleProfile):
        self.profile = profile

    def chat_completion(self, messages: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
        api_key = os.getenv(self.profile.api_key_env, "")
        if self.profile.require_api_key and not api_key:
            raise EnvironmentError(f"Missing API key environment variable: {self.profile.api_key_env}")

        payload: dict[str, Any] = {
            "model": overrides.pop("model", self.profile.model),
            "messages": messages,
        }
        if self.profile.temperature is not None:
            payload["temperature"] = self.profile.temperature
        if self.profile.max_tokens is not None:
            payload["max_tokens"] = self.profile.max_tokens
        payload.update(self.profile.extra_body)
        payload.update(overrides)

        headers = {
            "Content-Type": "application/json",
            **self.profile.extra_headers,
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = json.dumps(payload).encode("utf-8")
        attempts = max(1, self.profile.max_retries + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            request = urllib.request.Request(
                self.profile.endpoint,
                data=body,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.profile.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if not _is_retryable_http(exc.code) or attempt == attempts - 1:
                    error_body = exc.read().decode("utf-8", errors="replace")[:1000]
                    raise RuntimeError(
                        f"OpenAI-compatible API returned HTTP {exc.code}: {error_body}"
                    ) from exc
                last_error = exc
            except urllib.error.URLError as exc:
                if attempt == attempts - 1:
                    raise RuntimeError(f"OpenAI-compatible API request failed: {exc.reason}") from exc
                last_error = exc
            time.sleep(min(2**attempt, 8) * 0.25)
        raise RuntimeError(f"OpenAI-compatible API request failed after retries: {last_error}")

    def completion_text(self, messages: list[dict[str, Any]], **overrides: Any) -> str:
        raw = self.chat_completion(messages, **overrides)
        choices = raw.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        return ""


def load_openai_compatible_profile(path: str | Path) -> OpenAICompatibleProfile:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return profile_from_dict(raw)


def profile_from_dict(raw: dict[str, Any]) -> OpenAICompatibleProfile:
    return OpenAICompatibleProfile(
        profile_name=str(raw.get("profile_name", "openai_compatible")),
        model=str(raw["model"]),
        base_url=str(raw.get("base_url", "https://api.openai.com/v1")),
        api_key_env=str(raw.get("api_key_env", "OPENAI_API_KEY")),
        target_api_key_env=str(raw.get("target_api_key_env", raw.get("api_key_env", "OPENAI_API_KEY"))),
        model_class=str(raw.get("model_class", "litellm")),
        custom_llm_provider=str(raw.get("custom_llm_provider", "openai")),
        temperature=_optional_float(raw.get("temperature", 0.0)),
        max_tokens=_optional_int(raw.get("max_tokens")),
        timeout_seconds=int(raw.get("timeout_seconds", 120)),
        max_retries=int(raw.get("max_retries", 2)),
        require_api_key=bool(raw.get("require_api_key", True)),
        cost_tracking=str(raw.get("cost_tracking", "ignore_errors")),
        chat_completions_path=str(raw.get("chat_completions_path", "/chat/completions")),
        model_kwargs=dict(raw.get("model_kwargs", {})),
        extra_headers={str(k): str(v) for k, v in dict(raw.get("extra_headers", {})).items()},
        extra_body=dict(raw.get("extra_body", {})),
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _kv(key: str, value: Any) -> str:
    return f"{key}={json.dumps(value, ensure_ascii=True, sort_keys=True)}"


def _is_retryable_http(status_code: int) -> bool:
    return status_code in {408, 409, 429, 500, 502, 503, 504}


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("key", "token", "secret", "password")):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = _redact_sensitive(item)
        return result
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value
