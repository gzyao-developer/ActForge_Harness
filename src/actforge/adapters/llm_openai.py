from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from actforge.worldview.models import ActionIntent
from actforge.worldview.snapshot import Snapshot


class LLMPolicyError(RuntimeError):
    """Raised when LLM cannot produce a valid ActionIntent."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def _strip_fences(text: str) -> str:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        return m.group(1).strip()
    return text


class LLMPolicy:
    def __init__(
        self,
        system_prompt_path: str | Path = "prompts/pick_can_system.md",
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_retries: int = 2,
        verbose: bool = False,
    ):
        self.system_prompt = Path(system_prompt_path).read_text(encoding="utf-8")
        self.api_key = api_key or os.getenv("EMBODY_LLM_API_KEY", "")
        self.base_url = (
            base_url or os.getenv("EMBODY_LLM_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self.model = model or os.getenv("EMBODY_LLM_MODEL", "gpt-4o-mini")
        env_temp = os.getenv("EMBODY_LLM_TEMPERATURE")
        if env_temp is not None and env_temp != "":
            self.temperature = float(env_temp)
        else:
            self.temperature = temperature
        self.max_retries = max_retries
        self.verbose = verbose
        self.last_raw: str = ""

    def decide(self, snap: Snapshot) -> ActionIntent:
        if not self.api_key or self.api_key.startswith("sk-xxx"):
            raise LLMPolicyError(
                "llm_not_configured",
                "EMBODY_LLM_API_KEY not configured; use --policy script or set .env",
            )

        user_content = snap.model_dump_json()
        if self.verbose:
            print("--- verbose system prompt (head) ---")
            print(self.system_prompt[:800])
            print("--- verbose snapshot ---")
            print(user_content[:2000])

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        last_err = ""
        http_retries = max(self.max_retries, 3)
        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Previous output failed to parse: {last_err}. "
                            "Reply with ONLY one valid JSON object for ActionIntent."
                        ),
                    }
                )
            try:
                raw = self._chat(messages, http_retries=http_retries)
            except httpx.HTTPError as e:
                raise LLMPolicyError("llm_http_error", str(e)) from e
            self.last_raw = raw
            messages.append({"role": "assistant", "content": raw})
            if self.verbose:
                print(f"--- verbose llm raw (attempt {attempt}) ---")
                print(raw[:1500])
            try:
                data = json.loads(_strip_fences(raw))
                return ActionIntent.model_validate(data)
            except Exception as e:  # noqa: BLE001
                last_err = str(e)

        raise LLMPolicyError("llm_parse_exhausted", last_err)

    def _chat(self, messages: list[dict[str, Any]], http_retries: int = 3) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": messages,
        }
        last_exc: Exception | None = None
        for i in range(http_retries + 1):
            try:
                with httpx.Client(timeout=90.0) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    # Retry transient upstream errors
                    if resp.status_code in (408, 429, 500, 502, 503, 504):
                        raise httpx.HTTPStatusError(
                            f"transient {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )
                    resp.raise_for_status()
                    data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (httpx.HTTPError, KeyError, IndexError, TypeError) as e:
                last_exc = e
                if i >= http_retries:
                    break
                time.sleep(1.5 * (i + 1))
                if self.verbose:
                    print(f"--- llm http retry {i + 1}/{http_retries}: {e} ---")
        assert last_exc is not None
        raise last_exc
