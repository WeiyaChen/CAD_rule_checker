# src/spatial/contours/rgp.py
"""基于几何规则的空间轮廓提取（RGP, Rule-based Geometric Polygonization）。

与 CDT 路线（先三角剖分、再在网格上区域生长）不同，RGP 完全工作在"线段 + 平面图"
上：把边界图元整理成一个平面直线图，再按半边轮转（rotation system）规则直接遍历
出所有有界面，因此**不需要任何三角剖分库**。

实现步骤与设计文档一一对应（:meth:`RGPContourExtractor.extract` 中按序调用）::

    输入：预测得到的边界图元（墙体线段）
     1. 坐标归一化
     2. 重复点 / 重复段剔除
     3. 端点吸附
     4. 共线线段合并
     5. 短缺口补全
     6. 线段求交与打断
     7. 平面图构建
     8. 多边形化
     9. 小面积 / 细长区域过滤
    10. 外部面剔除
    输出：房间多边形集合

工程要点（来自真实图纸的实测结论）：

* 图纸上的墙体是 **200~300mm 厚的闭合轮廓**，直接多边形化会同时得到"房间面"和
  "墙腔面"，因此必须保留与 CDT 同口径的形态过滤（见 :mod:`.filters`）。
* 门窗洞口在图上表现为 **墙体轮廓线之间的短缺口**，缺口两端是"拐角节点"而不是
  "悬空端点"，所以缺口补全不能只看悬挂端点，而要求补出来的边在两端都能与原有
  墙体**共线延续**（见 :meth:`RGPContourExtractor._step5_complete_gaps`）。
* 参数名与 :class:`~.cdt.CDTContourExtractor` 保持超集兼容，切换
  ``spatial.contour.algorithm`` 时无需改动 ``params`` 配置块。
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

from .filters import SpaceShapeFilter
from ..contracts import ISpatialContourExtractor
from ..domain import SpatialComponent, SpatialContour
from ..registry import CONTOUR_EXTRACTORS

Point2D = tuple[float, float]
Segment = tuple[int, int]

#: 缺口补全的两条路线，仅用于统计与可视化区分。
BRIDGE_GAP = "gap_completion"
BRIDGE_OPENING = "opening_seal"


@CONTOUR_EXTRACTORS.register(
    "RGP", aliases=("RULE_BASED", "POLYGONIZE", "GEOMETRIC_POLYGONIZATION")
)
class RGPContourExtractor(ISpatialContourExtractor):
    """基于几何规则的房间多边形化，不依赖 CDT。"""

    name = "RGP"
    visualization_suffix = "rgp"

    def __init__(
        self,
        *,
        # —— 与 CDT 共用的形态过滤参数（同名同义，便于直接切换算法）——
        min_area_mm2: float = 2000000.0,
        erode_mm: float = 250.0,
        min_width_mm: float = 600.0,
        min_compactness: float = 0.08,
        min_solidity: float = 0.25,
        # —— 与 CDT 共用的门窗虚拟封口参数 ——
        virtual_blocker_dist_tol_mm: float = 300.0,
        virtual_blocker_max_len_mm: float = 3500.0,
        virtual_blocker_angle_tol_deg: float = 0.0,
        # —— RGP 专有参数 ——
        coord_precision_mm: float = 1.0,
        dup_tol_mm: float = 1.0,
        snap_tol_mm: float = 10.0,
        collinear_angle_tol_deg: float = 1.0,
        collinear_offset_tol_mm: float = 1.0,
        max_gap_mm: float = 3000.0,
        gap_angle_tol_deg: float = 10.0,
    ):
        self.min_area_mm2 = float(min_area_mm2)
        self.erode_mm = float(erode_mm)
        self.min_width_mm = float(min_width_mm)
        self.min_compactness = float(min_compactness)
        self.min_solidity = float(min_solidity)
        self.virtual_blocker_dist_tol_mm = float(virtual_blocker_dist_tol_mm)
        self.virtual_blocker_max_len_mm = float(virtual_blocker_max_len_mm)
        self.virtual_blocker_angle_tol_deg = float(virtual_blocker_angle_tol_deg)

        self.coord_precision_mm = max(float(coord_precision_mm), 1e-6)
        self.dup_tol_mm = max(float(dup_tol_mm), 0.0)
        self.snap_tol_mm = max(float(snap_tol_mm), 0.0)
        self.collinear_angle_tol_deg = max(float(collinear_angle_tol_deg), 1e-6)
        self.collinear_offset_tol_mm = max(float(collinear_offset_tol_mm), 1e-6)
        self.max_gap_mm = float(max_gap_mm)
        self.gap_angle_tol_deg = float(gap_angle_tol_deg)

        self.shape_filter = SpaceShapeFilter(
            min_area_mm2=self.min_area_mm2,
            erode_mm=self.erode_mm,
            min_width_mm=self.min_width_mm,
            min_compactness=self.min_compactness,
            min_solidity=self.min_solidity,
        )

        # 最近一次 extract() 的产物，供可视化读取
        self.points: list[Point2D] = []
        self.segments: list[Segment] = []
        self.bridges: list[tuple[int, int, str]] = []
        self.stats: dict[str, Any] = {}

    # ------------------------------------------------------------------ 公共入口
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
        """按 10 步流水线把墙体线段转成房间多边形。

        ``texts`` / ``components`` / ``context`` 不参与几何计算，保留参数是为了与
        其它轮廓算法保持统一调用约定；``doors`` / ``windows`` 仅作为缺口补全
        第 2 条路线（洞口封堵）的提示。
        """
        self.points = []
        self.segments = []
        self.bridges = []
        self.stats = {}

        raw = self._step1_normalize(walls)
        if not raw:
            return []

        points, segments, duplicate_segments = self._step2_remove_duplicates(raw)
        points, segments, snapped_nodes = self._step3_snap_endpoints(points, segments)
        segments, merged_segments = self._step4_merge_collinear(points, segments)
        if len(points) < 3 or not segments:
            return []

        openings = self._collect_openings(doors, windows)
        bridges = self._step5_complete_gaps(points, segments, openings)
        points, segments = self._step6_split_at_intersections(
            points, segments + [(a, b) for a, b, _ in bridges]
        )

        adjacency = self._step7_build_planar_graph(segments)
        faces = self._step8_polygonize(points, adjacency)
        regions, rejected = self._step9_filter_regions(points, faces)
        kept = self._step10_remove_exterior_faces(regions)

        # 面积从大到小编号，保证多次运行结果稳定
        kept.sort(key=lambda item: (-round(item[0].area, 3), item[0].bounds[0], item[0].bounds[1]))
        results = [
            SpatialContour(
                id=f"Space_{index:03d}",
                label="Unknown",
                geometry=list(poly.exterior.coords),
            )
            for index, (poly, _signed_area) in enumerate(kept, start=1)
        ]

        self.points = points
        self.segments = segments
        self.bridges = bridges
        self.stats = {
            "input_segments": len(raw),
            "duplicate_segments": duplicate_segments,
            "snapped_nodes": snapped_nodes,
            "merged_segments": merged_segments,
            "nodes": len(points),
            "segments": len(segments),
            "gap_bridges": sum(1 for _, _, kind in bridges if kind == BRIDGE_GAP),
            "opening_seals": sum(1 for _, _, kind in bridges if kind == BRIDGE_OPENING),
            "faces": len(faces),
            "rejected_faces": dict(sorted(rejected.items())),
            "exterior_faces_removed": len(regions) - len(kept),
            "rooms": len(results),
        }
        print(
            "[RGP] segments {input_segments}→{segments} nodes {nodes} "
            "(snap {snapped_nodes}, merge {merged_segments}, dup {duplicate_segments}) "
            "bridges {gap_bridges}+{opening_seals} faces {faces} → rooms {rooms} "
            "rejected {rejected_faces}".format(**self.stats)
        )
        return results

    def get_visualization_data(self):
        """返回 ``(墙体边, 虚拟封口边, None, 平面图节点)``。

        RGP 没有三角网，第 3 项固定为 ``None``，可视化函数会跳过 ``triplot``
        只画节点散点；虚拟封口边仍以红色虚线呈现，便于与 CDT 产物对照。
        """
        if not self.points:
            return [], [], None, []
        real_lines = [
            LineString([self.points[a], self.points[b]]) for a, b in self.segments
        ]
        bridge_lines = [
            LineString([self.points[a], self.points[b]]) for a, b, _ in self.bridges
        ]
        return real_lines, bridge_lines, None, np.asarray(self.points, dtype=float)

    # ------------------------------------------------------------------ 通用工具
    @staticmethod
    def _iter_line_coords(walls: Iterable[Any]) -> Iterable[list[Any]]:
        """把墙体几何统一展开成坐标序列（支持 LineString / MultiLineString / Polygon）。"""
        for geom in walls or ():
            if geom is None:
                continue
            geom_type = getattr(geom, "geom_type", None)
            if geom_type == "LineString":
                yield list(geom.coords)
            elif geom_type == "MultiLineString":
                for part in geom.geoms:
                    yield list(part.coords)
            elif geom_type == "Polygon":
                yield list(geom.exterior.coords)
            else:
                for part in getattr(geom, "geoms", ()):
                    if getattr(part, "geom_type", None) == "LineString":
                        yield list(part.coords)

    @staticmethod
    def _unit(origin: Point2D, target: Point2D) -> tuple[float, float] | None:
        """``origin → target`` 的单位方向向量；退化时返回 ``None``。"""
        dx, dy = target[0] - origin[0], target[1] - origin[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return None
        return dx / length, dy / length

    @staticmethod
    def _angle_between(u: tuple[float, float], v: tuple[float, float]) -> float:
        """两个方向的夹角（度，0~180）。"""
        cos_value = max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))
        return math.degrees(math.acos(cos_value))

    @staticmethod
    def _build_adjacency(segments: Sequence[Segment]) -> dict[int, set[int]]:
        adjacency: dict[int, set[int]] = defaultdict(set)
        for a, b in segments:
            adjacency[a].add(b)
            adjacency[b].add(a)
        return adjacency

    @staticmethod
    def _collect_openings(doors: Sequence[Any], windows: Sequence[Any]) -> list[Polygon]:
        openings: list[Polygon] = []
        for geom in list(doors or ()) + list(windows or ()):
            if geom is None:
                continue
            geom_type = getattr(geom, "geom_type", None)
            if geom_type == "Polygon" and not geom.is_empty:
                openings.append(geom)
            elif geom_type == "MultiPolygon":
                openings.extend(part for part in geom.geoms if not part.is_empty)
        return openings

    # ------------------------------------------------------------------- 步骤 1
    def _step1_normalize(self, walls: Iterable[Any]) -> list[tuple[Point2D, Point2D]]:
        """1. 坐标归一化：统一到毫米精度网格，并把折线拆成基本线段。"""
        step = self.coord_precision_mm
        raw: list[tuple[Point2D, Point2D]] = []
        for coords in self._iter_line_coords(walls):
            for i in range(len(coords) - 1):
                a = (round(coords[i][0] / step) * step + 0.0, round(coords[i][1] / step) * step + 0.0)
                b = (
                    round(coords[i + 1][0] / step) * step + 0.0,
                    round(coords[i + 1][1] / step) * step + 0.0,
                )
                if a != b:
                    raw.append((a, b))
        return raw

    # ------------------------------------------------------------------- 步骤 2
    def _step2_remove_duplicates(
        self, raw: Sequence[tuple[Point2D, Point2D]]
    ) -> tuple[list[Point2D], list[Segment], int]:
        """2. 去重：相同坐标只保留一个节点，重复/自环线段剔除。"""
        index: dict[Point2D, int] = {}
        points: list[Point2D] = []
        segments: list[Segment] = []
        seen: set[Segment] = set()
        duplicate_segments = 0

        for a, b in raw:
            ia = index.get(a)
            if ia is None:
                index[a] = ia = len(points)
                points.append(a)
            ib = index.get(b)
            if ib is None:
                index[b] = ib = len(points)
                points.append(b)
            if ia == ib:
                continue  # 自环（零长度）已在步骤 1 处理，这里兜底
            key = (ia, ib) if ia < ib else (ib, ia)
            if key in seen:
                duplicate_segments += 1
                continue
            seen.add(key)
            segments.append(key)
        return points, segments, duplicate_segments

    # ------------------------------------------------------------------- 步骤 3
    def _step3_snap_endpoints(
        self, points: Sequence[Point2D], segments: Sequence[Segment]
    ) -> tuple[list[Point2D], list[Segment], int]:
        """3. 端点吸附：``snap_tol_mm`` 内的节点合并为同一节点。

        用格网分桶 + 并查集做传递闭包，代表点取簇内字典序最小的坐标，
        因此结果与输入顺序无关、可重复。
        """
        tolerance = self.snap_tol_mm
        if tolerance <= 0 or len(points) < 2:
            return list(points), list(segments), 0

        parent = list(range(len(points)))

        def find(node: int) -> int:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        def union(left: int, right: int) -> None:
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[max(root_left, root_right)] = min(root_left, root_right)

        buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        for node, (x, y) in enumerate(points):
            buckets[(math.floor(x / tolerance), math.floor(y / tolerance))].append(node)

        squared_tolerance = tolerance * tolerance
        for (cell_x, cell_y), members in buckets.items():
            for offset_x in (-1, 0, 1):
                for offset_y in (-1, 0, 1):
                    others = buckets.get((cell_x + offset_x, cell_y + offset_y))
                    if not others:
                        continue
                    for node in members:
                        px, py = points[node]
                        for other in others:
                            qx, qy = points[other]
                            if (px - qx) ** 2 + (py - qy) ** 2 <= squared_tolerance:
                                union(node, other)

        clusters: dict[int, list[int]] = defaultdict(list)
        for node in range(len(points)):
            clusters[find(node)].append(node)

        representatives = {root: min(points[node] for node in members) for root, members in clusters.items()}
        remap: dict[int, int] = {}
        new_points: list[Point2D] = []
        for root in sorted(clusters, key=lambda key: representatives[key]):
            new_id = len(new_points)
            new_points.append(representatives[root])
            for node in clusters[root]:
                remap[node] = new_id

        new_segments: list[Segment] = []
        seen: set[Segment] = set()
        for a, b in segments:
            ia, ib = remap[a], remap[b]
            if ia == ib:
                continue
            key = (ia, ib) if ia < ib else (ib, ia)
            if key in seen:
                continue
            seen.add(key)
            new_segments.append(key)

        return new_points, new_segments, len(points) - len(new_points)

    # ------------------------------------------------------------------- 步骤 4
    def _step4_merge_collinear(
        self, points: Sequence[Point2D], segments: Sequence[Segment]
    ) -> tuple[list[Segment], int]:
        """4. 共线线段合并：同一直线上首尾相接/重叠的区间合成一条。

        注意这里**只合并相接或重叠**的区间，绝不跨越空隙——跨越空隙属于步骤 5
        的职责，否则会把门窗洞口一并封死。
        """
        groups: dict[tuple[int, int, int], list[tuple[float, float, int, int]]] = defaultdict(list)
        for a, b in segments:
            pa, pb = points[a], points[b]
            direction = self._unit(pa, pb)
            if direction is None:
                continue
            ux, uy = direction
            if ux < -1e-12 or (abs(ux) <= 1e-12 and uy < 0.0):
                ux, uy = -ux, -uy  # 统一朝向，使同一直线的正反两个方向落进同一组
            param_a = ux * pa[0] + uy * pa[1]
            param_b = ux * pb[0] + uy * pb[1]
            item = (param_a, param_b, a, b) if param_a <= param_b else (param_b, param_a, b, a)
            groups[self._line_key(ux, uy, pa)].append(item)

        merged: list[Segment] = []
        merged_segments = 0
        for items in groups.values():
            items.sort()
            current_lo, current_hi, current_a, current_b = items[0]
            for lo, hi, a, b in items[1:]:
                if lo <= current_hi + self.dup_tol_mm:
                    if hi > current_hi:
                        current_hi, current_b = hi, b
                    merged_segments += 1
                else:
                    merged.append((current_a, current_b))
                    current_lo, current_hi, current_a, current_b = lo, hi, a, b
            merged.append((current_a, current_b))

        return merged, merged_segments

    def _line_key(self, ux: float, uy: float, point: Point2D) -> tuple[int, int, int]:
        """把"无限直线"量化成可哈希的桶：方向角 + 垂距。"""
        direction_buckets = max(1.0 / math.sin(math.radians(self.collinear_angle_tol_deg)), 1.0)
        offset = -uy * point[0] + ux * point[1]
        return (
            round(ux * direction_buckets),
            round(uy * direction_buckets),
            round(offset / self.collinear_offset_tol_mm),
        )

    # ------------------------------------------------------------------- 步骤 5
    def _step5_complete_gaps(
        self,
        points: Sequence[Point2D],
        segments: Sequence[Segment],
        openings: Sequence[Polygon],
    ) -> list[tuple[int, int, str]]:
        """5. 短缺口补全：在断口两端之间补一条虚拟封口边。

        两条路线：

        * 路线 A（共线延续，主路线）：沿某条墙体的方向继续往前找最近的节点，
          要求该节点处的墙体也沿同一方向**继续远离**（双向延续），并且新边不与
          任何已有线段相交。实测图纸的门窗洞口两端都是这种"拐角节点"，因此这是
          补洞的主要手段，也是悬挂端点无法覆盖的情形。
        * 路线 B（洞口封堵，兜底）：两端点都紧贴同一个门窗补片、连线长度受限且
          与补片某条边平行时封口，规则与 CDT 的虚拟阻挡边判定保持一致。
        """
        adjacency = self._build_adjacency(segments)
        lines = [LineString([points[a], points[b]]) for a, b in segments]
        tree = STRtree(lines) if lines else None
        coords = np.asarray(points, dtype=float)
        neighbourhood: dict[int, list[tuple[float, int, tuple[float, float]]]] = {}

        def candidates(node: int) -> list[tuple[float, int, tuple[float, float]]]:
            """返回 (距离, 节点, 单位方向) 列表，按距离升序，距离相同按节点号升序。"""
            cached = neighbourhood.get(node)
            if cached is not None:
                return cached
            distances = np.hypot(coords[:, 0] - coords[node, 0], coords[:, 1] - coords[node, 1])
            indices = np.where((distances > self.dup_tol_mm) & (distances <= self.max_gap_mm))[0]
            items: list[tuple[float, int, tuple[float, float]]] = []
            for other in sorted(indices.tolist(), key=lambda index: (distances[index], index)):
                direction = self._unit(points[node], points[other])
                if direction is not None:
                    items.append((float(distances[other]), int(other), direction))
            neighbourhood[node] = items
            return items

        bridges: list[tuple[int, int, str]] = []
        used: set[Segment] = set()

        # —— 路线 A：共线延续 ——
        for node in sorted(adjacency):
            for previous in sorted(adjacency[node]):
                direction = self._unit(points[previous], points[node])
                if direction is None:
                    continue
                for _distance, target, to_target in candidates(node):
                    if target in adjacency[node]:
                        continue
                    if self._angle_between(direction, to_target) > self.gap_angle_tol_deg + 1e-9:
                        continue
                    if not self._continues_away(adjacency, points, target, direction):
                        continue
                    if self._crosses_existing(points, tree, segments, node, target):
                        continue
                    key = (min(node, target), max(node, target))
                    bridges.append((node, target, BRIDGE_GAP))
                    used.add(key)
                    break

        # —— 路线 B：洞口封堵（兜底）——
        if openings and self.virtual_blocker_dist_tol_mm > 0:
            max_length = min(self.max_gap_mm, self.virtual_blocker_max_len_mm)
            distance_tolerance = self.virtual_blocker_dist_tol_mm
            for patch in openings:
                nearby = {
                    node
                    for node in range(len(points))
                    if Point(points[node]).distance(patch) <= distance_tolerance
                }
                if len(nearby) < 2:
                    continue
                for node in sorted(nearby):
                    for previous in sorted(adjacency.get(node, ())):
                        direction = self._unit(points[previous], points[node])
                        if direction is None:
                            continue
                        for distance, target, to_target in candidates(node):
                            if target not in nearby or target in adjacency[node]:
                                continue
                            if distance > max_length:
                                continue
                            if self._angle_between(direction, to_target) > self.gap_angle_tol_deg + 1e-9:
                                continue
                            if not self._is_parallel_to_patch(to_target, patch):
                                continue
                            if self._crosses_existing(points, tree, segments, node, target):
                                continue
                            key = (min(node, target), max(node, target))
                            if key in used:
                                continue
                            bridges.append((node, target, BRIDGE_OPENING))
                            used.add(key)
                            break

        return bridges

    def _continues_away(
        self,
        adjacency: Mapping[int, set[int]],
        points: Sequence[Point2D],
        node: int,
        direction: tuple[float, float],
    ) -> bool:
        """``node`` 处是否存在沿 ``direction`` 继续远离的墙体。"""
        for other in adjacency.get(node, ()):
            unit = self._unit(points[node], points[other])
            if unit is not None and self._angle_between(unit, direction) <= self.gap_angle_tol_deg + 1e-9:
                return True
        return False

    def _is_parallel_to_patch(self, direction: tuple[float, float], patch: Polygon) -> bool:
        """连线方向是否与补片某条边平行（判定口径与 CDT 一致）。"""
        cos_threshold = math.cos(math.radians(self.virtual_blocker_angle_tol_deg))
        ring = list(patch.exterior.coords)
        for i in range(len(ring) - 1):
            edge = self._unit(ring[i], ring[i + 1])
            if edge is None:
                continue
            dot = abs(direction[0] * edge[0] + direction[1] * edge[1])
            if dot >= cos_threshold - 1e-12:
                return True
        return False

    def _crosses_existing(
        self,
        points: Sequence[Point2D],
        tree: STRtree | None,
        segments: Sequence[Segment],
        start: int,
        end: int,
    ) -> bool:
        """待补的边是否穿越/压叠任何已有线段（共端点或 T 形接触不算穿越）。"""
        if tree is None:
            return False
        candidate = LineString([points[start], points[end]])
        start_point, end_point = Point(points[start]), Point(points[end])
        for index in tree.query(candidate):
            a, b = segments[int(index)]
            if start in (a, b) or end in (a, b):
                continue  # 与待补边共端点：两条直线只会在该点相交
            intersection = candidate.intersection(LineString([points[a], points[b]]))
            if intersection.is_empty:
                continue
            if intersection.geom_type == "Point" and (
                intersection.equals(start_point) or intersection.equals(end_point)
            ):
                continue  # T 形接触：墙在此处拐弯，不构成穿越
            return True
        return False

    # ------------------------------------------------------------------- 步骤 6
    def _step6_split_at_intersections(
        self, points: Sequence[Point2D], segments: Sequence[Segment]
    ) -> tuple[list[Point2D], list[Segment]]:
        """6. 线段求交与打断：在交点/T 形接点处插点并打断线段。

        已有节点编号保持不变（只在尾部追加新节点），以便缺口补全记录仍然有效。
        """
        if not segments:
            return list(points), []

        lines = [LineString([points[a], points[b]]) for a, b in segments]
        tree = STRtree(lines)
        split_points: dict[int, list[tuple[float, float]]] = defaultdict(list)
        for index, line in enumerate(lines):
            for other_index in tree.query(line):
                other_index = int(other_index)
                if other_index == index:
                    continue
                for point in self._iter_intersection_points(line.intersection(lines[other_index])):
                    split_points[index].append(point)

        new_points: list[Point2D] = list(points)
        index_of: dict[Point2D, int] = {point: index for index, point in enumerate(new_points)}
        step = self.coord_precision_mm

        def node_of(x: float, y: float) -> int:
            key = (round(x / step) * step + 0.0, round(y / step) * step + 0.0)
            node = index_of.get(key)
            if node is None:
                index_of[key] = node = len(new_points)
                new_points.append(key)
            return node

        split_segments: list[Segment] = []
        seen: set[Segment] = set()
        for index, (a, b) in enumerate(segments):
            pa, pb = points[a], points[b]
            dx, dy = pb[0] - pa[0], pb[1] - pa[1]
            squared_length = dx * dx + dy * dy
            if squared_length <= 0:
                continue
            parameters = {0.0, 1.0}
            for x, y in split_points.get(index, ()):
                parameter = ((x - pa[0]) * dx + (y - pa[1]) * dy) / squared_length
                if 0.0 < parameter < 1.0:
                    parameters.add(round(parameter, 9))
            nodes = [
                node_of(pa[0] + parameter * dx, pa[1] + parameter * dy)
                for parameter in sorted(parameters)
            ]
            for left, right in zip(nodes, nodes[1:]):
                if left == right:
                    continue
                key = (left, right) if left < right else (right, left)
                if key in seen:
                    continue
                seen.add(key)
                split_segments.append(key)

        return new_points, split_segments

    @staticmethod
    def _iter_intersection_points(geometry: Any) -> Iterable[tuple[float, float]]:
        """把交点几何展开成坐标序列（Point / MultiPoint / 重叠线段的端点）。"""
        if geometry is None or geometry.is_empty:
            return
        geom_type = geometry.geom_type
        if geom_type == "Point":
            yield (geometry.x, geometry.y)
        elif geom_type == "LineString":
            for x, y in geometry.coords:
                yield (x, y)
        else:
            for part in getattr(geometry, "geoms", ()):
                yield from RGPContourExtractor._iter_intersection_points(part)

    # ------------------------------------------------------------------- 步骤 7
    def _step7_build_planar_graph(
        self, segments: Sequence[Segment]
    ) -> dict[int, list[int]]:
        """7. 平面图构建：邻接表（邻居按节点号排序，保证遍历顺序确定）。"""
        adjacency = self._build_adjacency(segments)
        return {node: sorted(neighbours) for node, neighbours in adjacency.items()}

    # ------------------------------------------------------------------- 步骤 8
    def _step8_polygonize(
        self, points: Sequence[Point2D], adjacency: Mapping[int, list[int]]
    ) -> list[tuple[list[int], float]]:
        """8. 多边形化：半边轮转遍历出所有面，并计算有向面积。

        每个节点按方位角排序得到旋转系统；对一条有向边 ``u→v``，在 ``v`` 处取
        ``u`` 的**前一个**邻居继续走，即可把每个面恰好遍历一次。有界面为逆时针
        （有向面积 > 0），外部面为顺时针（有向面积 < 0）。
        """
        order: dict[int, list[int]] = {
            node: sorted(
                neighbours,
                key=lambda other: math.atan2(
                    points[other][1] - points[node][1], points[other][0] - points[node][0]
                ),
            )
            for node, neighbours in adjacency.items()
        }
        position: dict[int, dict[int, int]] = {
            node: {other: index for index, other in enumerate(neighbours)}
            for node, neighbours in order.items()
        }

        visited: set[Segment] = set()
        faces: list[tuple[list[int], float]] = []
        for node in sorted(order):
            for neighbour in order[node]:
                if (node, neighbour) in visited:
                    continue
                ring = self._trace_face(node, neighbour, order, position, visited)
                if len(ring) >= 3:
                    faces.append((ring, self._signed_area(points, ring)))
        return faces

    @staticmethod
    def _trace_face(
        start: int,
        second: int,
        order: Mapping[int, list[int]],
        position: Mapping[int, dict[int, int]],
        visited: set[Segment],
    ) -> list[int]:
        """从有向边 ``start→second`` 出发绕行一圈，返回该面的节点环。"""
        limit = 4 * sum(len(neighbours) for neighbours in order.values()) + 8
        ring = [start]
        current_from, current_to = start, second
        while True:
            visited.add((current_from, current_to))
            ring.append(current_to)
            neighbours = order[current_to]
            next_node = neighbours[(position[current_to][current_from] - 1) % len(neighbours)]
            current_from, current_to = current_to, next_node
            if (current_from, current_to) == (start, second):
                break
            if len(ring) > limit:  # 防御性兜底，理论上不可达
                break
        ring.pop()  # 末位与首位重复
        return ring

    @staticmethod
    def _signed_area(points: Sequence[Point2D], ring: Sequence[int]) -> float:
        """鞋带公式；折返（悬挂边）段贡献为 0。"""
        total = 0.0
        count = len(ring)
        for index in range(count):
            x1, y1 = points[ring[index]]
            x2, y2 = points[ring[(index + 1) % count]]
            total += x1 * y2 - x2 * y1
        return total / 2.0

    # ------------------------------------------------------------------- 步骤 9
    def _step9_filter_regions(
        self, points: Sequence[Point2D], faces: Sequence[tuple[list[int], float]]
    ) -> tuple[list[tuple[Polygon, float]], Counter]:
        """9. 小面积/细长区域过滤：与 CDT 同口径的四道防线。"""
        kept: list[tuple[Polygon, float]] = []
        rejected: Counter = Counter()
        for ring, signed_area in faces:
            polygon = self._ring_to_polygon(points, ring)
            if polygon is None:
                rejected["degenerate"] += 1
                continue
            reason = self.shape_filter.check(polygon)
            if reason is not None:
                rejected[reason] += 1
                continue
            kept.append((polygon, signed_area))
        return kept, rejected

    @staticmethod
    def _ring_to_polygon(points: Sequence[Point2D], ring: Sequence[int]) -> Polygon | None:
        """节点环 → 合法多边形；自交环用 ``buffer(0)`` 修补后取最大块。"""
        polygon = Polygon([points[node] for node in ring])
        if polygon.is_empty or polygon.area <= 0:
            return None
        if not polygon.is_valid:
            repaired = polygon.buffer(0)
            if repaired.is_empty:
                return None
            if repaired.geom_type == "MultiPolygon":
                repaired = max(repaired.geoms, key=lambda part: part.area)
            if repaired.geom_type != "Polygon" or repaired.area <= 0:
                return None
            polygon = repaired
        return polygon

    # ------------------------------------------------------------------ 步骤 10
    @staticmethod
    def _step10_remove_exterior_faces(
        regions: Sequence[tuple[Polygon, float]]
    ) -> list[tuple[Polygon, float]]:
        """10. 外部面剔除：只保留有向面积为正的（逆时针）有界面。

        外墙轮廓面的环是顺时针的（有向面积为负），悬挂边形成的折返环面积为 0，
        两者都在这里被剔除。
        """
        return [(polygon, signed_area) for polygon, signed_area in regions if signed_area > 0.0]
