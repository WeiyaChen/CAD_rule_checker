# src/spatial/classifiers/prompts.py
"""空间类型识别使用的提示词模板。"""

from __future__ import annotations

import json
import os
from typing import Any, Sequence

#: 标准建筑空间类型字典（与图谱 ``bldg:`` 命名空间一一对应）。
STANDARD_SPACE_TYPES: tuple[str, ...] = (
    "Bedroom",
    "LivingRoom",
    "Kitchen",
    "Bathroom",
    "Balcony",
    "Corridor",
    "Entrance",
    "Garden",
    "DiningRoom",
    "ElevatorShaft",
    "StorageRoom",
    "Stairwell",
    "Cloakroom",
    "StudyRoom",
    "SunRoom",
    "WaterRoom",
    "ElectricalRoom",
    "VentilationRoom",
)

#: 大模型系统提示词。
SYSTEM_PROMPT = (
    "You are a top-tier BIM data compliance review expert. "
    "You must output results in strict JSON format."
)


def dumps_context(context_data: Any) -> str:
    return json.dumps(context_data, ensure_ascii=False, indent=2)


def build_cleaning_prompt(raw_texts: Sequence[str]) -> str:
    """任务 A：把原始 OCR 文本映射为标准建筑空间类型字典。"""
    context_str = dumps_context(list(raw_texts))
    options = ", ".join(STANDARD_SPACE_TYPES)
    return (
        f"请将以下图纸的原始OCR文本映射为标准建筑空间类型字典。\n"
        f"可选项: {options}\n"
        f"先验知识：'更衣'对应的是Cloakroom\n"
        f"如果无法识别，请设为 'Unknown'。仅返回 JSON 格式，键为原文本，值为标准类型。\n"
        f"原始文本: {context_str}"
    )


def build_inference_prompt(context_data: Any, template_path: str | os.PathLike | None = None) -> str:
    """任务 B：根据面积/家具/邻接关系推断未标注房间的功能。"""
    context_str = dumps_context(context_data)
    if template_path and os.path.exists(template_path):
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()
        return template.replace("{context_data}", context_str)
    return f"推断以下房间功能(返回JSON)：\n{context_str}"
