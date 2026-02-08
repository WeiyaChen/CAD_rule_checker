import json
import math

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

        # 定义 JSON-LD 的头部 Context
        self.context = {
            "bot": "https://w3id.org/bot#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
            "inst": "http://mythesis.org/instance/",
            "props": "http://mythesis.org/props/",
            "beo": "https://pi.pauwel.be/voc/buildingelement#",
            "geo": "http://www.opengis.net/ont/geosparql#"
        }
        self.graph = []

    def _get_wkt(self, geom):
        """辅助函数，将Shapely对象转化为WKT字符串"""
        return geom.wkt

    def _cast_rays_for_door(self, door_comp, probe_len=300):
        """通过射线法探测门连接的房间对象"""
        door_geom = door_comp.geometry
        centroid = Polygon(door_geom).centroid
        cx, cy = centroid.x, centroid.y  # 中心点坐标

        search_zone = Polygon(door_geom)

        target_vector = None

        # 遍历所有房间，寻找参考墙线
        for r_id, r_poly in self.room_polys.items():
            r_boundary = r_poly.boundary

            if search_zone.intersects(r_boundary):
                ref_line = search_zone.intersection(r_boundary)
                if ref_line:
                    cords = list(ref_line.coords)
                    p1 = cords[0]
                    p2 = cords[-1]

                    dx = p2[0] - p1[0]
                    dy = p2[1] - p1[1]

                    mid_x = (p1[0] + p2[0]) / 2
                    mid_y = (p1[1] + p2[1]) / 2

                    # 更新发射源坐标
                    cx, cy = mid_x, mid_y

                    length = math.sqrt(dx ** 2 + dy ** 2)
                    if length > 0:
                        nx, ny = -dy / length, dx / length
                        target_vector = (nx, ny)
                        break

        # 射线生成
        rays = []
        if target_vector:
            nx, ny = target_vector
            rays = [
                LineString([(cx, cy), (cx + nx * probe_len, cy + ny * probe_len)]),
                LineString([(cx, cy), (cx - nx * probe_len, cy - ny * probe_len)])
            ]
        hit_rooms = set()
        for ray in rays:
            for r_id, r_poly in self.room_polys.items():
                if ray.intersects(r_poly):
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
                if len(connected_set) >= 2:
                    associated_rooms = list(connected_set)
                    r_a, r_b = associated_rooms[0], associated_rooms[1]

                    # 记录门是接口
                    topology["interfaces"][comp.uid] = [r_a, r_b]

                    # 推导房间相邻
                    topology["adjacency"][r_a].add(r_b)
                    topology["adjacency"][r_b].add(r_a)

                    # 记录门属于这两个房间
                    topology["containment"][r_a].append(comp.uid)
                    topology["containment"][r_b].append(comp.uid)

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

        return topology

    def generate(self):
        topo_data = self._calculate_topology()

        # 生成房间节点
        for r in self.rooms:
            r_id = r["id"]
            node_id = f"inst:{r['label']}_{r_id}"

            node = {
                "@id": node_id,
                "@type": ["bot:Space", f"props:{r['label']}"],
                "rdfs:label": f"{r['label']} Instance",
                "props:geometryWKT": self._get_wkt(self.room_polys[r_id]),
                "props:hasArea": round(self.room_polys[r_id].area / 1000000, 2),

                # 填充拓扑关系
                "bot:containsElement": [
                    {"@id": f"inst:{comp_uid}"}
                    for comp_uid in topo_data["containment"][r_id]
                ],
                "bot:adjacentZone": [
                    {"@id": f"inst:{self.rooms[n_id]['label']}_{n_id}"}
                    for n_id in topo_data["adjacency"][r_id]
                ]
            }
            print(node)
            self.graph.append(node)

            # 生成构件节点
            for comp in self.components:
                node_id = f"inst:{comp.uid}"

                node = {
                    "@id": node_id,
                    "@type": ["bot:Element", f"beo:{comp.category}"],
                    "props:width": comp.properties.get("width"),
                    "props:length": comp.properties.get("length"),
                    "props:geometryWKT": self._get_wkt(Polygon(comp.geometry))
                }

                # 如果是门
                if comp.uid in topo_data["interfaces"]:
                    connected_rooms = topo_data["interfaces"][comp.uid]
                    node["bot:interfaceOf"] = [
                        {"@id": f"inst:{self.rooms[rid]['label']}_{rid}"}
                        for rid in connected_rooms
                    ]
                self.graph.append(node)

        # 最终组装
        final_json_ld = {
            "@context": self.context,
            "@graph": self.graph
        }
        return final_json_ld
