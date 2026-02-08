from shapely.geometry import Polygon
from shapely.strtree import STRtree
import numpy as np


class TopologyAnalyzer:
    def __init__(self, rooms_data, doors_polygons):
        """
        Args:
            rooms_data: List[dict] - 房间数据 [{'id':.., 'geometry':..}]
            doors_polygons: List[Polygon] - 门的几何对象

        """
        self.rooms_data = rooms_data
        self.doors_polygons = doors_polygons

        # 1. 准备房间几何对象列表 (用于构建索引)
        self.room_polys = []
        for r in rooms_data:
            geom = r['geometry']
            self.room_polys.append(geom)

        # 2. 构建房间的空间索引 (R-Tree)，加速查询
        self.room_tree = STRtree(self.room_polys)

        # 3. 建立索引映射 (index -> room_data)
        self.room_map = {i: r for i, r in enumerate(rooms_data)}

    def analyze_doors(self):
        """
        建立门与房间的拓扑关系 (KNN 距离排序法)
        解决门体未充满墙洞或主要在某一侧房间内的问题
        """
        analyzed_doors = []

        # 定义距离容差 (单位: 米)
        # 墙体厚度通常在 0.2m~0.3m 之间。
        # 设置为 0.4m 意味着：只要房间离门在 40cm 以内，都算作潜在连接对象。
        MAX_WALL_THICKNESS_TOLERANCE = 0.4

        for i, door_geom in enumerate(self.doors_polygons):
            # -------------------------------------------------------
            # 1. 几何属性计算
            # -------------------------------------------------------
            min_x, min_y, max_x, max_y = door_geom.bounds
            width_mm = max(max_x - min_x, max_y - min_y)

            # -------------------------------------------------------
            # 2. 拓扑绑定 (核心修改部分)
            # -------------------------------------------------------
            connected_room_ids = []
            connected_room_labels = []  # 方便调试

            # A. 扩大搜索范围 (Broad Search)
            # 创建一个向外膨胀 0.5m 的搜索区。
            # 这保证了即使门在房间A内部，也能“摸”到隔壁墙后的房间B。
            search_area = door_geom.buffer(0.5)
            possible_indexes = self.room_tree.query(search_area)

            # B. 计算精确距离 (Distance Calculation)
            candidates = []
            for idx in possible_indexes:
                room_poly = self.room_polys[idx]

                # 计算门与该房间的欧几里得距离
                # 如果门有一部分在房间内，distance = 0
                dist = door_geom.distance(room_poly)
                candidates.append((dist, idx))

            # C. 排序与筛选 (Sort & Filter)
            # 按距离从小到大排序：[0.0(所在房间), 0.15(隔壁房间), 1.2(远处的房间)...]
            candidates.sort(key=lambda x: x[0])

            # 取前两名 (Top 2)
            # 因为一扇门物理上最多连接 2 个空间
            final_matches = []

            # 第 1 名：必然是连接的 (通常距离为 0 或极小)
            if len(candidates) >= 1:
                final_matches.append(candidates[0])

            # 第 2 名：检查是否在容差范围内
            if len(candidates) >= 2:
                dist_2, idx_2 = candidates[1]
                if dist_2 < MAX_WALL_THICKNESS_TOLERANCE:
                    final_matches.append((dist_2, idx_2))

            # D. 提取结果数据
            for dist, idx in final_matches:
                r_data = self.room_map[idx]
                connected_room_ids.append(r_data['id'])
                connected_room_labels.append(r_data.get('label', 'Unknown'))

            # -------------------------------------------------------
            # 3. 类型推断 (入户门 vs 内门)
            # -------------------------------------------------------
            is_entrance = False

            # 逻辑 A: 单连接 + 宽度达标
            # 如果只连接了 1 个房间，且不是通往阳台(通常阳台也会被识别为Room)，且够宽
            if len(connected_room_ids) == 1:
                # 排除通往阳台的情况 (简单通过标签判断，如果没有标签可忽略)
                neighbor_label = connected_room_labels[0].lower() if connected_room_labels else ""

                # 如果连接的是 LivingRoom 且门很宽，大概率是入户门
                # 假设一般入户门 >= 850mm
                if width_mm >= 850 and "balcony" not in neighbor_label:
                    is_entrance = True

            # 逻辑 B: 标签辅助 (如果上游 OCR 给了 'Entrance' 标签)
            # if hasattr(door_geom, 'label') and '入户' in door_geom.label: is_entrance = True

            # -------------------------------------------------------
            # 4. 组装数据
            # -------------------------------------------------------
            analyzed_doors.append({
                'id': f"door_{i}",
                'width': float(width_mm),
                'is_entrance': is_entrance,
                'connects_rooms': connected_room_ids,
                'debug_labels': connected_room_labels  # 这一项仅用于打印调试，RDF生成时不用
            })

        return analyzed_doors
