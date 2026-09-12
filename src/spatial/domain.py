# src/spatial/domain.py
"""算法无关的领域对象。

本模块只描述"空间轮廓提取"与"空间类型识别"两类任务在算法层面看到的数据，
刻意不包含任何 JSON-LD / 知识图谱细节。图谱适配器
(:mod:`src.topology.builder` 与 :mod:`src.enricher.semantic_enricher`)
负责在图谱节点与这些对象之间转换。

坐标单位统一为图纸单位（本项目为毫米）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

Point2D = Sequence[float]

#: 构件缺失 ``rdfs:label`` 时使用的占位标签，参与类型推断时会被过滤掉。
UNKNOWN_LABEL = "unknown"

#: 预测来源：由图纸文字标注直接命中。
SOURCE_TEXT_MATCH = "text_match"

#: 预测来源：由上下文（面积/家具/邻接）推理得出。
SOURCE_LLM_INFERENCE = "llm_inference"


@dataclass
class TextAnnotation:
    """图纸上的一处原始文字标注及其锚点坐标。"""

    raw_text: str
    point: Point2D
    #: 归一化后的标准建筑空间类型（如 ``"Bedroom"``）。
    standard_label: str | None = None


@dataclass
class SpatialComponent:
    """参与空间语义判断的构件（门、窗、家具等）。"""

    uid: str
    category: str = ""
    specific_type: str | None = None
    geometry: Any = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class SpatialContour:
    """一个封闭的空间轮廓。

    同时用作轮廓提取算法的 *输出* 与类型识别算法的 *输入*：提取算法只需填充
    ``id`` / ``geometry`` / ``label``；分类算法还可以消费图谱侧补充的
    ``area_sqm`` / ``elements`` / ``neighbors`` / ``annotations``。
    """

    id: str
    geometry: Sequence[Point2D] = field(default_factory=tuple)
    label: str = "Unknown"
    #: 面积（平方米），由几何富化阶段写入图谱后回填。
    area_sqm: float | None = None
    #: 落在该轮廓内的构件 uid 列表。
    elements: list[str] = field(default_factory=list)
    #: 与之相邻的轮廓 id 列表。
    neighbors: list[str] = field(default_factory=list)
    #: 已绑定到该轮廓的文字标注。
    annotations: list[TextAnnotation] = field(default_factory=list)
    #: 供具体算法自由存放的附加信息。
    attributes: dict[str, Any] = field(default_factory=dict)

    def exterior_coords(self) -> list[Point2D]:
        """返回外环坐标列表（坐标均转成 ``tuple``，便于 Shapely 消费）。"""
        return [tuple(p) for p in self.geometry]

    def to_legacy_dict(self) -> dict[str, Any]:
        """转换为历史流水线下游（BOT 生成 / 可视化）使用的字典格式。"""
        return {
            "id": self.id,
            "label": self.label,
            "geometry": list(self.geometry),
        }


@dataclass
class SpaceTypePrediction:
    """一次空间类型判定结果。"""

    contour_id: str
    #: 标准建筑空间类型名（如 ``"Bedroom"``），不含命名空间前缀；可包含多个。
    types: list[str] = field(default_factory=list)
    #: :data:`SOURCE_TEXT_MATCH` 或 :data:`SOURCE_LLM_INFERENCE`。
    source: str = SOURCE_TEXT_MATCH
    #: 文字命中时携带的原始标注（含锚点，用于写回 ``props:textAnchors``）。
    annotation: TextAnnotation | None = None
    confidence: float | None = None


def contours_to_legacy_dicts(contours: Sequence[SpatialContour]) -> list[dict[str, Any]]:
    """把轮廓对象批量转换为历史字典格式。"""
    return [contour.to_legacy_dict() for contour in contours]


def resolve_neighbors(
    contour: SpatialContour,
    adjacency: dict[str, Sequence[str]] | None = None,
) -> list[str]:
    """解析轮廓的邻接关系：优先使用显式 ``adjacency``，否则回退到轮廓自带字段。"""
    if adjacency and contour.id in adjacency:
        return list(adjacency[contour.id])
    return list(contour.neighbors)
