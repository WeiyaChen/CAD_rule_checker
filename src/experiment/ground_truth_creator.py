import os
import sys
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from shapely.wkt import loads as wkt_loads
from shapely.geometry import Polygon, MultiPoint, LineString, Point
from math import dist
from collections import deque

from src.config.config import settings

try:
    import ezdxf
    from ezdxf import bbox
except ImportError:
    print("❌ 缺少 ezdxf 库。请先运行: pip install ezdxf")
    sys.exit(1)

try:
    from rdflib import Graph
    from pyshacl import validate
except ImportError:
    print("❌ 缺少 rdflib 或 pyshacl 库。请先运行: pip install rdflib pyshacl")
    sys.exit(1)

# =====================================================================
# 常量与映射配置
# =====================================================================
LAYER_SEMANTIC_MAP = {
    # 中英文标准图层
    "GT_BEDROOM": "Bedroom", "GT_卧室": "Bedroom",
    "GT_LIVINGROOM": "LivingRoom", "GT_客厅": "LivingRoom",
    "GT_KITCHEN": "Kitchen", "GT_厨房": "Kitchen",
    "GT_BATHROOM": "Bathroom", "GT_卫生间": "Bathroom",
    "GT_BALCONY": "Balcony", "GT_阳台": "Balcony",
    "GT_CORRIDOR": "Corridor", "GT_过道": "Corridor",
    "GT_ENTRANCE": "Entrance", "GT_玄关": "Entrance",
    "GT_GARDEN": "Garden", "GT_花园": "Garden",
    "GT_DININGROOM": "DiningRoom", "GT_餐厅": "DiningRoom",
    "GT_ELEVATORSHAFT": "ElevatorShaft", "GT_电梯": "ElevatorShaft",
    "GT_STORAGEROOM": "StorageRoom", "GT_储藏间": "StorageRoom",
    "GT_STAIRWELL": "Stairwell", "GT_楼梯": "Stairwell",
    "GT_CLOAKROOM": "Cloakroom", "GT_衣帽间": "Cloakroom",
    "GT_STUDYROOM": "StudyRoom", "GT_书房": "StudyRoom",
    "GT_SUNROOM": "SunRoom", "GT_阳光房": "SunRoom",
    "GT_WATERROOM": "WaterRoom", "GT_水机房": "WaterRoom",
    "GT_ELECTRICALROOM": "ElectricalRoom", "GT_电机房": "ElectricalRoom",
    "GT_VENTILATIONROOM": "VentilationRoom", "GT_风机房": "VentilationRoom"
}

DOOR_LAYERS = ["GT_DOOR", "GT_门"]

# 新增：内部设施图层映射
FACILITY_MAP = {
    "GT_SINK": "beo:Sink", "GT_水槽": "beo:Sink",
    "GT_BATHTUB": "beo:Bathtub", "GT_浴缸": "beo:Bathtub",
    "GT_BATH": "beo:Bath", "GT_洗浴区": "beo:Bath",
    "GT_GASSTOVE": "beo:GasStove", "GT_燃气灶": "beo:GasStove",
    "GT_TOILET": "beo:Toilet", "GT_便器": "beo:Toilet"
}

JSONLD_CONTEXT = {
    "bot": "https://w3id.org/bot#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "inst": "http://mythesis.org/instance/",
    "props": "http://mythesis.org/props/",
    "beo": "https://pi.pauwel.be/voc/buildingelement#",
    "bldg": "http://mythesis.org/bldg/",
    "geo": "http://www.opengis.net/ont/geosparql#",
    "xsd": "http://www.w3.org/2001/XMLSchema#"
}


