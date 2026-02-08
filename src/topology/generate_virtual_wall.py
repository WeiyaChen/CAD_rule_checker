import numpy as np
from scipy.spatial import Delaunay
from shapely import STRtree
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union


class FloorPlanMeshBuilder:
    def __init__(self):
        self.points = []
        self.pos_to_idx = {}
        self.tri = None
        self.edge_index = {}  # 存储阻断边: {(u, v): 'type'}

    def _get_node_id(self, point):
        pt = tuple(np.round(point, 2))
        if pt not in self.pos_to_idx:
            idx = len(self.points)
            self.points.append(pt)
            self.pos_to_idx[pt] = idx
        return self.pos_to_idx[pt]

    # --- 您提供的几何判断函数 (稍作参数调整建议) ---
    def _is_parallel_and_close(self, line_geom, polygons, angle_tol_deg=0, dist_tol=10000.0):
        """
        判断 Delaunay 边是否是门窗的虚拟墙。
        注：dist_tol 建议设为 300左右 (略大于墙厚)，3000 太大了容易误判远处平行墙。
        """
        # 1. 快速距离筛选
        nearby_polys = [p for p in polygons if line_geom.distance(p) < dist_tol]
        if not nearby_polys:
            return False

        l_coords = list(line_geom.coords)
        vec_line = np.array(l_coords[-1]) - np.array(l_coords[0])
        len_line = np.linalg.norm(vec_line)
        if len_line < 1e-3: return False
        unit_line = vec_line / len_line

        cos_threshold = np.cos(np.deg2rad(angle_tol_deg))

        for poly in nearby_polys:
            # 遍历 BBox 的 4 条边
            poly_coords = list(poly.exterior.coords)
            for i in range(len(poly_coords) - 1):
                p_start = np.array(poly_coords[i])
                p_end = np.array(poly_coords[i + 1])

                vec_edge = p_end - p_start
                len_edge = np.linalg.norm(vec_edge)
                if len_edge < 1e-3: continue
                unit_edge = vec_edge / len_edge

                # 计算平行度
                dot_val = np.abs(np.dot(unit_line, unit_edge))
                if dot_val >= cos_threshold:
                    # 找到了平行且靠近的边 -> 视为虚拟墙
                    return True
        return False

    def _mark_virtual_walls_in_mesh(self, door_polys, window_polys):
        """
        遍历 Delaunay 生成的所有边，利用 _is_parallel_and_close 识别虚拟墙
        """
        if self.tri is None: return

        # 获取所有门窗的多边形列表
        all_polys = door_polys + window_polys
        if not all_polys: return

        # 遍历所有三角形的边
        # 使用 set 防止重复检查同一条边
        checked_edges = set()

        for simplex in self.tri.simplices:
            # 三角形的 3 条边: (0,1), (1,2), (2,0)
            for i in range(3):
                u = simplex[i]
                v = simplex[(i + 1) % 3]

                # 排序确保无向性 u < v
                edge_key = tuple(sorted((u, v)))

                # 1. 如果已经在 edge_index 里 (比如是真实墙)，跳过
                if edge_key in self.edge_index:
                    continue

                # 2. 如果已经检查过，跳过
                if edge_key in checked_edges:
                    continue

                checked_edges.add(edge_key)

                # 3. 构建 LineString 几何对象
                p1 = self.points[u]
                p2 = self.points[v]
                line_geom = LineString([p1, p2])

                # 4. 调用您的核心判断函数
                # 这里的参数根据您的实际单位调整，假设单位是 mm
                if self._is_parallel_and_close(line_geom, all_polys, angle_tol_deg=0):
                    # 判定成功！加入阻断索引
                    self.edge_index[edge_key] = 'virtual_blocker'
                    # print(f"检测到门窗虚拟墙: {edge_key}")

    def extract_room(self, center_pt):
        """
        洪水填充 (逻辑不变，只查 edge_index)
        """
        if self.tri is None: return None
        # 1. 获取 numpy 结果
        seed_idx_raw = self.tri.find_simplex(center_pt)

        # 2. 转换为 Python int (这一步解决了 unhashable 问题)
        seed_idx = int(seed_idx_raw)

        if seed_idx == -1:
            print(f"❌ 警告: 种子点 {center_pt} 不在网格内")
            return None

        # B. BFS 队列
        queue = [seed_idx]
        visited = {seed_idx}  # 现在这里是 {int}，不会报错了
        room_polys = []

        while queue:
            curr_idx = queue.pop(0)
            simplex = self.tri.simplices[curr_idx]
            poly_coords = [self.points[i] for i in simplex]
            room_polys.append(Polygon(poly_coords))

            for neighbor_idx in self.tri.neighbors[curr_idx]:
                if neighbor_idx == -1: continue
                if neighbor_idx in visited: continue

                # 检查公共边
                simplex_next = self.tri.simplices[neighbor_idx]
                common = list(set(simplex) & set(simplex_next))

                if len(common) == 2:
                    u, v = sorted((common[0], common[1]))

                    # 【核心】：无论是 'real_wall' 还是刚才识别的 'virtual_blocker'
                    # 只要在表里，就阻断
                    if (u, v) in self.edge_index:
                        continue

                visited.add(neighbor_idx)
                queue.append(neighbor_idx)

        if not room_polys: return None
        return unary_union(room_polys)

        # ... (接在 FloorPlanMeshBuilder 类定义的最后) ...

    def get_visualization_data(self):
        """
        导出用于可视化的数据。
        将内部的 edge_index 还原为 LineString 对象。

        Returns:
            real_wall_lines: List[LineString] - 真实墙体
            virtual_wall_lines: List[LineString] - 识别出的门窗阻断线
            tri: Delaunay Object - 三角剖分对象
            points: List[(x,y)] - 所有顶点坐标
        """
        real_wall_lines = []
        virtual_wall_lines = []

        if not self.points:
            return [], [], None, []

        # 遍历所有被标记的边
        for (u, v), edge_type in self.edge_index.items():
            # 通过 ID 找回坐标
            p1 = self.points[u]
            p2 = self.points[v]
            line = LineString([p1, p2])

            if edge_type == 'real_wall':
                real_wall_lines.append(line)
            elif edge_type == 'virtual_blocker':
                virtual_wall_lines.append(line)

        return real_wall_lines, virtual_wall_lines, self.tri, self.points

    def _add_constraint(self, line_geom):
        """注册线段端点"""
        coords = list(line_geom.coords)
        u = self._get_node_id(coords[0])
        v = self._get_node_id(coords[-1])

    def _find_intersections_and_add_points(self, wall_lines):
        """
        迭代细化核心：检测穿墙边并加点
        """
        if self.tri is None: return False

        wall_tree = STRtree(wall_lines)
        new_points_added = False
        checked_edges = set()

        for simplex in self.tri.simplices:
            for i in range(3):
                u = simplex[i]
                v = simplex[(i + 1) % 3]
                edge_key = tuple(sorted((u, v)))

                if edge_key in checked_edges: continue
                checked_edges.add(edge_key)

                p1 = self.points[u]
                p2 = self.points[v]
                mesh_edge = LineString([p1, p2])

                # 查询可能相交的墙
                possible_idx = wall_tree.query(mesh_edge)
                for idx in possible_idx:
                    wall = wall_lines[idx]

                    # 严谨判断：必须是穿过 (Crosses)
                    if mesh_edge.crosses(wall):
                        intersection = mesh_edge.intersection(wall)
                        if intersection.is_empty: continue

                        pts_to_add = []
                        if intersection.geom_type == 'Point':
                            pts_to_add.append(intersection)
                        elif intersection.geom_type == 'MultiPoint':
                            pts_to_add.extend(intersection.geoms)

                        for pt in pts_to_add:
                            old_len = len(self.points)
                            self._get_node_id((pt.x, pt.y))
                            if len(self.points) > old_len:
                                new_points_added = True
                        break  # 这条边已经打断了，不用查其他墙了

        return new_points_added

    def build(self, walls, doors=[], windows=[], rooms=[]):
        """
        严格匹配您的输入签名
        Args:
            walls: List[LineString] - 包含真实墙线 + 门窗等效线
            doors: List[Polygon] - 门 BBox
            windows: List[Polygon] - 窗 BBox
            rooms: List[Tuple] - 房间标签
        """
        self.points = []
        self.pos_to_idx = {}
        self.edge_index = {}

        # 1. 初始注册 (仅端点)
        for line in walls:
            self._add_constraint(line)

        # 2. 初始 Delaunay
        if len(self.points) < 3: return []
        self.tri = Delaunay(self.points)

        # 3. 迭代细化 (打断穿墙边)
        # 这一步保证了拓扑网格与物理墙体一致
        for _ in range(3):
            if not self._find_intersections_and_add_points(walls):
                break
            self.tri = Delaunay(self.points)  # 重新生成

        # =========================================================
        # 4. 核心：建立边索引 & 语义识别 (Typing)
        # =========================================================
        # 此时网格已稳定，我们需要遍历所有网格边，判断它是墙还是空地
        # 如果是墙，进一步判断是 Real 还是 Virtual

        # 构建墙体索引加速查询
        wall_tree = STRtree(walls)
        all_semantics = doors + windows

        self.edge_index = {}

        # 遍历所有网格边
        checked_edges = set()
        for simplex in self.tri.simplices:
            for i in range(3):
                u = simplex[i]
                v = simplex[(i + 1) % 3]
                edge_key = tuple(sorted((u, v)))

                if edge_key in checked_edges: continue
                checked_edges.add(edge_key)

                p1 = self.points[u]
                p2 = self.points[v]
                edge_geom = LineString([p1, p2])

                # A. 物理判断：这条边是否在 walls 列表里？
                # 判断方法：查看是否被墙体包含或重叠 (buffer 容差处理)
                is_wall_edge = False

                possible_idx = wall_tree.query(edge_geom)
                for idx in possible_idx:
                    input_wall = walls[idx]

                    # --- 修改后的逻辑 ---

                    # 1. 快速距离检查：先看是不是离得很远
                    if input_wall.distance(edge_geom) > 1.0:
                        continue

                    # 2. 包含关系检查 (Coincidence/Containment)
                    # 逻辑：我们将“输入墙线”稍微变粗一点点 (buffer 0.5mm)，变成一个细长的矩形通道。
                    # 如果“网格边”完全落在这个通道里 (covers)，说明它就是这面墙的一部分。
                    # 这种方法对浮点数误差容忍度极高，且比计算 intersection length 更快。

                    if input_wall.covers(edge_geom):
                        is_wall_edge = True
                        break  # 确认是墙了，跳出循环
                if is_wall_edge:
                    self.edge_index[edge_key] = 'real_wall'

                else:
                    # B. 语义判断：是否是虚拟墙？
                    # 调用您的 _is_parallel_and_close
                    if self._is_parallel_and_close(edge_geom, all_semantics):
                        self.edge_index[edge_key] = 'virtual_blocker'

        # 5. 洪水填充提取房间
        results = []
        # 使用 enumerate 生成一个索引 i，作为 ID 的来源
        for i, (label, center) in enumerate(rooms):
            poly = self.extract_room(center)
            if poly:
                results.append({
                    'id': i,  # <--- 【关键修复】必须给每个房间一个唯一 ID
                    'label': label,
                    'geometry': list(poly.exterior.coords)
                    # 'neighbors': ... (后续如果你加了拓扑分析，记得也加上)
                })
                print({
                    'id': i,  # <--- 【关键修复】必须给每个房间一个唯一 ID
                    'label': label,
                    'geometry': list(poly.exterior.coords)
                    # 'neighbors': ... (后续如果你加了拓扑分析，记得也加上)
                })
        return results