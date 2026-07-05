import json
import uuid
import math
import numpy as np
from shapely.wkt import loads as wkt_loads
from shapely.geometry import Polygon, Point, MultiLineString, LineString
from shapely.ops import unary_union, split
from shapely.affinity import scale


class ACDProcessor:
    def __init__(self, graph_dict):
        """
        初始化近似凸分解处理器
        :param graph_dict: 已经过大模型语义富化的 JSON-LD 知识图谱字典
        """
        self.graph = graph_dict
        self.nodes = {node.get("@id"): node for node in self.graph.get("@graph", [])}

    def _is_composite_space(self, node):
        """判断节点是否为需要切分的复合空间"""
        types = node.get("@type", [])
        if isinstance(types, str): types = [types]

        if "bot:Space" not in types:
            return False

        # 统计以 "bldg:" 开头的建筑语义标签数量
        bldg_tags = [t for t in types if t.startswith("bldg:") and t != "bldg:Suite"]
        return len(bldg_tags) >= 2

    def _get_concave_points(self, poly):
        """提取多边形中的所有几何凹点及其对应边缘的延长线方向向量"""
        coords = list(poly.exterior.coords)
        if coords[0] == coords[-1]:
            coords = coords[:-1]

        concave_info = []
        n = len(coords)
        is_ccw = poly.exterior.is_ccw

        for i in range(n):
            p_prev = coords[i - 1]
            p_curr = coords[i]
            p_next = coords[(i + 1) % n]

            v1 = (p_curr[0] - p_prev[0], p_curr[1] - p_prev[1])
            v2 = (p_next[0] - p_curr[0], p_next[1] - p_curr[1])

            cross_product = v1[0] * v2[1] - v1[1] * v2[0]

            if (is_ccw and cross_product < -1e-4) or (not is_ccw and cross_product > 1e-4):
                len_v1 = math.hypot(v1[0], v1[1])
                dir1 = (v1[0] / len_v1, v1[1] / len_v1) if len_v1 > 1e-6 else (0, 0)

                v3 = (p_curr[0] - p_next[0], p_curr[1] - p_next[1])
                len_v3 = math.hypot(v3[0], v3[1])
                dir2 = (v3[0] / len_v3, v3[1] / len_v3) if len_v3 > 1e-6 else (0, 0)

                concave_info.append((Point(p_curr), [dir1, dir2]))

        return concave_info

    def _execute_acd_math(self, room_poly, constraint_geoms):
        """执行底层的近似凸分解数学运算 (常规边缘延长线投射迭代)"""
        if room_poly.geom_type != 'Polygon' or room_poly.is_empty:
            return [room_poly] if not room_poly.is_empty else []

        concave_info = self._get_concave_points(room_poly)
        if not concave_info:
            return [room_poly]

        minx, miny, maxx, maxy = room_poly.bounds
        max_dist = math.hypot(maxx - minx, maxy - miny)

        best_split_line = None
        min_split_length = float('inf')

        for pt, directions in concave_info:
            for dx, dy in directions:
                if dx == 0 and dy == 0:
                    continue

                ray_end = Point(pt.x + dx * max_dist, pt.y + dy * max_dist)
                ray = LineString([pt, ray_end])
                boundary_intersection = ray.intersection(room_poly.boundary)

                closest_dist = float('inf')
                closest_pt = None

                if boundary_intersection.geom_type == 'Point':
                    if pt.distance(boundary_intersection) > 1e-4:
                        closest_dist = pt.distance(boundary_intersection)
                        closest_pt = boundary_intersection
                elif boundary_intersection.geom_type == 'MultiPoint':
                    for ip in boundary_intersection.geoms:
                        d = pt.distance(ip)
                        if 1e-4 < d < closest_dist:
                            closest_dist = d
                            closest_pt = ip
                elif boundary_intersection.geom_type in ['LineString', 'MultiLineString', 'GeometryCollection']:
                    pts = []
                    if hasattr(boundary_intersection, 'geoms'):
                        for geom in boundary_intersection.geoms:
                            if geom.geom_type == 'Point':
                                pts.append(geom)
                            elif geom.geom_type == 'LineString':
                                pts.extend([Point(c) for c in geom.coords])
                    else:
                        pts.extend([Point(c) for c in boundary_intersection.coords])

                    for ip in pts:
                        d = pt.distance(ip)
                        if 1e-4 < d < closest_dist:
                            closest_dist = d
                            closest_pt = ip

                if closest_pt is None:
                    continue

                candidate_line = LineString([pt, closest_pt])
                if not room_poly.contains(candidate_line.centroid):
                    continue

                if candidate_line.length < min_split_length:
                    min_split_length = candidate_line.length
                    best_split_line = candidate_line

        if best_split_line is None:
            return [room_poly]

        extended_line = scale(best_split_line, xfact=1.001, yfact=1.001)

        try:
            split_result = split(room_poly, extended_line)
            sub_polys = [geom for geom in split_result.geoms if geom.geom_type == 'Polygon' and geom.area > 1e-2]
        except Exception:
            return [room_poly]

        if len(sub_polys) == 1:
            return sub_polys

        final_polys = []
        for sub_poly in sub_polys:
            final_polys.extend(self._execute_acd_math(sub_poly, constraint_geoms))

        return final_polys

    def _is_adjacent(self, poly1, poly2, tolerance=1.0, min_overlap=1.0):
        if poly1.distance(poly2) > tolerance:
            return False

        overlap = poly1.intersection(poly2.buffer(tolerance)).intersection(poly1.boundary)

        overlap_len = 0.0
        if overlap.geom_type == 'LineString':
            overlap_len = overlap.length
        elif overlap.geom_type == 'MultiLineString':
            overlap_len = sum(line.length for line in overlap.geoms)
        elif overlap.geom_type == 'GeometryCollection':
            for geom in overlap.geoms:
                if geom.geom_type == 'LineString':
                    overlap_len += geom.length
                elif geom.geom_type == 'MultiLineString':
                    overlap_len += sum(line.length for line in geom.geoms)

        return overlap_len > min_overlap

    def process(self):
        composite_nodes = [n for n in self.graph.get("@graph", []) if self._is_composite_space(n)]
        if not composite_nodes:
            return self.graph

        nodes_to_remove = []
        nodes_to_add = []
        active_spaces = {}

        for node in self.graph.get("@graph", []):
            types = node.get("@type", [])
            if isinstance(types, str): types = [types]
            if "bot:Space" in types:
                wkt_val = node.get("geo:asWKT")
                if wkt_val:
                    wkt_str = wkt_val.get("@value", wkt_val) if isinstance(wkt_val, dict) else wkt_val
                    try:
                        active_spaces[node.get("@id")] = {"node": node, "poly": wkt_loads(wkt_str)}
                    except Exception:
                        pass

        for node in composite_nodes:
            old_id = node.get("@id")

            if old_id in active_spaces:
                del active_spaces[old_id]

            for s_id, s_info in active_spaces.items():
                adj_list = s_info["node"].get("bot:adjacentZone", [])
                if not isinstance(adj_list, list): adj_list = [adj_list]
                new_adj_list = [adj for adj in adj_list if (adj.get("@id") if isinstance(adj, dict) else adj) != old_id]
                s_info["node"]["bot:adjacentZone"] = new_adj_list

            old_wkt = node.get("geo:asWKT", "")
            if isinstance(old_wkt, dict): old_wkt = old_wkt.get("@value", "")
            try:
                room_poly = wkt_loads(old_wkt)
            except Exception:
                continue

            constraint_geoms = []
            contained_elems = node.get("bot:containsElement", [])
            if not isinstance(contained_elems, list): contained_elems = [contained_elems]
            elem_nodes = [self.nodes[ref.get("@id")] for ref in contained_elems if ref.get("@id") in self.nodes]

            for e in elem_nodes:
                e_wkt = e.get("geo:asWKT", "")
                if isinstance(e_wkt, dict): e_wkt = e_wkt.get("@value", "")
                try:
                    constraint_geoms.append(wkt_loads(e_wkt))
                except Exception:
                    pass

            text_anchors = node.get("props:textAnchors", [])
            for anchor in text_anchors:
                try:
                    pt = Point(anchor["coordinates"])
                    constraint_geoms.append(pt.buffer(100))
                except Exception:
                    pass

            # ==============================================================
            # 【逻辑调整】：如果已经是凸多边形了，优先执行包围盒中心投影切分
            # ==============================================================
            sub_polygons = []
            is_dual_label_concave = len(text_anchors) == 2 and len(self._get_concave_points(room_poly)) == 0

            if is_dual_label_concave:
                try:
                    c1 = Point(text_anchors[0]["coordinates"])
                    c2 = Point(text_anchors[1]["coordinates"])

                    # 1. 提取当前空间包围盒的四个边界
                    minx, miny, maxx, maxy = room_poly.bounds

                    # 2. 将包围盒的中心分别投影到四个边界，并计算同一个边界的投影点间隔距离
                    # Top/Bottom 边界投影点形成的间隔线段
                    seg_top = LineString([(c1.x, maxy), (c2.x, maxy)])
                    seg_bottom = LineString([(c1.x, miny), (c2.x, miny)])
                    dist_x = seg_top.length

                    # Left/Right 边界投影点形成的间隔线段
                    seg_left = LineString([(minx, c1.y), (minx, c2.y)])
                    seg_right = LineString([(maxx, c1.y), (maxx, c2.y)])
                    dist_y = seg_left.length

                    # 3. 将投影点距离最长的前两个投影间隔线段提取，连接两个线段的中点
                    if dist_x > dist_y:
                        # 沿 X 轴分布更宽，提取 Top 和 Bottom 边界投影线段的中点
                        cut_line = LineString([seg_top.centroid, seg_bottom.centroid])
                    else:
                        # 沿 Y 轴分布更宽，提取 Left 和 Right 边界投影线段的中点
                        cut_line = LineString([seg_left.centroid, seg_right.centroid])

                    # 延伸线段以保证贯穿整个多边形
                    extended_cut_line = scale(cut_line, xfact=1.2, yfact=1.2)

                    split_result = split(room_poly, extended_cut_line)
                    sub_polygons = [geom for geom in split_result.geoms if
                                    geom.geom_type == 'Polygon' and geom.area > 1e-2]

                except Exception:
                    sub_polygons = []

            # 如果未触发双标签逻辑，或者上述规则切分后没有成功分解，则继续执行原有常规迭代切分
            if len(sub_polygons) < 2:
                sub_polygons = self._execute_acd_math(room_poly, constraint_geoms)

            if len(sub_polygons) < 2:
                active_spaces[old_id] = {"node": node, "poly": room_poly}
                continue

            current_nodes_to_add = []

            for i, sub_poly in enumerate(sub_polygons):
                new_id = f"{old_id}_Sub_{i + 1}"
                new_elements = []
                for elem in elem_nodes:
                    try:
                        e_wkt = elem.get("geo:asWKT", "")
                        if isinstance(e_wkt, dict): e_wkt = e_wkt.get("@value", "")
                        elem_geom = wkt_loads(e_wkt)
                        if sub_poly.contains(elem_geom.centroid):
                            new_elements.append({"@id": elem.get("@id")})
                    except Exception:
                        pass

                assigned_tag = None
                assigned_raw_text = None
                assigned_coords = None

                for anchor in text_anchors:
                    pt = Point(anchor["coordinates"])
                    if sub_poly.contains(pt):
                        assigned_tag = anchor["std_label"]
                        assigned_raw_text = anchor["raw_text"]
                        assigned_coords = anchor["coordinates"]
                        break

                if not assigned_tag:
                    assigned_tag = "bldg:Corridor"
                    assigned_raw_text = "过道"

                new_node = {
                    "@id": new_id,
                    "@type": ["bot:Space", assigned_tag],
                    "geo:asWKT": sub_poly.wkt,
                    "props:hasArea": 0.0,
                    "bot:containsElement": new_elements,
                    "bot:adjacentZone": []
                }

                if assigned_raw_text:
                    new_node["props:roomLabel"] = assigned_raw_text
                if assigned_coords:
                    new_node["props:labelCoordinates"] = assigned_coords

                current_nodes_to_add.append(new_node)
                nodes_to_add.append(new_node)
                active_spaces[new_id] = {"node": new_node, "poly": sub_poly}

            nodes_to_remove.append(node)

            for d_id, d_node in self.nodes.items():
                types = d_node.get("@type", [])
                if isinstance(types, str): types = [types]
                if "beo:Door" not in types: continue

                interfaces = d_node.get("bot:interfaceOf", [])
                if not isinstance(interfaces, list): interfaces = [interfaces]

                interface_ids = [ref.get("@id") if isinstance(ref, dict) else ref for ref in interfaces]

                if old_id in interface_ids:
                    door_wkt = d_node.get("geo:asWKT")
                    door_wkt_str = door_wkt.get("@value", door_wkt) if isinstance(door_wkt, dict) else door_wkt
                    try:
                        door_poly = wkt_loads(door_wkt_str)
                    except Exception:
                        continue

                    best_sub_id = None
                    min_dist = float('inf')
                    for new_node in current_nodes_to_add:
                        try:
                            sub_poly = wkt_loads(new_node["geo:asWKT"])
                            d = door_poly.distance(sub_poly)
                            if d < min_dist:
                                min_dist = d
                                best_sub_id = new_node["@id"]
                        except Exception:
                            continue

                    if best_sub_id:
                        new_interfaces_set = set()
                        for ref_id in interface_ids:
                            if ref_id == old_id:
                                new_interfaces_set.add(best_sub_id)
                            else:
                                new_interfaces_set.add(ref_id)

                        d_node["bot:interfaceOf"] = [{"@id": r_id} for r_id in new_interfaces_set]

                        conn_list = list(new_interfaces_set)
                        if len(conn_list) >= 2:
                            def update_adjacent_zone(target_id, neighbor_id):
                                target_node = next((n for n in current_nodes_to_add if n["@id"] == target_id), None)
                                if not target_node and target_id in active_spaces:
                                    target_node = active_spaces[target_id]["node"]
                                if target_node:
                                    adj = target_node.get("bot:adjacentZone", [])
                                    if not isinstance(adj, list): adj = [adj]
                                    if not any(
                                            (ref.get("@id") if isinstance(ref, dict) else ref) == neighbor_id for ref in
                                            adj):
                                        adj.append({"@id": neighbor_id})
                                    target_node["bot:adjacentZone"] = adj

                            for i in range(len(conn_list)):
                                for j in range(i + 1, len(conn_list)):
                                    update_adjacent_zone(conn_list[i], conn_list[j])
                                    update_adjacent_zone(conn_list[j], conn_list[i])

            for new_node in current_nodes_to_add:
                n1_id = new_node["@id"]
                try:
                    n1_poly = wkt_loads(new_node["geo:asWKT"])
                except Exception:
                    continue

                for a_id, a_info in active_spaces.items():
                    if n1_id == a_id:
                        continue

                    n2_poly = a_info["poly"]
                    target_node = a_info["node"]

                    try:
                        if self._is_adjacent(n1_poly, n2_poly, tolerance=1.0, min_overlap=10.0):
                            adj1 = new_node.get("bot:adjacentZone", [])
                            if not any(ref.get("@id") == a_id for ref in adj1 if isinstance(ref, dict)):
                                adj1.append({"@id": a_id})
                            new_node["bot:adjacentZone"] = adj1

                            adj2 = target_node.get("bot:adjacentZone", [])
                            if not isinstance(adj2, list): adj2 = [adj2]
                            if not any((ref.get("@id") if isinstance(ref, dict) else ref) == n1_id for ref in adj2):
                                adj2.append({"@id": n1_id})
                            target_node["bot:adjacentZone"] = adj2
                    except Exception:
                        pass

        for n in nodes_to_remove:
            if n in self.graph["@graph"]:
                self.graph["@graph"].remove(n)
        self.graph["@graph"].extend(nodes_to_add)

        return self.graph


if __name__ == "__main__":
    pass