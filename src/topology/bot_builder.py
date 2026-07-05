import json
import math

import numpy as np
from shapely import LineString
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union


class BotGraphGenerator:
    def __init__(self, rooms_data, components_data):
        self.rooms = rooms_data
        self.components = components_data

        # 预处理，将房间坐标列表转为Shapely Polygon 对象，方便几何计算
        self.room_polys = {}
        for r in self.rooms:
            self.room_polys[r["id"]] = Polygon(r["geometry"])

        # 构件房间id和房间类型标签的字典
        self.room_label_map = {r["id"]: r['label'] for r in self.rooms}


        # 定义 JSON-LD 的头部 Context
        self.context = {
            "bot": "https://w3id.org/bot#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "inst": "http://mythesis.org/instance/",
            "props": "http://mythesis.org/props/",
            "bldg": "http://mythesis.org/bldg/",
            "beo": "https://pi.pauwel.be/voc/buildingelement#",
            "geo": "http://www.opengis.net/ont/geosparql#",
            "xsd": "http://www.w3.org/2001/XMLSchema#"
        }
        self.graph = []

    def _get_wkt(self, geom):
        """辅助函数，将Shapely对象转化为WKT字符串"""
        return geom.wkt

    def _cast_rays_for_door(self, door_comp, probe_len=300, buffer_dist=0.1):
        """通过交线中点与法向射线探测门连接的房间对象"""
        # 构造门的几何多边形
        door_poly = Polygon(door_comp.geometry)
        buffered_door = door_poly.buffer(buffer_dist)

        best_line = None
        max_len = 0

        # A. 寻找门图元与任意房间边界的最长交线 (作为门槛基准线)
        for r_id, r_poly in self.room_polys.items():
            intersection = buffered_door.intersection(r_poly.boundary)
            lines = []

            if intersection.geom_type == 'LineString':
                lines.append(intersection)
            elif intersection.geom_type == 'MultiLineString':
                lines.extend(list(intersection.geoms))
            elif intersection.geom_type == 'GeometryCollection':
                lines.extend([g for g in intersection.geoms if g.geom_type == 'LineString'])

            for line in lines:
                if line.length > max_len:
                    max_len = line.length
                    best_line = line

        hit_rooms = set()

        # B. 提取交线中点作法向射线探测
        if best_line and max_len > 1e-3:
            coords = list(best_line.coords)
            p1, p2 = np.array(coords[0]), np.array(coords[-1])
            midpoint = (p1 + p2) / 2.0

            vec = p2 - p1
            vec_len = np.linalg.norm(vec)
            if vec_len > 1e-5:
                unit_vec = vec / vec_len
                # 逆时针旋转90度生成法向量
                normal_vec = np.array([-unit_vec[1], unit_vec[0]])

                # 沿法向量双向延伸构建探测射线
                ray_line = LineString([midpoint - normal_vec * probe_len, midpoint + normal_vec * probe_len])

                # 检测射线穿越了哪些房间区域
                for r_id, r_poly in self.room_polys.items():
                    if r_poly.intersects(ray_line):
                        hit_rooms.add(r_id)

        # C. 异常兜底策略：若未成功提取有效交线，回退至距离容差判断
        if not hit_rooms:
            fallback_tol = 300  # 根据您的实际坐标比例可适当调整该值
            for r_id, r_poly in self.room_polys.items():
                if door_poly.distance(r_poly) < fallback_tol:
                    hit_rooms.add(r_id)

        return hit_rooms

    def _calculate_topology(self):
        """核心函数，计算房间之间，房间和家具的拓扑关系"""
        topology = {
            "containment": {r["id"]: [] for r in self.rooms},  # 房间包含哪些构件
            "adjacency": {r["id"]: set() for r in self.rooms},  # 房间邻接哪些房间
            "interfaces": {}  # 门连接了哪些房间 {door_uid:[room_id_1, room_id_2]}
        }

        # 预计算缓冲区(用于窗户判定)
        buffered_rooms = {
            r_id: poly.buffer(300) for r_id, poly in self.room_polys.items()
        }

        # 1 计算包含关系
        # 遍历所有构件，看它在哪个房间里
        for comp in self.components:
            p_center = Polygon(comp.geometry).centroid

            # 门的处理逻辑
            if comp.category == "Door":
                connected_set = self._cast_rays_for_door(comp)
                # 情况一：射线捕获了两个或以上的空间实体
                if len(connected_set) >= 2:
                    associated_rooms = list(connected_set)
                    r_a, r_b = associated_rooms[0], associated_rooms[1]

                    # 记录门是接口及双向相邻推导
                    topology["interfaces"][comp.uid] = [r_a, r_b]
                    topology["adjacency"][r_a].add(r_b)
                    topology["adjacency"][r_b].add(r_a)
                    topology["containment"][r_a].append(comp.uid)
                    topology["containment"][r_b].append(comp.uid)

                # 情况二：射线仅捕获到一个内部空间，另一侧为未建模的图纸边界
                elif len(connected_set) == 1:
                    r_a = list(connected_set)[0]

                    # 纯记录单边连通关系
                    topology["interfaces"][comp.uid] = [r_a, "UnmodeledExterior"]
                    topology["containment"][r_a].append(comp.uid)

            # 窗户的处理逻辑
            elif comp.category == "Window":
                for r_id, r_buf in buffered_rooms.items():
                    # 窗户中心在膨胀后的房间内
                    if r_buf.contains(p_center):
                        topology["containment"][r_id].append(comp.uid)

            # 家具的处理逻辑
            else:
                for r_id, r_poly in self.room_polys.items():
                    if r_poly.contains(p_center):
                        topology["containment"][r_id].append(comp.uid)

        # 2 计算隐式连接，如玄关和客厅
        room_ids = list(self.room_polys.keys())

        for i in range(len(room_ids)):
            for j in range(i + 1, len(room_ids)):
                id_a, id_b = room_ids[i], room_ids[j]

                # 已经通过门连接了
                if id_b in topology["adjacency"][id_a]:
                    continue

                poly_a = self.room_polys[id_a]
                poly_b = self.room_polys[id_b]

                if not poly_a.intersects(poly_b):
                    continue

                topology["adjacency"][id_a].add(id_b)
                topology["adjacency"][id_b].add(id_a)
        return topology

    def generate(self):
        topo_data = self._calculate_topology()

        # 创建一个 Apartment 根节点
        apartment_node = {
            "@id": "inst:Apartment_01",
            "@type": "bot:Zone",
            "bot:containsZone": [{"@id": f"inst:{r['id']}"} for r in self.rooms]
        }
        self.graph.append(apartment_node)

        # 生成房间节点
        for r in self.rooms:
            r_id = r["id"]
            node_id = f"inst:{r_id}" # 直接使用纯ID，如inst:Space_001

            node = {
                "@id": node_id,
                "@type": ["bot:Space"],
                "geo:asWKT": {
                    "@value": self._get_wkt(self.room_polys[r_id]),
                    "@type": "geo:wktLiteral"
                },
                "props:hasArea": round(self.room_polys[r_id].area / 1000000, 2),

                # 填充拓扑关系
                "bot:containsElement": [
                    {"@id": f"inst:{comp_uid}"}
                    for comp_uid in topo_data["containment"][r_id]
                ],
                "bot:adjacentZone": [
                    {"@id": f"inst:{n_id}"}
                    for n_id in topo_data["adjacency"][r_id]
                ]
            }
            self.graph.append(node)

        # 生成构件节点
        for comp in self.components:
            node_id = f"inst:{comp.uid}"

            node = {
                "@id": node_id,
                "@type": ["bot:Element", f"beo:{comp.category}"],
                "rdfs:label":comp.specific_type,
                "props:width": comp.properties.get("width"),
                "props:length": comp.properties.get("length"),
                "geo:asWKT": {
                    "@value": self._get_wkt(Polygon(comp.geometry)),
                    "@type": "geo:wktLiteral"
                }
            }

            # 如果是门
            if comp.uid in topo_data["interfaces"]:
                connected_rooms = topo_data["interfaces"][comp.uid]
                node["bot:interfaceOf"] = [
                    {"@id": f"inst:{rid}"} for rid in connected_rooms
                ]
            self.graph.append(node)

        # 最终组装
        final_json_ld = {
            "@context": self.context,
            "@graph": self.graph
        }

        return final_json_ld


