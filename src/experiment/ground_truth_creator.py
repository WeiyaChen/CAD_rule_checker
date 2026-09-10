import os
os.environ.setdefault('MPLBACKEND', 'Agg')  # Force non-interactive backend in batch mode to prevent popups

import sys
import json
import traceback
from pathlib import Path
from typing import Any, cast

import numpy as np
import matplotlib.pyplot as plt
from shapely.geometry import Polygon, MultiPoint, LineString
from math import dist
from collections import deque

from src.config.config import settings
from src.config.gt_constants import (
    DOOR_LAYERS,
    FUNCTIONAL_ELEMENT_MAP,
    JSONLD_CONTEXT,
    LAYER_SEMANTIC_MAP,
    PRIVATE_SEEDS,
    PUBLIC_BLOCKERS,
    PUBLIC_SEEDS,
    ROOM_COLOR_MAP,
)

try:
    from ezdxf import bbox
    from ezdxf.filemanagement import readfile
except ImportError:
    print("❌ Missing ezdxf library. Please run: pip install ezdxf")
    sys.exit(1)

try:
    from rdflib import Graph
    from pyshacl import validate
except ImportError:
    print("❌ Missing rdflib or pyshacl library. Please run: pip install rdflib pyshacl")
    sys.exit(1)

# =====================================================================
# Core computational operators
# =====================================================================
def auto_calculate_deltas(doc):
    """Compute the global offset matrix from the entire drawing's bounding box."""
    msp = doc.modelspace()
    ext = bbox.extents(msp)

    if not ext.has_data:
        raise ValueError("DXF drawing is empty or bounding box cannot be obtained.")

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
    """Regular space: extract the minimum bounding rectangle and return area, long side, short side."""
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
    """Circulation space: compute the clear passage width using the non-adjacent boundary minimum-distance algorithm on pure vector geometry."""
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
# Graph semantic inference helper functions
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
# Main build flow
# =====================================================================
def build_graph_from_dxf(dxf_input=None):
    """Process a single annotated DXF drawing and generate GT JSON-LD / violation baseline / topology visualization.

    Args:
        dxf_input: Path to the DXF file. When None, enters interactive mode where user drags in input.
    Returns:
        "OK" for successful processing, otherwise returns "ERROR".
    """
    print("=====================================================")
    print("🏗️  BIM Knowledge Graph Auto-Construction Engine (Geometry + Topology + Component instances + Semantics)")
    print("=====================================================\n")

    if dxf_input is None:
        dxf_input = input("👉 Drag in a DXF file with layers already drawn: ").strip().strip("'\"")
    if not os.path.exists(dxf_input):
        print(f"\n❌ File not found: {dxf_input}")
        return "ERROR"

    try:
        doc = readfile(dxf_input)
        delta_x, delta_y, _ = auto_calculate_deltas(doc)
        print(f"✅ [Calibration OK] Delta X: {delta_x:.2f} | Delta Y: {delta_y:.2f}\n")
    except Exception as e:
        print(f"\n❌ DXF read or calibration failed: {e}")
        return "ERROR"

    msp = doc.modelspace()

    rooms_data = {}
    doors_data = {}
    functional_elements_data = {}  # Added: functional element data dictionary

    room_counter, door_counter, fe_counter = 1, 1, 1

    print("🔍 Phase 1/4: Scanning and reconstructing polygon entities (performing differentiated geometry calculation)...")

    # 1. Scan and extract entities
    for entity in msp:
        layer_name = entity.dxf.layer.upper()

        if hasattr(entity, 'get_points'):
            points = list(getattr(entity, 'get_points')(format='xy'))
        elif entity.dxftype() in ['LINE']:
            points = [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
        else:
            continue

        if not points or len(points) < 2: continue

        translated_points = [(round(x + delta_x), round(y + delta_y)) for x, y in points]

        # A. Room recognition
        if layer_name.startswith("GT_") and layer_name not in DOOR_LAYERS and layer_name not in FUNCTIONAL_ELEMENT_MAP:
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
                "contained_elements": set()  # Added: record functional-element IDs contained in this room
            }
            room_counter += 1

        # B. Door recognition
        elif layer_name in DOOR_LAYERS:
            mrr_geom = MultiPoint(translated_points).minimum_rotated_rectangle
            area, length, _ = get_mrr_metrics(mrr_geom)

            node_id = f"inst:Door_{door_counter:03d}"
            doors_data[node_id] = {
                "id": node_id,
                "geom": mrr_geom,
                "clear_width": length,
                "interfaces": set(),
                "door_type": "beo:Door"
            }
            door_counter += 1

        # C. Internal functional element recognition (sink, bathtub, gas stove)
        elif layer_name in FUNCTIONAL_ELEMENT_MAP:
            # Regardless of the element's original shape, use its minimum bounding rectangle as the physical footprint and compute the centroid.
            mrr_geom = MultiPoint(translated_points).minimum_rotated_rectangle
            centroid = mrr_geom.centroid

            node_id = f"inst:FunctionalElement_{fe_counter:03d}"
            functional_elements_data[node_id] = {
                "id": node_id,
                "geom": mrr_geom,
                "centroid": centroid,
                "semantic": FUNCTIONAL_ELEMENT_MAP[layer_name],
                "mounted_room": None  # Initialize the mounted room as empty
            }
            fe_counter += 1

    print(f"  [+] Successfully extracted {len(rooms_data)} rooms, {len(doors_data)} doors, {len(functional_elements_data)} functional elements.")

    print("🔍 Phase 2/4: Computing spatial topology network and functional-element mounting...")
    room_ids = list(rooms_data.keys())

    # 2.1 Topology extraction between rooms
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

    # 2.2 Door-bridged topology extraction
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

    # 2.3 Functional-element mounting topology (Spatial Join)
    # Use each element's centroid to determine which room polygon it falls into.
    mounted_count = 0
    for f_id, fe in functional_elements_data.items():
        centroid = fe['centroid']
        for r_id, room in rooms_data.items():
            # Use a containment check; if the centroid lies on the boundary due to precision issues, fall back to a tiny distance tolerance.
            if room['geom'].contains(centroid) or room['geom'].distance(centroid) < 5.0:
                fe['mounted_room'] = r_id
                room['contained_elements'].add(f_id)
                mounted_count += 1
                break
    print(f"  [+] Functional-element mounting complete. Successfully associated {mounted_count}/{len(functional_elements_data)} elements to their rooms.")

    print("🔍 Phase 3/4: External area detection, advanced semantic inference, and suite assembly...")
    # 3.1 Identify public/exterior spaces and interior corridors

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

    # 3.2 Door type determination
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

    # 3.3 Refine interior private corridor types
    for r_id, room in rooms_data.items():
        if room['semantic'] in ["Corridor", "PublicCorridor"]:
            neighbor_room_types = [rooms_data[n]['semantic'] for n in room['adjacencies']]
            connected_door_types = [door['door_type'] for door in doors_data.values() if r_id in door['interfaces']]
            composite_types = infer_corridor_type(room['semantic'], neighbor_room_types, connected_door_types)
            if composite_types:
                room['composite_corridor_types'] = composite_types

    # 3.4 Breadth-first search (BFS) to identify independent suites (Suites)
    suites = []

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

    print("📝 Phase 4/4: Serializing to JSON-LD knowledge graph (aligned with EXP format)...")

    graph_nodes = []
    graph_nodes.extend(suites)

    # Write room nodes (WKT format aligned with the EXP group's dictionary structure)
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

        if room['contained_elements']:
            node["bot:containsElement"] = [{"@id": f_id} for f_id in room['contained_elements']]

        graph_nodes.append(node)

    # Write door nodes (WKT format aligned)
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

    # Write functional element nodes (fully aligned with the EXP group's FunctionalElement and rdfs:label format)
    for f_id, fe in functional_elements_data.items():
        sem_type = fe['semantic']

        # Extract the concrete name and format it as rdfs:label (e.g. 'beo:Sink' -> 'sink')
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
                "@value": fe['geom'].wkt,
                "@type": "geo:wktLiteral"
            }
        }
        graph_nodes.append(node)

    jsonld_output = {
        "@context": JSONLD_CONTEXT,
        "@graph": graph_nodes
    }

    base_name = os.path.splitext(os.path.basename(dxf_input))[0].replace("_annotated", "")
    out_filename = f"{base_name}_gt.jsonld"

    ground_truth_dir = str(settings.gt_dir)
    os.makedirs(ground_truth_dir, exist_ok=True)

    out_path = os.path.join(ground_truth_dir, out_filename)

    # =====================================================================
    # Phase 4.5: Auto-execute SHACL rule validation to generate violation GT
    # =====================================================================
    print("⚖️ Phase 4.5: Auto-executing SHACL rule validation, generating violation Ground Truth...")
    violations_list = []
    try:
        data_graph = Graph()
        data_graph.parse(data=json.dumps(jsonld_output, ensure_ascii=False), format="json-ld")

        target_shacl_files = [
            "l1_semantic_check.ttl",
            "l2_geometric_check.ttl",
            "l3_topological_check.ttl"
        ]

        for shacl_file in target_shacl_files:
            shacl_file_path = os.path.join(str(settings.rules_dir), shacl_file)
            if not os.path.exists(shacl_file_path):
                continue

            shacl_graph = Graph()
            shacl_graph.parse(shacl_file_path, format="turtle")

            conforms, results_graph, _ = validate(
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
                violations = cast(Any, results_graph).query(query)
                for row in violations:
                    v_node_id = str(row.focusNode).split('/')[-1]
                    v_msg = str(row.message)
                    v_rule = str(row.sourceShape).split('/')[-1] if row.sourceShape else "UnknownRule"

                    violations_list.append({
                        "node_id": v_node_id,
                        "message": v_msg,
                        "rule": v_rule
                    })

        print(f"  [+] Successfully extracted {len(violations_list)} compliance violations as experimental baseline.")
    except Exception as e:
        print(f"  [-] SHACL validation engine execution error: {e}")

    jsonld_output["violations"] = violations_list

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(jsonld_output, f, ensure_ascii=False, indent=2)

    out_vio_filename = f"{base_name}_gt_violations.json"

    target_dir = str(settings.violations_dir)
    os.makedirs(target_dir, exist_ok=True)

    out_vio_path = os.path.join(target_dir, out_vio_filename)
    with open(out_vio_path, 'w', encoding='utf-8') as f:
        json.dump(violations_list, f, ensure_ascii=False, indent=2)

    # Compute the number of topology-connected edges (undirected graph edges = total degree // 2)
    total_edges = sum(len(room['adjacencies']) for room in rooms_data.values()) // 2

    print("\n" + "=" * 50)
    print("📊 Dataset Core Feature Statistics:")
    print(f"  - Room Nodes:                   {len(rooms_data)}")
    print(f"  - Door Elements:                {len(doors_data)}")
    print(f"  - Topology Edges:               {total_edges}")
    # print(f"  - Functional Elements:          {len(functional_elements_data)}")
    print(f"  - Extracted Suites:             {len(suites)}")
    # print(f"  - Violations:                   {len(violations_list)}")
    print("=" * 50 + "\n")

    # =====================================================================
    # 5. Visualization result generation (modified: supports different colors per room)
    # =====================================================================
    fig, ax = plt.subplots(figsize=(10, 8))
    # Set a font that supports Chinese to prevent garbled labels such as "Unknown Space".
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False  # Fix negative sign display

    # ROOM_COLOR_MAP (room semantic -> color) is defined in src/config/gt_constants.py.

    # Draw rooms
    print("🎨 Generating colored topology preview...")
    for r_id, room in rooms_data.items():
        poly = room['geom']
        x, y = poly.exterior.xy

        # Get the room semantic
        semantic = room['semantic']

        # Get the color by semantic; use default light blue if undefined.
        # alpha=0.6 sets transparency so the base color is not too glaring.
        fc_color = ROOM_COLOR_MAP.get(semantic, "#ADD8E6")  # default light blue

        # Draw the filled area
        ax.fill(x, y, alpha=0.6, fc=fc_color, ec='#404040', lw=1, zorder=1)

        # Draw the room label (semantic + area)
        centroid = poly.centroid
        if not centroid.is_empty:
            ax.text(poly.centroid.x, poly.centroid.y, f"{semantic}\n({room['area']}m²)",
                    ha='center', va='center', fontsize=12, fontweight='bold',
                    color='#2C3E50', zorder=10)  # Ensure text stays on top
        else:
            print(f"Warning: Empty geometry found, semantic label: {semantic}")

    # Draw doors (as-is, highlighted)
    for d_id, door in doors_data.items():
        poly = door['geom']
        x, y = poly.exterior.xy
        is_entr = (door['door_type'] == "bldg:EntranceDoor")
        door_color = '#E74C3C' if is_entr else '#FAD7A1'  # entrance doors red, interior doors orange
        edge_color = '#C0392B' if is_entr else '#E67E22'
        ax.fill(x, y, alpha=0.9, fc=door_color, ec=edge_color, lw=2, zorder=5)

    # Draw mounted functional element centroids (as-is)
    for f_id, fe in functional_elements_data.items():
        cx, cy = fe['centroid'].x, fe['centroid'].y
        f_type = fe['semantic']
        if f_type == "beo:Sink":
            marker, color = 'v', '#1E90FF'  # blue downward triangle
        elif f_type == "beo:Bathtub":
            marker, color = 's', '#00CED1'  # turquoise square
        elif f_type == "beo:GasStove":
            marker, color = '^', '#FF4500'  # orange-red upward triangle
        else:
            marker, color = 'o', '#808080'  # gray dot

        ax.scatter(cx, cy, marker=marker, color=color, s=60, edgecolors='black', zorder=15)
        # Add a tiny text label for the element
        label_text = f_type.split(':')[-1]
        ax.text(cx, cy + 150, label_text, fontsize=7, ha='center',
                color='#000080', fontweight='bold', zorder=16)

    # Draw topology connectivity with differentiation (as-is)
    # 1. Edges connected through doors (green dashed)
    door_edges = set()
    for d_id, door in doors_data.items():
        conn = list(door['interfaces'])
        if len(conn) == 2:
            edge = tuple(sorted([conn[0], conn[1]]))
            door_edges.add(edge)
            p1, p2 = rooms_data[conn[0]]['geom'].centroid, rooms_data[conn[1]]['geom'].centroid
            ax.plot([p1.x, p2.x], [p1.y, p2.y], color='#27AE60', linestyle='--', lw=2.5, alpha=0.8, zorder=20)

    # 2. Edges adjacent purely by geometry (blue solid)
    drawn_adj_edges = set()
    for r_id, room in rooms_data.items():
        for adj_id in room['adjacencies']:
            edge = tuple(sorted([r_id, adj_id]))
            if edge not in drawn_adj_edges and edge not in door_edges:
                drawn_adj_edges.add(edge)
                p1 = rooms_data[r_id]['geom'].centroid
                p2 = rooms_data[adj_id]['geom'].centroid
                ax.plot([p1.x, p2.x], [p1.y, p2.y], color='#2980B9', linestyle='-', lw=1.5, alpha=0.5, zorder=19)

    # Plot beautification settings
    ax.set_aspect('equal')
    ax.axis('off')  # Turn off axes
    plt.title("Global Topology & Colored Zone Analysis Preview", pad=20, fontsize=14, fontweight='bold')

    # Save image
    img_dir = str(settings.viz_dir)
    if not os.path.exists(img_dir): os.makedirs(img_dir)

    out_img_filename = f"{base_name}_gt_topology.png"
    out_img_path = os.path.join(img_dir, out_img_filename)

    plt.tight_layout()
    plt.savefig(out_img_path, bbox_inches='tight', dpi=300)
    print(f"✅ Colored topology preview saved to: {out_img_path}")

    plt.close(fig)
    return "OK"


def build_graph_from_directory(dxf_dir=None):
    """Batch mode: Process all annotated DXF drawings in the specified directory and generate GT knowledge graphs one by one.

    Args:
        dxf_dir: Directory path containing annotated DXF files. When None, uses the
                 input_data/dxf_gt directory from configuration.
    """
    if dxf_dir is None:
        dxf_dir = str(settings.dxf_gt_dir)

    dxf_dir_path = Path(dxf_dir)
    if not dxf_dir_path.exists() or not dxf_dir_path.is_dir():
        print(f"❌ Invalid or missing directory: {dxf_dir}")
        return

    dxf_files = sorted(dxf_dir_path.glob('*.dxf'))
    if not dxf_files:
        print(f"🛑 No DXF files found in directory: {dxf_dir}")
        return

    total = len(dxf_files)
    print(f"🔍 Found {total} DXF files to process, starting automated batch GT creation...\n")

    ok_count = 0
    error_count = 0
    for i, dxf_file in enumerate(dxf_files, 1):
        print("\n" + "─" * 60)
        print(f"[{i}/{total}] Processing: {dxf_file.name}")
        print("─" * 60)
        try:
            status = build_graph_from_dxf(str(dxf_file))
        except Exception as e:
            print(f"  ⚠️ {dxf_file.name} crashed unexpectedly: {e}")
            traceback.print_exc()
            status = "ERROR"
        if status == "OK":
            ok_count += 1
        else:
            error_count += 1
            print(f"  ⚠️ {dxf_file.name} failed with status: {status}")

    print("\n" + "★" * 60)
    print("📊 Batch GT creation complete!")
    print(f"  Total: {total} | ✅ Success: {ok_count} | ❌ Errors: {error_count}")
    print("★" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Ground Truth Creator (BIM knowledge graph auto-construction)"
    )
    parser.add_argument(
        "--mode",
        choices=["SINGLE", "BATCH"],
        default="SINGLE",
        help="SINGLE: process one DXF interactively; BATCH: process all DXFs in a directory",
    )
    parser.add_argument(
        "--dir",
        default=None,
        help="DXF directory for BATCH mode (default: input_data/dxf_gt)",
    )
    args = parser.parse_args()

    if args.mode.upper() == "BATCH":
        build_graph_from_directory(args.dir)
    else:
        build_graph_from_dxf()
