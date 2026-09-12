# src/spatial/contours/cdt.py
"""基于约束德劳内三角剖分（CDT）的空间轮廓提取算法。

算法思路（由 :meth:`CDTContourExtractor.extract` 实现）：

1. 把墙体线段构造成 PSLG，调用 :mod:`triangle` 执行一次精确 CDT；
2. 标记真实墙体边、凸包边，并对门窗洞口补充"虚拟封口边"；
3. 在三角网邻接图上做盲泛滥生长（BFS），遇到阻挡边即停止；
4. 对生长出的多边形依次施加面积、净宽、形状（紧凑度/实心率）四道防线。
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import triangle as tr
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from .filters import SpaceShapeFilter
from ..contracts import ISpatialContourExtractor
from ..domain import SpatialComponent, SpatialContour
from ..registry import CONTOUR_EXTRACTORS


@CONTOUR_EXTRACTORS.register("CDT", aliases=("CDT_MESH", "TRIANGLE_CDT"))
class CDTContourExtractor(ISpatialContourExtractor):
    """使用 ``triangle`` 库的约束三角剖分 + 区域泛滥生长提取房间轮廓。"""

    name = "CDT"
    visualization_suffix = "cdt"

    def __init__(
        self,
        *,
        min_area_mm2: float = 2000000.0,
        erode_mm: float = 250.0,
        min_width_mm: float = 600.0,
        min_compactness: float = 0.08,
        min_solidity: float = 0.25,
        virtual_blocker_dist_tol_mm: float = 300.0,
        virtual_blocker_max_len_mm: float = 3500.0,
        virtual_blocker_angle_tol_deg: float = 0.0,
    ):
        self.min_area_mm2 = float(min_area_mm2)
        self.erode_mm = float(erode_mm)
        self.min_width_mm = float(min_width_mm)
        self.min_compactness = float(min_compactness)
        self.min_solidity = float(min_solidity)
        self.virtual_blocker_dist_tol_mm = float(virtual_blocker_dist_tol_mm)
        self.virtual_blocker_max_len_mm = float(virtual_blocker_max_len_mm)
        self.virtual_blocker_angle_tol_deg = float(virtual_blocker_angle_tol_deg)

        self.shape_filter = SpaceShapeFilter(
            min_area_mm2=self.min_area_mm2,
            erode_mm=self.erode_mm,
            min_width_mm=self.min_width_mm,
            min_compactness=self.min_compactness,
            min_solidity=self.min_solidity,
        )

        # 最近一次 extract() 产生的网格状态，供可视化读取
        self.points: Any = []
        self.triangles: Any = []
        self.neighbors: Any = []
        self.edge_index: dict[tuple[int, int], str] = {}

    # ------------------------------------------------------------------ helpers
    def _is_parallel_and_close(self, line_geom, polygons, wall_lines):
        """
        判断 CDT 生成的三角边是否为门窗的虚拟物理阻挡边。
        【修复横跨空间问题】：增加最大长度限制与双端点距离严格约束。
        """
        l_coords = list(line_geom.coords)
        p_line_start = np.array(l_coords[0])
        p_line_end = np.array(l_coords[-1])

        vec_line = p_line_end - p_line_start
        len_line = np.linalg.norm(vec_line)

        # 1. 长度防线：过长的线不可能是门窗虚拟封口墙，直接拦截横跨空间的线
        if len_line < 1e-3 or len_line > self.virtual_blocker_max_len_mm:
            return False

        unit_line = vec_line / len_line
        cos_threshold = np.cos(np.deg2rad(self.virtual_blocker_angle_tol_deg))

        pt_start = Point(p_line_start)
        pt_end = Point(p_line_end)

        for poly in polygons:
            # 2. 双端点逼近防线：仅仅 line_geom 整体靠近门窗不够
            # 必须保证线段的【两个端点】都非常靠近门窗多边形
            # 这能彻底杜绝“一头在门边，一头在房间对面”的跨房间连线
            if (
                pt_start.distance(poly) > self.virtual_blocker_dist_tol_mm
                or pt_end.distance(poly) > self.virtual_blocker_dist_tol_mm
            ):
                continue

            # 3. 平行度防线：判断是否与门窗的某条边缘平行
            poly_coords = list(poly.exterior.coords)
            is_parallel_to_door = False
            for i in range(len(poly_coords) - 1):
                p_start = np.array(poly_coords[i])
                p_end = np.array(poly_coords[i + 1])
                vec_edge = p_end - p_start
                len_edge = np.linalg.norm(vec_edge)
                if len_edge < 1e-3:
                    continue
                unit_edge = vec_edge / len_edge

                if np.abs(np.dot(unit_line, unit_edge)) >= cos_threshold:
                    is_parallel_to_door = True
                    break

            if is_parallel_to_door:
                return True

        return False

    # -------------------------------------------------------------------- public
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
        """基于专业 CDT 库 (triangle) 的全局盲泛滥生长网格构建。

        ``texts`` / ``components`` / ``context`` 在本算法中不参与计算，
        保留参数是为了与其他轮廓算法保持统一调用约定。
        """
        self.points = []
        self.edge_index = {}

        # ==========================================
        # 1. 构建 PSLG (平面直线图) 数据结构
        # ==========================================
        vertices_list = []
        vertex_map = {}
        segments_list = []

        def get_or_add_vertex(pt):
            # 保留两位小数以消除微观浮点误差，确保节点重合
            key = (round(pt[0], 2), round(pt[1], 2))
            if key not in vertex_map:
                vertex_map[key] = len(vertices_list)
                vertices_list.append([key[0], key[1]])
            return vertex_map[key]

        # 遍历所有墙体，提取顶点并严格定义约束边 (Segments)
        for wall in walls:
            coords = list(wall.coords)
            for i in range(len(coords) - 1):
                idx1 = get_or_add_vertex(coords[i])
                idx2 = get_or_add_vertex(coords[i + 1])
                if idx1 != idx2:
                    segments_list.append([idx1, idx2])

        if len(vertices_list) < 3:
            return []

        # ==========================================
        # 2. 调用 triangle 库执行单次精确 CDT
        # ==========================================
        cdt_input = {
            'vertices': np.array(vertices_list, dtype=np.float64),
            'segments': np.array(segments_list, dtype=np.int32)
        }

        # 'p' = 启用 PSLG 约束 (强制保留 segments 作为网格边)
        # 'n' = 输出三角形的邻接关系 (用于后续的 BFS 泛滥生长)
        # 'c' = 保持凸包封闭
        cdt_output = tr.triangulate(cdt_input, 'pnc ')

        self.points = cdt_output['vertices']
        self.triangles = cdt_output['triangles']
        self.neighbors = cdt_output['neighbors']
        out_segments = cdt_output.get('segments', np.array(segments_list))

        # ==========================================
        # 3. 建立边索引 & 物理/虚拟阻挡判定
        # ==========================================
        # 将用户最初定义的约束边转换为哈希集合，便于快速比对
        user_edges = set(tuple(sorted(seg)) for seg in segments_list)

        # 区分真实墙体 与 算法生成的凸包边
        for seg in out_segments:
            u, v = int(seg[0]), int(seg[1])
            edge_key = tuple(sorted((u, v)))

            if edge_key in user_edges:
                self.edge_index[edge_key] = 'real_wall'  # 用户输入的物理约束
            else:
                self.edge_index[edge_key] = 'convex_hull'  # 算法生成的外部包络线

        all_semantics = list(doors) + list(windows)
        checked_edges = set(self.edge_index.keys())

        # 遍历生成的三角形，检测是否需要补充“虚拟阻挡边”
        for simplex in self.triangles:
            for i in range(3):
                u = simplex[i]
                v = simplex[(i + 1) % 3]
                edge_key = tuple(sorted((u, v)))

                if edge_key in checked_edges:
                    continue
                checked_edges.add(edge_key)

                p1 = self.points[u]
                p2 = self.points[v]
                edge_geom = LineString([p1, p2])

                if self._is_parallel_and_close(edge_geom, all_semantics, walls):
                    self.edge_index[edge_key] = 'virtual_blocker'

        # ==========================================
        # 4. 基于 CDT 邻接图的全局盲泛滥生长
        # ==========================================
        results: list[SpatialContour] = []
        visited_triangles = set()
        room_counter = 1

        for starting_tri_idx in range(len(self.triangles)):
            if starting_tri_idx in visited_triangles:
                continue

            component_tri_indices = []
            queue = [starting_tri_idx]
            is_exterior = False

            while queue:
                curr_idx = queue.pop(0)
                if curr_idx in visited_triangles:
                    continue

                visited_triangles.add(curr_idx)
                component_tri_indices.append(curr_idx)

                for k in range(3):
                    neighbor_idx = self.neighbors[curr_idx][k]

                    # 提取当前正在评估的共享边 (不包含第 k 个顶点)
                    u = self.triangles[curr_idx][(k + 1) % 3]
                    v = self.triangles[curr_idx][(k + 2) % 3]
                    edge_key = tuple(sorted((u, v)))

                    # 获取该边的类型
                    edge_type = self.edge_index.get(edge_key)

                    # [核心修复] 先判断边属性，利用物理/算法边界“挡住”泄漏
                    if edge_type == 'real_wall':
                        continue  # 遇到真实墙体 (如1号多边形)，正常阻断，不视为泄漏

                    if edge_type == 'virtual_blocker':
                        continue  # 虚拟门边界阻挡，正常阻断

                    # 如果这条边没有任何属性，且是生成的凸包边或者是虚空 (-1)，说明网格在此处真正发生了未闭合泄漏
                    if edge_type == 'convex_hull' or neighbor_idx == -1:
                        is_exterior = True
                        continue

                    # 正常生长
                    if neighbor_idx not in visited_triangles:
                        queue.append(neighbor_idx)

            if is_exterior:
                continue

            tri_polygons = []
            for tri_idx in component_tri_indices:
                pts = [self.points[idx] for idx in self.triangles[tri_idx]]
                tri_polygons.append(Polygon(pts))

            if not tri_polygons:
                continue

            room_poly = unary_union(tri_polygons)

            if room_poly.geom_type == 'MultiPolygon':
                room_poly = max(room_poly.geoms, key=lambda a: a.area)

            # 四道防线（面积 / 净宽 / 外接矩形短边 / 紧凑度+实心率），与 RGP 共用同一套口径
            if self.shape_filter.check(room_poly) is not None:
                continue

            results.append(
                SpatialContour(
                    id=f"Space_{room_counter:03d}",
                    label="Unknown",
                    geometry=list(room_poly.exterior.coords),
                )
            )
            room_counter += 1

        return results

    def get_visualization_data(self):
        """导出用于可视化的数据。

        返回 ``(real_wall_lines, virtual_wall_lines, triangles, points)``，
        其中第 3/4 项分别是 ``triangle`` 库输出的三角形顶点索引数组与顶点坐标数组。
        """
        real_wall_lines = []
        virtual_wall_lines = []

        if len(self.points) == 0:
            return [], [], None, []

        for (u, v), edge_type in self.edge_index.items():
            p1 = self.points[u]
            p2 = self.points[v]
            line = LineString([p1, p2])

            if edge_type == 'real_wall':
                real_wall_lines.append(line)
            elif edge_type == 'virtual_blocker':
                virtual_wall_lines.append(line)

        return real_wall_lines, virtual_wall_lines, self.triangles, self.points
