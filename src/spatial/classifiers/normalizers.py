# src/spatial/classifiers/normalizers.py
"""原始图纸文本 → 标准建筑空间类型 的归一化实现。"""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from ..contracts import ITextLabelNormalizer
from ..registry import TEXT_LABEL_NORMALIZERS
from .llm_support import LLMJsonGateway, parse_json_response
from .prompts import STANDARD_SPACE_TYPES, build_cleaning_prompt

#: 无大模型可用时的兜底清洗字典（与重构前 ``_stage1_clean_texts`` 内的沙箱数据一致）。
DEFAULT_FALLBACK_MAPPING: dict[str, str] = {
    "次卧": "Bedroom",
    "主卫": "Bathroom",
    "餐客厅": "LivingRoom",
}

#: 纯字典归一化使用的常见中英文标注对照表。
DEFAULT_TEXT_DICTIONARY: dict[str, str] = {
    # 中文常见标注
    "主卧": "Bedroom",
    "卧室": "Bedroom",
    "次卧": "Bedroom",
    "客卧": "Bedroom",
    "儿童房": "Bedroom",
    "书房": "StudyRoom",
    "客厅": "LivingRoom",
    "起居室": "LivingRoom",
    "餐客厅": "LivingRoom",
    "餐厅": "DiningRoom",
    "厨房": "Kitchen",
    "卫生间": "Bathroom",
    "主卫": "Bathroom",
    "客卫": "Bathroom",
    "浴室": "Bathroom",
    "阳台": "Balcony",
    "生活阳台": "Balcony",
    "阳光房": "SunRoom",
    "走廊": "Corridor",
    "过道": "Corridor",
    "玄关": "Entrance",
    "入户": "Entrance",
    "门厅": "Entrance",
    "花园": "Garden",
    "庭院": "Garden",
    "电梯": "ElevatorShaft",
    "电梯井": "ElevatorShaft",
    "储藏间": "StorageRoom",
    "储藏室": "StorageRoom",
    "储物间": "StorageRoom",
    "楼梯间": "Stairwell",
    "楼梯": "Stairwell",
    "衣帽间": "Cloakroom",
    "更衣室": "Cloakroom",
    "更衣": "Cloakroom",
    "水暖井": "WaterRoom",
    "水井": "WaterRoom",
    "配电间": "ElectricalRoom",
    "电气间": "ElectricalRoom",
    "通风井": "VentilationRoom",
    "新风井": "VentilationRoom",
}


@TEXT_LABEL_NORMALIZERS.register("LLM", aliases=("LLM_CLEANING",))
class LLMTextLabelNormalizer(ITextLabelNormalizer):
    """调用大模型把零散的中英文标注清洗为标准类型。"""

    name = "LLM"

    def __init__(
        self,
        *,
        llm_client=None,
        llm_model: str | None = None,
        gateway: LLMJsonGateway | None = None,
        fallback_mapping: Mapping[str, str] | None = None,
    ):
        self.gateway = gateway or LLMJsonGateway(client=llm_client, model=llm_model)
        self.fallback_mapping = dict(
            DEFAULT_FALLBACK_MAPPING if fallback_mapping is None else fallback_mapping
        )

    def normalize(self, raw_texts: Sequence[str]) -> dict[str, str]:
        candidate_texts = [str(t) for t in raw_texts if t and str(t).strip()]
        if not candidate_texts:
            return {}

        print("[Stage 1] Requesting LLM to clean raw text labels...")
        prompt = build_cleaning_prompt(candidate_texts)
        fallback_json = json.dumps(self.fallback_mapping, ensure_ascii=False)

        raw_result = self.gateway.ask(prompt, fallback_json)
        print(f"  [Debug] Raw LLM response: {raw_result}")
        parsed = parse_json_response(raw_result)

        return {
            key: value
            for key, value in parsed.items()
            if isinstance(value, str) and value and value != "Unknown"
        }


@TEXT_LABEL_NORMALIZERS.register("Dictionary", aliases=("DICT", "RULES"))
class DictionaryTextLabelNormalizer(ITextLabelNormalizer):
    """不依赖大模型的查表归一化，适合离线/确定性场景。"""

    name = "Dictionary"

    def __init__(
        self,
        *,
        mapping: Mapping[str, str] | None = None,
        case_insensitive: bool = True,
        trim: bool = True,
    ):
        self.mapping = dict(DEFAULT_TEXT_DICTIONARY if mapping is None else mapping)
        for space_type in STANDARD_SPACE_TYPES:
            self.mapping.setdefault(space_type, space_type)
        self.case_insensitive = case_insensitive
        self.trim = trim
        self._lookup = {self._key(k): v for k, v in self.mapping.items()}

    def _key(self, text: str) -> str:
        key = str(text)
        if self.trim:
            key = key.strip()
        return key.upper() if self.case_insensitive else key

    def normalize(self, raw_texts: Sequence[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for text in raw_texts:
            label = self._lookup.get(self._key(text))
            if isinstance(label, str) and label and label != "Unknown":
                result[text] = label
        return result