# =====================================================================
# 核心计算算子
# =====================================================================
def auto_calculate_deltas(doc):
    """根据整个图纸的包围盒计算全局偏移矩阵"""
    msp = doc.modelspace()
    ext = bbox.extents(msp)

    if not ext.has_data:
        raise ValueError("DXF 图纸为空或无法获取边界框。")

    xmin, xmax = ext.extmin[0], ext.extmax[0]
    ymin, ymax = ext.extmin[1], ext.extmax[1]

    sx = 140 / (xmax - xmin)
    sy = 140 / (ymax - ymin)
    s = min(sx, sy)

    new_w = s * (xmax - xmin)
    new_h = s * (ymax - ymin)
    offset_x = (140 - new_w) / 2
    offset_y = (140 - new_h) / 2

    delta_x = (offset_x / s) - xmin
    delta_y = (offset_y / s) - ymin

    return delta_x, delta_y, s


def get_mrr_metrics(polygon_geom):
    """常规空间：提取几何的最小外接矩形，返回面积、长边、短边"""
    area_sqm = polygon_geom.area / 1_000_000.0
    rect = polygon_geom.minimum_rotated_rectangle

    if rect.geom_type in ['LineString', 'Point']:
        return round(area_sqm, 2), 0.0, 0.0

    coords = list(rect.exterior.coords)
    if len(coords) < 4:
        return round(area_sqm, 2), 0.0, 0.0

    edge1 = dist(coords[0], coords[1]) / 1000.0
    edge2 = dist(coords[1], coords[2]) / 1000.0

    length = max(edge1, edge2)
    width = min(edge1, edge2)

    return round(area_sqm, 2), round(length, 2), round(width, 2)


def get_corridor_clear_width(polygon_geom):
    """交通空间：基于纯矢量几何的非相邻边界最小距离算法计算通行净宽"""
    if polygon_geom.geom_type != 'Polygon':
        return 0.0

    coords = list(polygon_geom.exterior.coords)
    if len(coords) < 4:
        _, _, width = get_mrr_metrics(polygon_geom)
        return width

    edges = []
    for i in range(len(coords) - 1):
        edges.append(LineString([coords[i], coords[i + 1]]))

    min_dist = float('inf')
    found_non_adjacent = False
    num_edges = len(edges)

    for i in range(num_edges):
        for j in range(i + 2, num_edges):
            if i == 0 and j == num_edges - 1:
                continue
            distance = edges[i].distance(edges[j])
            if distance < min_dist:
                min_dist = distance
                found_non_adjacent = True

    if found_non_adjacent:
        return round(min_dist / 1000.0, 2)
    else:
        _, _, width = get_mrr_metrics(polygon_geom)
        return width


# =====================================================================
# 图谱语义推理辅助函数
# =====================================================================
def infer_interior_door_type(connected_room_types):
    if "Kitchen" in connected_room_types: return "bldg:KitchenDoor"
    if "Bathroom" in connected_room_types: return "bldg:BathroomDoor"
    if "Bedroom" in connected_room_types: return "bldg:BedroomDoor"
    return "bldg:InteriorDoor"


def infer_corridor_type(room_semantic, connected_room_types, connected_door_types):
    types = set()
    if room_semantic == "PublicCorridor":
        if "bldg:EntranceDoor" in connected_door_types:
            types.add("bldg:EntranceCorridor")
    elif room_semantic == "Corridor":
        if "Bedroom" in connected_room_types or "LivingRoom" in connected_room_types:
            types.add("bldg:MainCorridor")
        if "Kitchen" in connected_room_types or "Bathroom" in connected_room_types:
            types.add("bldg:SecondaryCorridor")
        if not types:
            types.add("bldg:Corridor")
    return list(types)


def get_min_topology_distance(start_node, target_semantics, rooms_data):
    queue = deque([(start_node, 0)])
    visited = {start_node}
    while queue:
        curr, dist = queue.popleft()
        if rooms_data[curr]['semantic'] in target_semantics:
            return dist
        for neighbor in rooms_data[curr]['adjacencies']:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))
    return float('inf')


