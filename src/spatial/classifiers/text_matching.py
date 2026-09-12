# src/spatial/classifiers/text_matching.py
"""纯几何的文字落位分类算法：只用图纸标注与轮廓求交，不依赖大模型。"""

from __future__ import annotations

from typing import Mapping, Sequence

from ..contracts import ISpaceTypeClassifier, ITextLabelNormalizer
from ..domain import (
    SpatialComponent,
    SpatialContour,
    SpaceTypePrediction,
    TextAnnotation,
)
from ..registry import SPACE_TYPE_CLASSIFIERS, TEXT_LABEL_NORMALIZERS
from .matching import match_annotations_to_contours

#: 默认使用的文本归一化算法（查表，离线可用）。
DEFAULT_NORMALIZER_ALGORITHM = "Dictionary"


@SPACE_TYPE_CLASSIFIERS.register("TextMatching", aliases=("TEXT", "GEOMETRY_ONLY"))
class TextMatchingClassifier(ISpaceTypeClassifier):
    """仅依据图纸文字标注判定空间类型。

    相比 :class:`~src.spatial.classifiers.llm_multistage.LLMMultiStageClassifier`，
    本算法不做常识推理，因此结果完全确定、可离线复现，适合作为基线或降级方案。
    """

    name = "TextMatching"

    def __init__(
        self,
        *,
        text_normalizer: ITextLabelNormalizer | None = None,
        text_normalizer_algorithm: str = DEFAULT_NORMALIZER_ALGORITHM,
        text_normalizer_params: Mapping | None = None,
        match_tolerance_mm: float = 0.0,
        min_confidence: float = 0.5,
    ):
        self.match_tolerance_mm = float(match_tolerance_mm or 0.0)
        self.min_confidence = float(min_confidence)
        self._text_normalizer = text_normalizer
        self._normalizer_algorithm = text_normalizer_algorithm
        self._normalizer_params = dict(text_normalizer_params or {})

    @property
    def text_normalizer(self) -> ITextLabelNormalizer:
        if self._text_normalizer is None:
            self._text_normalizer = TEXT_LABEL_NORMALIZERS.create(
                self._normalizer_algorithm,
                params=self._normalizer_params,
            )
        return self._text_normalizer

    def classify(
        self,
        *,
        contours: Sequence[SpatialContour] = (),
        texts: Sequence[TextAnnotation] = (),
        components: Sequence[SpatialComponent] = (),
        adjacency: Mapping[str, Sequence[str]] | None = None,
        context: Mapping | None = None,
    ) -> list[SpaceTypePrediction]:
        annotations = self._normalize_texts(texts)
        return match_annotations_to_contours(
            list(contours),
            annotations,
            tolerance_mm=self.match_tolerance_mm,
            min_confidence=self.min_confidence,
        )

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
