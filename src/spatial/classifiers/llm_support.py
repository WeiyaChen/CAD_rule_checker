# src/spatial/classifiers/llm_support.py
"""与大模型交互的薄封装：发提示词 → 拿原始文本 → 解析 JSON。"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from .prompts import SYSTEM_PROMPT

_FENCE_PATTERN = '`' * 3 + r'(?:json)?\n?(.*?)\n?' + '`' * 3


def parse_json_response(raw_text: str) -> dict[str, Any]:
    """健壮的 JSON 解析器：容忍 ```json 代码围栏，解析失败时返回空字典。"""
    try:
        clean_text = re.sub(_FENCE_PATTERN, r'\1', str(raw_text), flags=re.DOTALL).strip()
        parsed = json.loads(clean_text)
    except (json.JSONDecodeError, TypeError):
        print(f"Failed to parse LLM JSON response! Raw content:\n{raw_text}")
        return {}
    return parsed if isinstance(parsed, dict) else {}


class LLMJsonGateway:
    """统一负责提示词发送、耗时统计与沙箱降级。"""

    def __init__(self, client=None, model: str | None = None,
                 system_prompt: str = SYSTEM_PROMPT, temperature: float = 0.1):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature

    def ask(self, prompt: str, fallback_text: str = "") -> str:
        """向大模型发送提示词；未配置客户端或调用失败时返回 ``fallback_text``。"""
        if self.client:
            try:
                start_time = time.time()
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                )
                elapsed_time = time.time() - start_time
                print(f"  [+] LLM call successful, inference time: {elapsed_time:.2f}s")
                return response.choices[0].message.content
            except Exception as e:
                print(f"  ⚠️ API call failed: {e}, falling back to sandbox data.")
        return fallback_text

    def ask_json(self, prompt: str, fallback_text: str = "") -> dict[str, Any]:
        """发送提示词并直接返回解析后的字典。"""
        return parse_json_response(self.ask(prompt, fallback_text))
