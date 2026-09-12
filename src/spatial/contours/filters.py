# src/spatial/contours/filters.py
"""空间多边形可信度过滤（各轮廓算法共用）。

墙体在图纸上通常画成 200~300mm 厚的闭合轮廓，因此几何多边形化的结果里除了
真实房间，还会夹杂大量"墙体空腔""墙缝工字形"之类的伪多边形。这里把 CDT 与
RGP 共用的四道防线集中到一处，保证两种算法对"什么算房间"的口径一致：

1. 绝对面积：剔除 2㎡ 以下碎片；
2. 真实净宽（形态学负缓冲）：墙腔收缩 ``erode_mm`` 后会消失，真实房间不会；
3. 外接矩形短边：剔除细长墙缝；
4. 紧凑度 + 实心率：剔除"工""十"字形扭曲边界。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from shapely.geometry import Point, Polygon


@dataclass(frozen=True)
class SpaceShapeFilter:
    """空间轮廓形态过滤器，``check()`` 返回拒绝原因（``None`` 表示通过）。"""

    min_area_mm2: float = 2000000.0
    erode_mm: float = 250.0
    min_width_mm: float = 600.0
    min_compactness: float = 0.08
    min_solidity: float = 0.25

    @classmethod
    def from_params(cls, params: Mapping[str, Any] | None) -> "SpaceShapeFilter":
        """从参数字典构造；缺失项沿用默认值，因此两种算法的参数可互换。"""
        params = params or {}
        known = cls.__dataclass_fields__
        return cls(**{key: float(params[key]) for key in known if key in params})

    def metrics(self, poly: Polygon) -> dict[str, float]:
        """计算用于判定与报告的形状指标。"""
        rect_coords = list(poly.minimum_rotated_rectangle.exterior.coords)
        edge1 = Point(rect_coords[0]).distance(Point(rect_coords[1]))
        edge2 = Point(rect_coords[1]).distance(Point(rect_coords[2]))
        hull_area = poly.convex_hull.area
        return {
            "area": poly.area,
            "min_width": min(edge1, edge2),
            "compactness": (4 * math.pi * poly.area) / (poly.length ** 2) if poly.length else 0.0,
            "solidity": poly.area / hull_area if hull_area > 0 else 0.0,
        }

    def check(self, poly: Polygon) -> str | None:
        """返回拒绝原因；``None`` 表示该多边形可以保留为空间轮廓。"""
        if poly.area < self.min_area_mm2:
            return "area_too_small"
        if poly.buffer(-self.erode_mm).is_empty:
            return "too_narrow"
        m = self.metrics(poly)
        if m["min_width"] < self.min_width_mm:
            return "slender"
        if m["compactness"] < self.min_compactness or m["solidity"] < self.min_solidity:
            return "irregular_shape"
        return None


__all__ = ["SpaceShapeFilter"]
