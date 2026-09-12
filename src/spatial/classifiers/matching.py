# src/spatial/classifiers/matching.py
"""文字标注落位到空间轮廓的几何匹配逻辑，供各分类算法复用。"""

from __future__ import annotations

from typing import Sequence

from shapely.geometry import Point, Polygon

from ..domain import (
    SOURCE_TEXT_MATCH,
    SpatialContour,
    SpaceTypePrediction,
    TextAnnotation,
)

#: 严格包含（锚点落在轮廓内部）时的置信度。
CONFIDENCE_CONTAINED = 1.0

#: 仅靠容差命中（锚点在轮廓外但在容差范围内）时的置信度。
CONFIDENCE_WITHIN_TOLERANCE = 0.5


def make_polygon(contour: SpatialContour) -> Polygon | None:
    """由轮廓外环坐标构造可用的多边形；坐标不足或退化时返回 ``None``。"""
    coords = contour.exterior_coords()
    if len(coords) < 4:
        return None
    try:
        polygon = Polygon(coords)
    except Exception:
        return None
    if polygon.is_empty:
        return None
    if not polygon.is_valid:
        # 自相交等退化环会让 contains() 结果不可靠，先做一次拓扑修复
        polygon = polygon.buffer(0)
        if polygon.is_empty or polygon.geom_type != "Polygon":
            return None
    return polygon


def hit_confidence(polygon: Polygon, point, tolerance_mm: float = 0.0) -> float | None:
    """判断锚点是否命中多边形，返回置信度；未命中返回 ``None``。"""
    pt = Point(point)
    if polygon.contains(pt):
        return CONFIDENCE_CONTAINED
    if tolerance_mm and tolerance_mm > 0 and polygon.distance(pt) <= tolerance_mm:
        return CONFIDENCE_WITHIN_TOLERANCE
    return None


def match_annotations_to_contours(
    contours: Sequence[SpatialContour],
    annotations: Sequence[TextAnnotation],
    *,
    tolerance_mm: float = 0.0,
    min_confidence: float = 0.5,
) -> list[SpaceTypePrediction]:
    """把已归一化的文字标注按"点在多边形内"落位到空间轮廓。

    结果顺序为「轮廓在前、标注在后」，调用方按此顺序写回图谱即可得到稳定输出。
    """
    predictions: list[SpaceTypePrediction] = []
    # 与重构前保持一致：无论是否有可匹配的标注，都打印阶段标题
    print("[Stage 2] Performing geometric spatial intersection matching...")
    if not annotations:
        return predictions

    for contour in contours:
        polygon = make_polygon(contour)
        if polygon is None:
            continue
        for annotation in annotations:
            if not annotation.standard_label:
                continue
            confidence = hit_confidence(polygon, annotation.point, tolerance_mm)
            if confidence is None or confidence < min_confidence:
                continue
            predictions.append(
                SpaceTypePrediction(
                    contour_id=contour.id,
                    types=[annotation.standard_label],
                    source=SOURCE_TEXT_MATCH,
                    annotation=annotation,
                    confidence=confidence,
                )
            )
    return predictions