# =====================================================================
# 主构建流程
# =====================================================================
def build_graph_from_dxf():
    print("=====================================================")
    print("🏗️  BIM 知识图谱全自动构建引擎 (几何+拓扑+设施挂载+语义)")
    print("=====================================================\n")

    dxf_input = input("👉 请拖入已经画好图层的 DXF 文件: ").strip().strip("'\"")
    if not os.path.exists(dxf_input):
        print(f"\n❌ 找不到文件: {dxf_input}")
        return

    try:
        doc = ezdxf.readfile(dxf_input)
        delta_x, delta_y, scale_factor = auto_calculate_deltas(doc)
        print(f"✅ [校准成功] Delta X: {delta_x:.2f} | Delta Y: {delta_y:.2f}\n")
    except Exception as e:
        print(f"\n❌ DXF 读取或校准失败: {e}")
        return

    msp = doc.modelspace()

    rooms_data = {}
    doors_data = {}
    facilities_data = {}  # 新增：设施数据字典

    room_counter, door_counter, facility_counter = 1, 1, 1

    print("🔍 阶段 1/4: 扫描并重建多边形实体 (执行差异化几何核算)...")

    # 1. 扫描提取图元
    for entity in msp:
        layer_name = entity.dxf.layer.upper()

        if hasattr(entity, 'get_points'):
            points = list(entity.get_points(format='xy'))
        elif entity.dxftype() in ['LINE']:
            points = [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
        else:
            continue

        if not points or len(points) < 2: continue

        translated_points = [(round(x + delta_x), round(y + delta_y)) for x, y in points]

        # A. 房间识别
        if layer_name.startswith("GT_") and layer_name not in DOOR_LAYERS and layer_name not in FACILITY_MAP:
            semantic_type = LAYER_SEMANTIC_MAP.get(layer_name, "Unknown")

            if dist(translated_points[0], translated_points[-1]) > 1e-5:
                translated_points.append(translated_points[0])

            poly_geom = Polygon(translated_points)
            if not poly_geom.is_valid:
                poly_geom = poly_geom.buffer(0)

            if semantic_type == "Corridor":
                area = round(poly_geom.area / 1_000_000.0, 2)
                calculated_width = get_corridor_clear_width(poly_geom)
            else:
                area, _, calculated_width = get_mrr_metrics(poly_geom)

            node_id = f"inst:Space_{room_counter:03d}"
            rooms_data[node_id] = {
                "id": node_id,
                "geom": poly_geom,
                "semantic": semantic_type,
                "area": area,
                "calculated_width": calculated_width,
                "adjacencies": set(),
                "contained_facilities": set()  # 新增：记录该房间包含的设施ID
            }
            room_counter += 1

        # B. 门识别
        elif layer_name in DOOR_LAYERS:
            mrr_geom = MultiPoint(translated_points).minimum_rotated_rectangle
            area, length, width = get_mrr_metrics(mrr_geom)

            node_id = f"inst:Door_{door_counter:03d}"
            doors_data[node_id] = {
                "id": node_id,
                "geom": mrr_geom,
                "clear_width": length,
                "interfaces": set(),
                "door_type": "beo:Door"
            }
            door_counter += 1

        # C. 内部设施识别 (水槽、浴缸、燃气灶)
        elif layer_name in FACILITY_MAP:
            # 无论设施原形状如何，取其最小外接矩形作为物理占位，并计算质心
            mrr_geom = MultiPoint(translated_points).minimum_rotated_rectangle
            centroid = mrr_geom.centroid

            node_id = f"inst:Facility_{facility_counter:03d}"
            facilities_data[node_id] = {
                "id": node_id,
                "geom": mrr_geom,
                "centroid": centroid,
                "semantic": FACILITY_MAP[layer_name],
                "mounted_room": None  # 初始化归属房间为空
            }
            facility_counter += 1

    print(f"  [+] 成功提取 {len(rooms_data)} 个房间, {len(doors_data)} 扇门, {len(facilities_data)} 个内部设施。")

    print("🔍 阶段 2/4: 自动计算空间底层拓扑网络与设施挂载...")
    room_ids = list(rooms_data.keys())

    # 2.1 房间之间的拓扑提取
    min_overlap_length = 1
    for i in range(len(room_ids)):
        for j in range(i + 1, len(room_ids)):
            r1, r2 = rooms_data[room_ids[i]], rooms_data[room_ids[j]]
            overlap = r1['geom'].intersection(r2['geom']).intersection(r1['geom'].boundary)

            overlap_len = 0.0
            if overlap.geom_type == 'LineString':
                overlap_len = overlap.length
            elif overlap.geom_type == 'MultiLineString':
                overlap_len = sum(line.length for line in overlap.geoms)
            elif overlap.geom_type == 'GeometryCollection':
                lines = [g for g in overlap.geoms if g.geom_type in ['LineString', 'MultiLineString']]
                for l in lines:
                    if l.geom_type == 'LineString':
                        overlap_len += l.length
                    else:
                        overlap_len += sum(sl.length for sl in l.geoms)

            if overlap_len > min_overlap_length:
                r1['adjacencies'].add(r2['id'])
                r2['adjacencies'].add(r1['id'])

    # 2.2 门桥接拓扑提取
    ray_len = 300
    for d_id, door in doors_data.items():
        door_geom = door['geom']
        buffered_door = door_geom.buffer(0)

        best_line = None
        max_len = 0

        for r_id, room in rooms_data.items():
            intersection = buffered_door.intersection(room['geom'].boundary)
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

        if best_line and max_len > 1e-3:
            coords = list(best_line.coords)
            p1, p2 = np.array(coords[0]), np.array(coords[-1])
            midpoint = (p1 + p2) / 2.0
            vec = p2 - p1
            vec_len = np.linalg.norm(vec)
            if vec_len > 1e-5:
                unit_vec = vec / vec_len
                normal_vec = np.array([-unit_vec[1], unit_vec[0]])
                ray_line = LineString([midpoint - normal_vec * ray_len, midpoint + normal_vec * ray_len])

                for r_id, room in rooms_data.items():
                    if room['geom'].intersects(ray_line):
                        door['interfaces'].add(r_id)

        if not door['interfaces']:
            fallback_tol = 300
            for r_id, room in rooms_data.items():
                if door_geom.distance(room['geom']) < fallback_tol:
                    door['interfaces'].add(r_id)

        conn_list = list(door['interfaces'])
        if len(conn_list) == 2:
            rA, rB = rooms_data[conn_list[0]], rooms_data[conn_list[1]]
            rA['adjacencies'].add(rB['id'])
            rB['adjacencies'].add(rA['id'])

    # 2.3 设施挂载拓扑 (Spatial Join)
    # 利用设施的质心判断其落入哪个房间的多边形内部
    mounted_count = 0
    for f_id, facility in facilities_data.items():
        centroid = facility['centroid']
        for r_id, room in rooms_data.items():
            # 使用包含判定，若由于精度问题质心在边界上，退化为极小距离容差判断
            if room['geom'].contains(centroid) or room['geom'].distance(centroid) < 5.0:
                facility['mounted_room'] = r_id
                room['contained_facilities'].add(f_id)
                mounted_count += 1
                break
    print(f"  [+] 设施拓扑挂载完毕，成功将 {mounted_count}/{len(facilities_data)} 个设施关联至所在房间。")

    print("🔍 阶段 3/4: 外部区域检测、高级语义推断与套型组装...")
    # 3.1 识别公共外部空间与内部走廊
    PUBLIC_SEEDS = {"ElevatorShaft", "Stairwell", "WaterRoom", "ElectricalRoom", "VentilationRoom", "EquipmentRoom"}
    PRIVATE_SEEDS = {"Bedroom", "LivingRoom", "Kitchen", "Bathroom", "DiningRoom", "Cloakroom", "StudyRoom", "Balcony",
                     "Entrance"}

    public_spaces = set()
    for r_id, room in rooms_data.items():
        if room['semantic'] in PUBLIC_SEEDS:
            public_spaces.add(r_id)

    for r_id, room in rooms_data.items():
        if room['semantic'] == "Corridor":
            dist_to_pub = get_min_topology_distance(r_id, PUBLIC_SEEDS, rooms_data)
            dist_to_priv = get_min_topology_distance(r_id, PRIVATE_SEEDS, rooms_data)

            if dist_to_pub <= dist_to_priv and dist_to_pub != float('inf'):
                room['semantic'] = "PublicCorridor"
                public_spaces.add(r_id)

    # 3.2 门洞类型判定
    for d_id, door in doors_data.items():
        conn_list = list(door['interfaces'])
        connected_semantics = [rooms_data[r]['semantic'] for r in conn_list]

        is_entrance = False
        if len(conn_list) < 2:
            is_entrance = True
        else:
            r1_pub = conn_list[0] in public_spaces
            r2_pub = conn_list[1] in public_spaces
            if r1_pub != r2_pub:
                is_entrance = True

        if is_entrance:
            door['door_type'] = "bldg:EntranceDoor"
        else:
            door['door_type'] = infer_interior_door_type(connected_semantics)

    # 3.3 细化内部私有过道类型
    for r_id, room in rooms_data.items():
        if room['semantic'] in ["Corridor", "PublicCorridor"]:
            neighbor_room_types = [rooms_data[n]['semantic'] for n in room['adjacencies']]
            connected_door_types = [door['door_type'] for door in doors_data.values() if r_id in door['interfaces']]
            composite_types = infer_corridor_type(room['semantic'], neighbor_room_types, connected_door_types)
            if composite_types:
                room['composite_corridor_types'] = composite_types

    # 3.4 广度优先搜索 (BFS) 识别独立套型 (Suite)
    suites = []
    PUBLIC_BLOCKERS = {"ElevatorShaft", "Stairwell", "WaterRoom", "ElectricalRoom", "VentilationRoom", "EquipmentRoom",
                       "PublicCorridor", "Unknown"}

    visited_rooms = set()
    for r_id, room in rooms_data.items():
        if room['semantic'] in PUBLIC_BLOCKERS:
            visited_rooms.add(r_id)

    suite_counter = 1
    for r_id, room in rooms_data.items():
        if r_id not in visited_rooms:
            current_suite = []
            queue = deque([r_id])
            visited_rooms.add(r_id)

            while queue:
                curr = queue.popleft()
                current_suite.append(curr)

                for neighbor in rooms_data[curr]['adjacencies']:
                    if neighbor not in visited_rooms:
                        if rooms_data[neighbor]['semantic'] not in PUBLIC_BLOCKERS:
                            visited_rooms.add(neighbor)
                            queue.append(neighbor)

            if current_suite:
                suites.append({
                    "@id": f"inst:Suite_{suite_counter:02d}",
                    "@type": ["bot:Zone", "bldg:Suite"],
                    "bot:hasSpace": [{"@id": sid} for sid in current_suite]
                })
                suite_counter += 1

    print("📝 阶段 4/4: 序列化为 JSON-LD 知识图谱 (对齐 EXP 格式)...")

    graph_nodes = []
    graph_nodes.extend(suites)

    # 写入房间节点 (WKT 格式对齐 EXP 组的字典结构)
    for r_id, room in rooms_data.items():
        types = ["bot:Space"]
        if room['semantic'] == "Corridor" and 'composite_corridor_types' in room:
            types.extend(room['composite_corridor_types'])
        else:
            types.append(f"bldg:{room['semantic']}")

        node = {
            "@id": r_id,
            "@type": types,
            "geo:asWKT": {
                "@value": room['geom'].wkt,
                "@type": "geo:wktLiteral"
            },
            "props:hasArea": room['area']
        }

        if "Corridor" in room['semantic']:
            node["props:clearWidth"] = room['calculated_width']
        else:
            node["props:hasShortSide"] = room['calculated_width']

        if room['adjacencies']:
            node["bot:adjacentZone"] = [{"@id": n} for n in room['adjacencies']]

        if room['contained_facilities']:
            node["bot:containsElement"] = [{"@id": f_id} for f_id in room['contained_facilities']]

        graph_nodes.append(node)

    # 写入门节点 (WKT 格式对齐)
    for d_id, door in doors_data.items():
        types = ["bot:Element", "beo:Door", door['door_type']]
        node = {
            "@id": d_id,
            "@type": types,
            "geo:asWKT": {
                "@value": door['geom'].wkt,
                "@type": "geo:wktLiteral"
            },
            "props:clearWidth": door['clear_width']
        }
        if door.get('frontage_width') is not None:
            node["props:hasFrontageClearWidth"] = door['frontage_width']
        if door['interfaces']:
            node["bot:interfaceOf"] = [{"@id": n} for n in door['interfaces']]

        graph_nodes.append(node)

    # 写入设施节点 (全面对齐 EXP 组的 FunctionalElement 与 rdfs:label 格式)
    for f_id, facility in facilities_data.items():
        sem_type = facility['semantic']

        # 提取具体的名称并格式化为 rdfs:label (如 'beo:Sink' -> 'sink')
        label = sem_type.split(":")[-1].lower()
        if label == "gasstove":
            label = "gas stove"
        elif label == "bathtub":
            label = "bath"
        elif label == "toilet":
            label = "toilet"
        elif label == "sink":
            label = "sink"

        types = ["bot:Element", "beo:FunctionalElement"]
        node = {
            "@id": f_id,
            "@type": types,
            "rdfs:label": label,
            "geo:asWKT": {
                "@value": facility['geom'].wkt,
                "@type": "geo:wktLiteral"
            }
        }
        graph_nodes.append(node)

    jsonld_output = {
        "@context": JSONLD_CONTEXT,
        "@graph": graph_nodes
    }

    base_name = os.path.splitext(os.path.basename(dxf_input))[0].replace("_已标注", "")
    out_filename = f"{base_name}_gt.jsonld"

    # 上一级目录
    abs_input_path = os.path.abspath(dxf_input)
    parent_dir_name = os.path.basename(os.path.dirname(abs_input_path))

    # 输出目录
    ground_truth_dir = settings.gt_jsonld_dir

    # 防止重创建
    target_dir = os.path.join(ground_truth_dir, parent_dir_name)
    os.makedirs(target_dir, exist_ok=True)  # exist_ok=True 防止目录已存在时报错

    out_path = os.path.join(target_dir, out_filename)

    # =====================================================================
    # 阶段 4.5: 自动执行 SHACL 规则审查生成违规 GT
    # =====================================================================
    print("⚖️ 阶段 4.5: 自动执行 SHACL 规则审查，固化违规 Ground Truth...")
    violations_list = []
    try:
        data_graph = Graph()
        data_graph.parse(data=json.dumps(jsonld_output, ensure_ascii=False), format="json-ld")

        target_shacl_files = [
            "l1_semantic_check.ttl",
            "l2_geometirc_check.ttl",
            "l3_topologiccal_check.ttl"
        ]

        for shacl_file in target_shacl_files:
            if not os.path.exists(os.path.join(settings.rules_dir, shacl_file)):
                continue

            shacl_graph = Graph()
            shacl_graph.parse(os.path.join(settings.rules_dir, shacl_file), format="turtle")

            conforms, results_graph, results_text = validate(
                data_graph,
                shacl_graph=shacl_graph,
                inference='rdfs',
                abort_on_first=False,
                meta_shacl=False,
                debug=False
            )

            if not conforms:
                query = """
                    PREFIX sh: <http://www.w3.org/ns/shacl#>
                    SELECT ?focusNode ?message ?sourceShape
                    WHERE {
                        ?report a sh:ValidationReport ;
                                sh:result ?result .
                        ?result sh:focusNode ?focusNode ;
                                sh:resultMessage ?message ;
                                sh:sourceShape ?sourceShape .
                    }
                """
                violations = results_graph.query(query)
                for row in violations:
                    v_node_id = str(row.focusNode).split('/')[-1]
                    v_msg = str(row.message)
                    v_rule = str(row.sourceShape).split('/')[-1] if row.sourceShape else "UnknownRule"

                    violations_list.append({
                        "node_id": v_node_id,
                        "message": v_msg,
                        "rule": v_rule
                    })

        print(f"  [+] 成功提取 {len(violations_list)} 个规范违规项作为实验基准。")
    except Exception as e:
        print(f"  [-] SHACL 审查引擎执行发生异常: {e}")

    jsonld_output["violations"] = violations_list

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(jsonld_output, f, ensure_ascii=False, indent=2)

    out_vio_filename = f"{base_name}_gt_violations.json"

    target_dir = os.path.join(settings.gt_res_dir, parent_dir_name)
    os.makedirs(target_dir, exist_ok=True)  # exist_ok=True 防止目录已存在时报错

    out_vio_path = os.path.join(target_dir, out_vio_filename)
    with open(out_vio_path, 'w', encoding='utf-8') as f:
        json.dump(violations_list, f, ensure_ascii=False, indent=2)

    # 计算拓扑连通边数（无向图边数 = 总度数 // 2）
    total_edges = sum(len(room['adjacencies']) for room in rooms_data.values()) // 2

    print("\n" + "=" * 50)
    print("📊 数据集核心特征统计:")
    print(f"  - 独立空间节点数 (Rooms):     {len(rooms_data)}")
    print(f"  - 门构件数 (Doors):           {len(doors_data)}")
    print(f"  - 拓扑联通边数 (Edges):       {total_edges}")
    # print(f"  - 内部设施数 (Facilities):    {len(facilities_data)}")
    print(f"  - 提取独立套型数 (Suites):    {len(suites)}")
    # print(f"  - 确认真实违规数 (Violations):{len(violations_list)}")
    print("=" * 50 + "\n")

    # =====================================================================
    # 5. 可视化结果生成 (已修改：支持不同房间不同颜色)
    # =====================================================================
    fig, ax = plt.subplots(figsize=(10, 8))
    # 设置支持中文的字体，防止“未知空间”等标签乱码
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

    # 定义房间语义到颜色的映射表 (使用十六进制颜色，建议选择淡雅的颜色以防遮挡文字)
    # 你可以根据喜好随意修改这里的颜色值
    ROOM_COLOR_MAP = {
        "Bedroom": "#AEC6CF",  # 淡蓝色
        "LivingRoom": "#FFDAC1",  # 浅桃色
        "Kitchen": "#FFB7B2",  # 淡红色
        "Bathroom": "#B19CD9",  # 淡紫色
        "Balcony": "#CFCFC4",  # 浅灰色
        "Corridor": "#FDFD96",  # 淡黄色
        "Entrance": "#FFB7C5",  # 淡粉色
        "DiningRoom": "#E2F0CB",  # 淡青色
        "PublicCorridor": "#D3D3D3",  # 中灰色 (公共区域)
        "StudyRoom": "#C5E3BF",  # 浅绿色
        "StorageRoom": "#E0C9A6",  # 浅褐色
        "Unknown": "#F5F5F5"  # 烟白色 (未知)
    }

    # 绘制房间
    print("🎨 正在生成彩色拓扑预览图...")
    for r_id, room in rooms_data.items():
        poly = room['geom']
        x, y = poly.exterior.xy

        # 获取房间语义
        semantic = room['semantic']

        # 根据语义获取颜色，如果没有定义，则使用默认的浅蓝色
        # 这里的 alpha=0.6 设置了透明度，让底色不那么刺眼
        fc_color = ROOM_COLOR_MAP.get(semantic, "#ADD8E6")  # 默认淡蓝色

        # 绘制填充区域
        ax.fill(x, y, alpha=0.6, fc=fc_color, ec='#404040', lw=1, zorder=1)

        # 绘制房间标签 (语义 + 面积)
        centroid = poly.centroid
        if not centroid.is_empty:
            ax.text(poly.centroid.x, poly.centroid.y, f"{semantic}\n({room['area']}㎡)",
                    ha='center', va='center', fontsize=12, fontweight='bold',
                    color='#2C3E50', zorder=10)  # 确保文字在最上层
        else:
            print(f"警告：发现空几何体，语义标签为: {semantic}")

    # 绘制门 (保持原样，高亮显示)
    for d_id, door in doors_data.items():
        poly = door['geom']
        x, y = poly.exterior.xy
        is_entr = (door['door_type'] == "bldg:EntranceDoor")
        door_color = '#E74C3C' if is_entr else '#FAD7A1'  # 入户门红色，内部门橙色
        edge_color = '#C0392B' if is_entr else '#E67E22'
        ax.fill(x, y, alpha=0.9, fc=door_color, ec=edge_color, lw=2, zorder=5)

    # 绘制挂载的设施质心 (保持原样)
    for f_id, facility in facilities_data.items():
        cx, cy = facility['centroid'].x, facility['centroid'].y
        f_type = facility['semantic']
        if f_type == "beo:Sink":
            marker, color = 'v', '#1E90FF'  # 蓝色下三角
        elif f_type == "beo:Bathtub":
            marker, color = 's', '#00CED1'  # 碧绿色正方形
        elif f_type == "beo:GasStove":
            marker, color = '^', '#FF4500'  # 橙红色上三角
        else:
            marker, color = 'o', '#808080'  # 灰色圆点

        ax.scatter(cx, cy, marker=marker, color=color, s=60, edgecolors='black', zorder=15)
        # 为设施添加极小的文字标签
        label_text = f_type.split(':')[-1]
        ax.text(cx, cy + 150, label_text, fontsize=7, ha='center',
                color='#000080', fontweight='bold', zorder=16)

    # 差异化绘制拓扑连通关系 (保持原样)
    # 1. 通过门连接的边 (绿色虚线)
    door_edges = set()
    for d_id, door in doors_data.items():
        conn = list(door['interfaces'])
        if len(conn) == 2:
            edge = tuple(sorted([conn[0], conn[1]]))
            door_edges.add(edge)
            p1, p2 = rooms_data[conn[0]]['geom'].centroid, rooms_data[conn[1]]['geom'].centroid
            ax.plot([p1.x, p2.x], [p1.y, p2.y], color='#27AE60', linestyle='--', lw=2.5, alpha=0.8, zorder=20)

    # 2. 纯几何相邻的边 (蓝色实线)
    drawn_adj_edges = set()
    for r_id, room in rooms_data.items():
        for adj_id in room['adjacencies']:
            edge = tuple(sorted([r_id, adj_id]))
            if edge not in drawn_adj_edges and edge not in door_edges:
                drawn_adj_edges.add(edge)
                p1 = rooms_data[r_id]['geom'].centroid
                p2 = rooms_data[adj_id]['geom'].centroid
                ax.plot([p1.x, p2.x], [p1.y, p2.y], color='#2980B9', linestyle='-', lw=1.5, alpha=0.5, zorder=19)

    # 界面美化设置
    ax.set_aspect('equal')
    ax.axis('off')  # 关闭坐标轴
    plt.title("全局拓扑与彩色分区解析预览", pad=20, fontsize=14, fontweight='bold')

    # 保存图片
    img_dir = settings.gt_viz_dir
    if not os.path.exists(img_dir): os.makedirs(img_dir)

    target_dir = os.path.join(img_dir, parent_dir_name)
    os.makedirs(target_dir, exist_ok=True)  # exist_ok=True 防止目录已存在时报错
    out_img_filename = f"{base_name}_gt.png"
    out_img_path = os.path.join(target_dir, out_img_filename)

    plt.tight_layout()
    plt.savefig(out_img_path, bbox_inches='tight', dpi=300)
    print(f"✅ 彩色拓扑预览图已保存至: {out_img_path}")

    plt.close(fig)


if __name__ == "__main__":
    build_graph_from_dxf()
