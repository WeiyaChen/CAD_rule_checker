# src/spatial/contracts.py
"""空间轮廓提取与空间类型识别的抽象接口。

新增同类算法时只需实现这里的抽象类，并在对应的 ``Registry`` 中注册即可，
流水线其余部分无需改动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from .domain import SpatialComponent, SpatialContour, SpaceTypePrediction, TextAnnotation


class ISpatialContourExtractor(ABC):
    """空间轮廓提取器。

    典型输入是已经预处理过的墙体线段与门窗补片；输出是封闭空间轮廓列表。
    坐标单位为图纸单位（毫米）。
    """

    #: 注册到 :data:`src.spatial.registry.CONTOUR_EXTRACTORS` 时使用的算法名。
    name: str = "unknown"

    #: 可视化文件名后缀，产出形如 ``<图纸名>_<suffix>.png``，便于多算法产物并存对比。
    visualization_suffix: str = "contour"

    @abstractmethod
    def extract(
        self,
        *,
        walls: Sequence[Any] = (),
        doors: Sequence[Any] = (),
        windows: Sequence[Any] = (),
        texts: Sequence[Any] = (),
        components: Sequence[SpatialComponent] = (),
        context: Mapping[str, Any] | None = None,
    ) -> list[SpatialContour]:
        """从墙体/门窗几何中提取封闭空间轮廓。

        Args:
            walls: 真实墙体几何（Shapely ``LineString``/``MultiLineString``）。
            doors: 门洞几何（Shapely ``Polygon``），用于生成虚拟封口边。
            windows: 窗洞几何（Shapely ``Polygon``）。
            texts: 图纸文字标注，(文本, (x, y)) 或 :class:`TextAnnotation`。
            components: 已识别的构件，供需要构件信息的算法使用。
            context: 算法自定义的附加上下文。

        Returns:
            空间轮廓列表；无法提取时返回空列表。
        """

    def get_visualization_data(self) -> Any:
        """返回该算法专属的可视化载荷（默认无）。

        实现方可返回任意结构，配套的可视化函数按算法约定解析。
        """
        return None


class ISpaceTypeClassifier(ABC):
    """空间类型识别（分类）器。"""

    #: 注册到 :data:`src.spatial.registry.SPACE_TYPE_CLASSIFIERS` 时使用的算法名。
    name: str = "unknown"

    @abstractmethod
    def classify(
        self,
        *,
        contours: Sequence[SpatialContour] = (),
        texts: Sequence[TextAnnotation] = (),
        components: Sequence[SpatialComponent] = (),
        adjacency: Mapping[str, Sequence[str]] | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> list[SpaceTypePrediction]:
        """推断每个空间轮廓的类型。

        Args:
            contours: 待分类的空间轮廓（含几何、面积、包含构件、邻接信息）。
            texts: 图纸文字标注；分类器负责归一化后做几何落位。
            components: 用于语义推理的构件（家具等）。
            adjacency: 可选的显式邻接表 ``{轮廓 id: [相邻轮廓 id, ...]}``；
                提供时优先于 ``SpatialContour.neighbors``。
            context: 算法自定义的附加上下文。

        Returns:
            预测结果列表。同一轮廓可产生多条结果（例如多处文字标注命中），
            调用方应按返回顺序依次写回。
        """


class ITextLabelNormalizer(ABC):
    """原始图纸文本 → 标准建筑空间类型 的归一化器。"""

    name: str = "unknown"

    @abstractmethod
    def normalize(self, raw_texts: Sequence[str]) -> dict[str, str]:
        """返回 ``{原始文本: 标准类型}`` 映射；无法识别的文本不应出现在结果中。"""
