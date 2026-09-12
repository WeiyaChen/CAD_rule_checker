# src/spatial/classifiers/llm_multistage.py
"""三阶段空间类型识别：文本归一化 → 几何落位 → 上下文推理。"""

from __future__ import annotations

import json
import os
from typing import Mapping, Sequence

from ..contracts import ISpaceTypeClassifier, ITextLabelNormalizer
from ..domain import (
    SOURCE_LLM_INFERENCE,
    UNKNOWN_LABEL,
    SpatialComponent,
    SpatialContour,
    SpaceTypePrediction,
    TextAnnotation,
    resolve_neighbors,
)
from ..registry import SPACE_TYPE_CLASSIFIERS, TEXT_LABEL_NORMALIZERS
from .llm_support import LLMJsonGateway
from .matching import match_annotations_to_contours
from .prompts import build_inference_prompt

#: 无大模型可用时的兜底推理结果（与重构前阶段 3 内的沙箱数据一致）。
DEFAULT_FALLBACK_INFERENCE: dict[str, list[str]] = {
    "inst:Space_001": ["Corridor"],
    "inst:Space_002": ["Bathroom"],
}

#: 默认使用的文本归一化算法。
DEFAULT_NORMALIZER_ALGORITHM = "LLM"


@SPACE_TYPE_CLASSIFIERS.register(
    "LLMMultiStage", aliases=("LLM", "MULTISTAGE", "LLM_MULTI_STAGE")
)
class LLMMultiStageClassifier(ISpaceTypeClassifier):
    """结合图纸文字与大模型常识推理的空间类型识别算法。

    三个阶段与重构前的 ``SemanticEnricher`` 保持一致：

    1. 用 :class:`~src.spatial.contracts.ITextLabelNormalizer` 把原始标注清洗成标准类型；
    2. 用"文字锚点是否落在轮廓内"做精确匹配；
    3. 对仍无标注的轮廓，把面积/家具/邻接关系交给大模型做常识推理。
    """

    name = "LLMMultiStage"

    def __init__(
        self,
        *,
        llm_client=None,
        llm_model: str | None = None,
        text_normalizer: ITextLabelNormalizer | None = None,
        text_normalizer_algorithm: str = DEFAULT_NORMALIZER_ALGORITHM,
        text_normalizer_params: Mapping | None = None,
        prompt_config_path: str | os.PathLike | None = None,
        match_tolerance_mm: float = 0.0,
        min_confidence: float = 0.5,
        fallback_inference: Mapping[str, Sequence[str]] | None = None,
        gateway: LLMJsonGateway | None = None,
    ):
        self.llm_client = llm_client
        self.llm_model = llm_model
        self.prompt_config_path = prompt_config_path
        self.match_tolerance_mm = float(match_tolerance_mm or 0.0)
        self.min_confidence = float(min_confidence)
        self.fallback_inference = {
            key: list(value)
            for key, value in (
                DEFAULT_FALLBACK_INFERENCE if fallback_inference is None else fallback_inference
            ).items()
        }
        self._gateway = gateway
        self._text_normalizer = text_normalizer
        self._normalizer_algorithm = text_normalizer_algorithm
        self._normalizer_params = dict(text_normalizer_params or {})

    # ------------------------------------------------------------------
    # 依赖装配
    # ------------------------------------------------------------------
    @property
    def gateway(self) -> LLMJsonGateway:
        if self._gateway is None:
            self._gateway = LLMJsonGateway(client=self.llm_client, model=self.llm_model)
        return self._gateway

    @property
    def text_normalizer(self) -> ITextLabelNormalizer:
        if self._text_normalizer is None:
            self._text_normalizer = TEXT_LABEL_NORMALIZERS.create(
                self._normalizer_algorithm,
                params=self._normalizer_params,
                services={"llm_client": self.llm_client, "llm_model": self.llm_model},
            )
        return self._text_normalizer

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def classify(
        self,
        *,
        contours: Sequence[SpatialContour] = (),
        texts: Sequence[TextAnnotation] = (),
        components: Sequence[SpatialComponent] = (),
        adjacency: Mapping[str, Sequence[str]] | None = None,
        context: Mapping | None = None,
    ) -> list[SpaceTypePrediction]:
        contours = list(contours)
        components = list(components)

        annotations = self._normalize_texts(texts)
        predictions = match_annotations_to_contours(
            contours,
            annotations,
            tolerance_mm=self.match_tolerance_mm,
            min_confidence=self.min_confidence,
        )
        predictions.extend(self._infer_unmatched(contours, components, adjacency, predictions))
        return predictions

    # ------------------------------------------------------------------
    # 阶段 1：文本归一化
    # ------------------------------------------------------------------
    def _normalize_texts(self, texts: Sequence[TextAnnotation]) -> list[TextAnnotation]:
        if not texts:
            return []

        raw_candidates = [
            item.raw_text
            for item in texts
            if item.raw_text is not None and str(item.raw_text).strip()
        ]
        unique_texts = list(set(raw_candidates))
        if not unique_texts:
            return []

        mapping = self.text_normalizer.normalize(unique_texts)

        annotations: list[TextAnnotation] = []
        for item in texts:
            standard_label = mapping.get(item.raw_text)
            if not standard_label:
                continue
            annotations.append(
                TextAnnotation(
                    raw_text=item.raw_text,
                    point=item.point,
                    standard_label=standard_label,
                )
            )
        return annotations

    # ------------------------------------------------------------------
    # 阶段 3：对没有文字标注的轮廓做上下文推理
    # ------------------------------------------------------------------
    def _infer_unmatched(
        self,
        contours: Sequence[SpatialContour],
        components: Sequence[SpatialComponent],
        adjacency: Mapping[str, Sequence[str]] | None,
        predictions: Sequence[SpaceTypePrediction],
    ) -> list[SpaceTypePrediction]:
        if not contours:
            return []

        matched_ids = {prediction.contour_id for prediction in predictions}
        unmatched = [contour for contour in contours if contour.id not in matched_ids]
        if not unmatched:
            return []

        print(
            f"\n[Stage 3] Found {len(unmatched)} spaces without text labels, "
            "starting commonsense reasoning..."
        )
        context_data = self._build_inference_context(unmatched, components, adjacency)
        prompt = build_inference_prompt(context_data, self._resolve_prompt_path())
        fallback_json = json.dumps(self.fallback_inference, ensure_ascii=False)
        inferred_types = self.gateway.ask_json(prompt, fallback_json)

        known_ids = {contour.id for contour in contours}
        inferred: list[SpaceTypePrediction] = []
        for room_id, space_types in inferred_types.items():
            if room_id not in known_ids:
                continue
            if isinstance(space_types, str):
                space_types = [space_types]
            if not isinstance(space_types, (list, tuple)):
                continue
            for space_type in space_types:
                if not space_type:
                    continue
                inferred.append(
                    SpaceTypePrediction(
                        contour_id=room_id,
                        types=[str(space_type)],
                        source=SOURCE_LLM_INFERENCE,
                    )
                )
        return inferred

    def _build_inference_context(
        self,
        contours: Sequence[SpatialContour],
        components: Sequence[SpatialComponent],
        adjacency: Mapping[str, Sequence[str]] | None,
    ) -> dict[str, dict]:
        """剥离冗余几何，提炼大模型推理所需的"纯文本"上下文。"""
        component_labels = {component.uid: component.specific_type for component in components}
        inference_tasks: dict[str, dict] = {}

        for contour in contours:
            furniture_labels: list[str] = []
            for element_id in contour.elements:
                label = component_labels.get(element_id)
                if not label or label == UNKNOWN_LABEL:
                    continue
                lowered = str(label).lower()
                if "door" in lowered or "window" in lowered:
                    continue
                furniture_labels.append(label)

            inference_tasks[contour.id] = {
                "area_sqm": contour.area_sqm if contour.area_sqm is not None else 0,
                "furniture": furniture_labels,
                "neighbors": resolve_neighbors(contour, adjacency),
            }
        return inference_tasks

    def _resolve_prompt_path(self) -> str | os.PathLike | None:
        if self.prompt_config_path:
            return self.prompt_config_path
        from src.config.config import settings

        return settings.prompt_config_dir
