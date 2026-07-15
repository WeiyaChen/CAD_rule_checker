import json
import os
import numpy as np
from shapely.wkt import loads as wkt_loads
from shapely.geometry import Polygon
from shapely.ops import unary_union
from sklearn.metrics import classification_report, accuracy_score, precision_recall_fscore_support
import re


class PipelineEvaluator:
    def __init__(self, ground_truth_data, system_output_data, system_violations,
                 gt_svg_path=None, sys_svg_path=None):
        self.gt_raw = ground_truth_data
        self.sys_out = system_output_data
        self.sys_violations = system_violations
        self.gt_svg_path = gt_svg_path      # 可选：GT SVG 路径，用于几何验证
        self.sys_svg_path = sys_svg_path    # 可选：系统输入 SVG 路径，用于几何验证

        # 内部标准化的系统输出与真实标注数据容器
        self.sys_nodes = {}
        self.gt_rooms = {}
        self.gt_edges = set()
        self.gt_violations = []

        # 核心映射字典：用于存储系统生成的 ID 与真实标注 ID 之间的对应关系
        self.sys_to_gt_map = {}
        self.gt_to_sys_map = {}
        self.mapping_done = False

        # 批量评估数据缓存
        self.iou_scores = []
        self.gt_status = {}
        self.topo_counts = (0, 0, 0)
        self.compliance_counts = (0, 0, 0)
        self.area_errors = []
        self.width_errors = []
        self.y_true = []
        self.y_pred = []

        # 在初始化阶段统一执行数据清洗与提取
        self._parse_ground_truth()
        self._parse_system_output()

    def debug_parsed_data(self):
        """Print parsed internal data structures for validation."""
        print("=" * 60)
        print("🛠️ [Debug] Data Parsing Validation")
        print("=" * 60)

        # 1. GT Room Data
        print("\n[1] Ground Truth (GT) Room Parsing Results:")
        print(f"  - Total rooms extracted: {len(self.gt_rooms)}")
        for i, (gt_id, info) in enumerate(list(self.gt_rooms.items())[:3]):
            wkt_short = info['wkt'][:50] + "..." if info['wkt'] else "None"
            print(f"    * ID: {gt_id}")
            print(f"      Semantic Type: {info['semantic_type']}")
            print(f"      Area: {info['area']}, ShortSide: {info['short_side']}")
            print(f"      WKT: {wkt_short}")
        if len(self.gt_rooms) > 3:
            print(f"    * ... (omitting {len(self.gt_rooms) - 3} rooms)")

        # 2. GT Topology Edges
        print(f"\n[2] Ground Truth (GT) Topology Edges:")
        print(f"  - Unique edges extracted: {len(self.gt_edges)}")
        for i, edge in enumerate(list(self.gt_edges)[:3]):
            print(f"    * Edge: {edge[0]} <---> {edge[1]}")
        if len(self.gt_edges) > 3:
            print(f"    * ... (omitting {len(self.gt_edges) - 3} edges)")

        # 3. System Output Nodes
        sys_spaces = {k: v for k, v in self.sys_nodes.items() if "bot:Space" in v.get("@type", [])}
        print(f"\n[3] System Output (Sys) Space Node Parsing Results:")
        print(f"  - Space nodes extracted: {len(sys_spaces)}")
        for i, (sys_id, node) in enumerate(list(sys_spaces.items())[:3]):
            wkt_val = node.get("geo:asWKT", "")
            wkt_short = wkt_val[:50] + "..." if wkt_val else "None"
            print(f"    * ID: {sys_id}")
            print(f"      Types: {node.get('@type')}")
            print(f"      Adjacencies (bot:adjacentZone): {node.get('bot:adjacentZone')}")
            print(f"      WKT: {wkt_short}")
        if len(sys_spaces) > 3:
            print(f"    * ... (omitting {len(sys_spaces) - 3} space nodes)")

        print("\n" + "=" * 60 + "\n")

    def _parse_system_output(self):
        """标准化解析系统输出的 JSON-LD 格式数据"""
        for node in self.sys_out.get("@graph", []):
            node_id = node.get("@id")
            if not node_id: continue

            # 1. 规范化 @type 为列表
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            node["@type"] = types

            # 2. 规范化 geo:asWKT，提取纯字符串
            wkt_val = node.get("geo:asWKT", "")
            if isinstance(wkt_val, dict):
                wkt_val = wkt_val.get("@value", "")
            node["geo:asWKT"] = wkt_val

            # 3. 规范化拓扑关联，提取 @id 列表
            adj_zones = node.get("bot:adjacentZone", [])
            if not isinstance(adj_zones, list):
                adj_zones = [adj_zones]
            clean_adjs = []
            for adj in adj_zones:
                if not adj: continue
                clean_adjs.append(adj.get("@id") if isinstance(adj, dict) else adj)
            node["bot:adjacentZone"] = clean_adjs

            self.sys_nodes[node_id] = node

    def _parse_ground_truth(self):
        """兼容解析标准 JSON-LD 格式或旧版简化草稿格式的 Ground Truth"""
        if "@graph" in self.gt_raw:
            # 解析标准 JSON-LD 格式
            for node in self.gt_raw["@graph"]:
                node_id = node.get("@id")
                types = node.get("@type", [])
                if isinstance(types, str): types = [types]

                # 提取房间信息
                if "bot:Space" in types:
                    wkt_val = node.get("geo:asWKT", "")
                    if isinstance(wkt_val, dict): wkt_val = wkt_val.get("@value", "")

                    # 提取语义类型
                    bldg_types = [t.replace("bldg:", "") for t in types if t.startswith("bldg:") and t != "bldg:Suite"]
                    sem_type = bldg_types[0] if bldg_types else "Unknown"

                    self.gt_rooms[node_id] = {
                        "wkt": wkt_val,
                        "area": node.get("props:hasArea"),
                        "short_side": node.get("props:hasShortSide"),
                        "semantic_type": sem_type
                    }

                    # 提取拓扑邻接关系
                    adj_zones = node.get("bot:adjacentZone", [])
                    if not isinstance(adj_zones, list): adj_zones = [adj_zones]
                    for adj in adj_zones:
                        if not adj: continue
                        adj_id = adj.get("@id") if isinstance(adj, dict) else adj
                        self.gt_edges.add(tuple(sorted([node_id, adj_id])))

            self.gt_violations = self.gt_raw.get("violations", [])
        else:
            # 兼容旧版简化草稿格式
            self.gt_rooms = self.gt_raw.get("rooms", {})
            for edge in self.gt_raw.get("adjacencies", []):
                if len(edge) == 2:
                    self.gt_edges.add(tuple(sorted([edge[0], edge[1]])))
            self.gt_violations = self.gt_raw.get("violations", [])

    # ==========================================
    # SVG 几何提取：从 SVG 文件中提取房间多边形
    # ==========================================
    def _extract_rooms_from_svg(self, svg_path):
        """
        使用系统管线从 SVG 文件提取房间多边形。
        返回: {room_id: {"wkt": str, "area": float, "semantic_type": str}, ...}
        """
        from src.io.svg_loader import load_svg
        from src.io.svg_parser import parse_svg

        tree, primitives = load_svg(str(svg_path))
        elements = parse_svg(tree, primitives)

        # 通过 TopologyBuilder 构建房间几何
        from src.topology.builder import TopologyBuilder
        import tempfile

        builder = TopologyBuilder()
        with tempfile.NamedTemporaryFile(suffix=".jsonld", delete=False, mode="w") as tmp:
            tmp_path = tmp.name
        try:
            builder.build(elements, tmp_path)
            import json
            with open(tmp_path, "r", encoding="utf-8") as f:
                graph_data = json.load(f)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

        rooms = {}
        for node in graph_data.get("@graph", []):
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if "bot:Space" not in types:
                continue

            node_id = node.get("@id")
            wkt_val = node.get("geo:asWKT", "")
            if isinstance(wkt_val, dict):
                wkt_val = wkt_val.get("@value", "")

            bldg_types = [t.replace("bldg:", "") for t in types
                          if t.startswith("bldg:") and t != "bldg:Suite"]
            sem_type = bldg_types[0] if bldg_types else "Unknown"

            rooms[node_id] = {
                "wkt": wkt_val,
                "area": node.get("props:hasArea"),
                "short_side": node.get("props:hasShortSide") or node.get("props:clearWidth"),
                "semantic_type": sem_type
            }
        return rooms

    # ==========================================
    # 实验一: 底层房间轮廓提取精度
    # ==========================================
    def evaluate_geometry_extraction(self):
        print("\n" + "=" * 50)
        print("📊 [Exp 1] Room Contour Extraction Accuracy (Geometry Extraction)")
        print("=" * 50)

        # ---- 可选：从 SVG 文件提取几何代替 JSON-LD 数据 ----
        svg_rooms_gt = None
        if self.gt_svg_path and os.path.exists(self.gt_svg_path):
            print(f"  [+] Loading GT geometry from SVG: {self.gt_svg_path}")
            svg_rooms_gt = self._extract_rooms_from_svg(self.gt_svg_path)

        svg_rooms_sys = None
        if self.sys_svg_path and os.path.exists(self.sys_svg_path):
            print(f"  [+] Loading system geometry from SVG: {self.sys_svg_path}")
            svg_rooms_sys = self._extract_rooms_from_svg(self.sys_svg_path)

        total_gt = len(self.gt_rooms)

        # 系统多边形来源：SVG 优先，否则用 JSON-LD
        sys_polys = {}
        if svg_rooms_sys:
            for node_id, info in svg_rooms_sys.items():
                try:
                    poly = wkt_loads(info["wkt"])
                    if poly.is_valid:
                        sys_polys[node_id] = poly
                except:
                    pass
        else:
            for node_id, node in self.sys_nodes.items():
                if "bot:Space" in node.get("@type", []) and node.get("geo:asWKT"):
                    try:
                        sys_polys[node_id] = wkt_loads(node["geo:asWKT"])
                    except:
                        pass

        # GT 多边形来源：SVG 优先，否则用 JSON-LD
        gt_polys = {}
        if svg_rooms_gt:
            for gt_id, info in svg_rooms_gt.items():
                try:
                    poly = wkt_loads(info["wkt"])
                    if poly.is_valid:
                        gt_polys[gt_id] = poly
                except:
                    pass
            total_gt = len(svg_rooms_gt)
        else:
            for gt_id, gt_info in self.gt_rooms.items():
                try:
                    wkt_str = gt_info.get("wkt", "")
                    if not wkt_str: continue
                    poly = wkt_loads(wkt_str)
                    if poly.is_valid:
                        gt_polys[gt_id] = poly
                except:
                    continue

        self.gt_status = {k: "unmatched" for k in gt_polys.keys()}
        sys_status = {k: "unmatched" for k in sys_polys.keys()}
        self.iou_scores = []

        # 1. 欠分割检测
        for sys_id, sys_poly in sys_polys.items():
            if not sys_poly.is_valid: continue

            fragments = []
            for gt_id, gt_poly in gt_polys.items():
                inter_area = sys_poly.intersection(gt_poly).area
                if gt_poly.area > 0 and (inter_area / gt_poly.area) > 0.8:
                    fragments.append(gt_id)

            if len(fragments) >= 2:
                sys_status[sys_id] = "under-segmented"
                for gid in fragments:
                    self.gt_status[gid] = "under-segmented"
                    self.gt_to_sys_map[gid] = sys_id

        # 2. 过分割检测
        for gt_id, gt_poly in gt_polys.items():
            if self.gt_status[gt_id] != "unmatched": continue

            fragments = []
            for sys_id, sys_poly in sys_polys.items():
                if sys_status[sys_id] != "unmatched" or not sys_poly.is_valid: continue

                inter_area = gt_poly.intersection(sys_poly).area
                if sys_poly.area > 0 and (inter_area / sys_poly.area) > 0.8:
                    fragments.append(sys_id)

            if len(fragments) >= 2:
                union_frag = unary_union([sys_polys[sid] for sid in fragments])
                if gt_poly.area > 0 and (gt_poly.intersection(union_frag).area / gt_poly.area) > 0.5:
                    self.gt_status[gt_id] = "over-segmented"
                    for sid in fragments:
                        sys_status[sid] = "part_of_over"
                        self.sys_to_gt_map[sid] = gt_id

        # 3. 一对一匹配
        for gt_id, gt_poly in gt_polys.items():
            if self.gt_status[gt_id] != "unmatched": continue

            best_iou = 0.0
            best_sys_id = None

            for sys_id, sys_poly in sys_polys.items():
                if sys_status[sys_id] != "unmatched" or not sys_poly.is_valid: continue

                inter_area = gt_poly.intersection(sys_poly).area
                union_area = gt_poly.union(sys_poly).area
                iou = inter_area / union_area if union_area > 0 else 0

                if iou > best_iou:
                    best_iou = iou
                    best_sys_id = sys_id

            if best_iou > 0.5 and best_sys_id is not None:
                self.gt_status[gt_id] = "1-to-1"
                sys_status[best_sys_id] = "1-to-1"
                self.iou_scores.append(best_iou)

                self.sys_to_gt_map[best_sys_id] = gt_id
                self.gt_to_sys_map[gt_id] = best_sys_id

        self.mapping_done = True

        # 4. 统计指标
        count_1to1 = sum(1 for v in self.gt_status.values() if v == "1-to-1")
        count_over = sum(1 for v in self.gt_status.values() if v == "over-segmented")
        count_under = sum(1 for v in self.gt_status.values() if v == "under-segmented")
        count_missed = sum(1 for v in self.gt_status.values() if v == "unmatched")

        rate_1to1 = count_1to1 / total_gt if total_gt > 0 else 0
        rate_over = count_over / total_gt if total_gt > 0 else 0
        rate_under = count_under / total_gt if total_gt > 0 else 0
        rate_miss = count_missed / total_gt if total_gt > 0 else 0

        mean_iou_1to1 = np.mean(self.iou_scores) if self.iou_scores else 0

        print(f"  [+] Total GT rooms: {total_gt}")
        print(f"  [+] 1-to-1 matches: {count_1to1}")
        print(f"  [+] Over-segmentation (1 GT split into N Sys): {count_over}")
        print(f"  [+] Under-segmentation (N GT merged into 1 Sys): {count_under}")
        print(f"  [+] Missed detections: {count_missed}")
        print("-" * 30)
        print(f"  [+] 1-to-1 Match Rate: {rate_1to1 * 100:.2f}%")
        print(f"  [+] Over-segmentation Rate: {rate_over * 100:.2f}%")
        print(f"  [+] Under-segmentation Rate: {rate_under * 100:.2f}%")
        print(f"  [+] Miss Rate: {rate_miss * 100:.2f}%")
        print(f"  [+] 1-to-1 mIoU: {mean_iou_1to1:.4f}")

        return rate_1to1, mean_iou_1to1

    # ==========================================
    # 实验二: 空间拓扑关系提取精度 (已修复严格限制版)
    # ==========================================
    def evaluate_topological_similarity(self, max_hops=1):
        print("\n" + "=" * 50)
        print(f"🕸️ [Exp 2] Spatial Topology Extraction Accuracy (Strict Reachability - N={max_hops})")
        print("=" * 50)

        from shapely.wkt import loads as wkt_loads
        from collections import defaultdict

        # 1. 提取所有有效几何多边形
        gt_polys = {}
        for gt_id, info in self.gt_rooms.items():
            try:
                wkt_str = info.get("wkt", "")
                if wkt_str:
                    poly = wkt_loads(wkt_str)
                    if poly.is_valid and not poly.is_empty:
                        gt_polys[gt_id] = poly
            except Exception:
                pass

        sys_polys = {}
        for sys_id, node in self.sys_nodes.items():
            wkt_val = node.get("geo:asWKT")
            if not wkt_val: continue
            wkt_str = wkt_val.get("@value", wkt_val) if isinstance(wkt_val, dict) else wkt_val
            try:
                poly = wkt_loads(wkt_str)
                if poly.is_valid and not poly.is_empty:
                    sys_polys[sys_id] = poly
            except Exception:
                pass

        # 2. 构建基于几何交集的多对多重叠映射 (Overlaps)
        gt_to_sys_group = defaultdict(list)
        sys_to_gt_group = defaultdict(list)

        for gt_id, gt_poly in gt_polys.items():
            for sys_id, sys_poly in sys_polys.items():
                try:
                    inter_area = gt_poly.intersection(sys_poly).area
                    # 【修复 1】: 将宽松的 10% 提升至 30%，过滤极小擦边碎片，拒绝让几何漏检的房间“强行复活”
                    if inter_area / min(gt_poly.area, sys_poly.area) > 0.3:
                        gt_to_sys_group[gt_id].append(sys_id)
                        sys_to_gt_group[sys_id].append(gt_id)
                except Exception:
                    pass

        # 3. 构建系统图的全局无向邻接表
        sys_graph = defaultdict(set)
        for sys_id, node in self.sys_nodes.items():
            adjs = node.get("bot:adjacentZone", [])
            if not isinstance(adjs, list): adjs = [adjs]
            for adj in adjs:
                adj_id = adj.get("@id") if isinstance(adj, dict) else adj
                sys_graph[sys_id].add(adj_id)
                sys_graph[adj_id].add(sys_id)

        def has_path(graph, start_id, target_id, max_depth):
            """受限深度的 BFS 寻路"""
            # 【修复 2】: 严惩欠分割。如果两个真实的相邻房间映射到了同一个系统碎片，
            # 说明系统把它们合并了，根本没有提取出两者之间的边界(门/墙洞)。因此直接判定为不连通 (FN)。
            if start_id == target_id:
                return False

            queue = [(start_id, 0)]
            visited = {start_id}
            while queue:
                curr, depth = queue.pop(0)
                if curr == target_id: return True
                if depth < max_depth:
                    for neighbor in graph.get(curr, []):
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append((neighbor, depth + 1))
            return False

        # 4. 计算 True Positives (TP) 与 False Negatives (FN)
        true_positives = 0
        false_negatives = 0
        gt_edges = self.gt_edges

        for gt_edge in gt_edges:
            gt_u, gt_v = gt_edge
            sys_u_list = gt_to_sys_group.get(gt_u, [])
            sys_v_list = gt_to_sys_group.get(gt_v, [])

            is_edge_found = False
            # 只要覆盖 U 的任意有效碎片与覆盖 V 的任意有效碎片能够严格连通，即判定为正确
            for su in sys_u_list:
                for sv in sys_v_list:
                    if has_path(sys_graph, su, sv, max_hops):
                        is_edge_found = True
                        break
                if is_edge_found: break

            if is_edge_found:
                true_positives += 1
            else:
                false_negatives += 1

        # 5. 计算 False Positives (FP)
        false_positives = 0
        # 遍历系统生成的所有边
        for su in sys_graph:
            for sv in sys_graph[su]:
                if su >= sv: continue  # 避免无向边重复计算

                is_valid_sys_edge = False
                gu_list = sys_to_gt_group.get(su, [])
                gv_list = sys_to_gt_group.get(sv, [])

                # 情形A: 两个碎片属于同一个真实房间 (这是过分割产生的内部连接，合理修复，不应算作拓扑误报)
                if set(gu_list).intersection(set(gv_list)):
                    is_valid_sys_edge = True
                else:
                    # 情形B: 两个碎片分属的真实房间在 GT 中确实是相连的
                    for gu in gu_list:
                        for gv in gv_list:
                            if tuple(sorted((gu, gv))) in gt_edges:
                                is_valid_sys_edge = True
                                break
                        if is_valid_sys_edge: break

                # 如果既不是内部缝合边，也不是真实的跨房间连通边，则判定为误报
                if not is_valid_sys_edge:
                    # 【修复 3附带效果】: 由于前面的映射阈值提高到了 0.3，噪声碎片变少，
                    # 欠分割区域的组合爆炸被抑制，FP 的识别会变得更加敏锐和准确。
                    if gu_list and gv_list:
                        false_positives += 1

        self.topo_counts = (true_positives, false_positives, false_negatives)

        precision = true_positives / (true_positives + false_positives) if (
                                                                                       true_positives + false_positives) > 0 else 0
        recall = true_positives / (true_positives + false_negatives) if (
                                                                                    true_positives + false_negatives) > 0 else 0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        print(f"  [+] GT topology edges: {len(gt_edges)}")
        print(f"  [+] Reachability-verified edges: {true_positives} (hops N={max_hops})")
        print(
            f"  [+] Correct (TP): {true_positives} | False Positive: {false_positives} | False Negative: {false_negatives}")
        print("-" * 30)
        print(f"  [+] Edge Precision: {precision * 100:.2f}%")
        print(f"  [+] Edge Recall: {recall * 100:.2f}%")
        print(f"  [+] Edge F1-Score: {f1 * 100:.2f}%")

        return precision, recall, f1

    # ==========================================
    # 实验三: 基础几何特征计算误差
    # ==========================================
    def evaluate_geometric_computation(self):
        print("\n" + "=" * 50)
        print("📐 [Exp 3] Geometric Computation Error")
        print("=" * 50)

        self.area_errors = []
        self.width_errors = []

        for gt_id, gt_info in self.gt_rooms.items():
            sys_id = self.gt_to_sys_map.get(gt_id)
            if not sys_id: continue

            sys_node = self.sys_nodes.get(sys_id)
            if not sys_node: continue

            sys_area = sys_node.get("props:hasArea")
            gt_area = gt_info.get("area")
            if sys_area is not None and gt_area is not None:
                self.area_errors.append(abs(sys_area - gt_area))

            sys_width = sys_node.get("props:hasShortSide")
            gt_width = gt_info.get("short_side")
            if sys_width is not None and gt_width is not None:
                self.width_errors.append(abs(sys_width - gt_width))

        mae_area = np.mean(self.area_errors) if self.area_errors else 0
        mae_width = np.mean(self.width_errors) if self.width_errors else 0

        print(f"  [+] Sample count: {len(self.area_errors)} rooms")
        print(f"  [+] MAE_Area: {mae_area:.4f} ㎡")
        print(f"  [+] MAE_Width: {mae_width:.4f} m")
        return mae_area, mae_width

    # ==========================================
    # Exp 4: LLM Semantic Reasoning & Error Cascade Analysis
    # ==========================================
    def evaluate_semantic_enrichment(self):
        print("\n" + "=" * 50)
        print("🧠 [Exp 4] LLM Semantic Reasoning & Error Cascade Analysis")
        print("=" * 50)

        self.y_true = []
        self.y_pred = []
        failed_samples = []

        for gt_id, gt_info in self.gt_rooms.items():
            gt_type = gt_info.get("semantic_type", "Unknown")
            self.y_true.append(gt_type)

            sys_id = self.gt_to_sys_map.get(gt_id)

            if not sys_id:
                self.y_pred.append("Unknown")
                failed_samples.append({
                    "gt_id": gt_id,
                    "true_label": gt_type,
                    "pred_label": "Unknown",
                    "reason": "Geometry Miss (底层几何漏检)"
                })
                continue

            sys_node = self.sys_nodes.get(sys_id, {})
            # 提取出系统对该空间推断出的所有有效功能标签
            bldg_types = [t.replace("bldg:", "") for t in sys_node.get("@type", []) if t.startswith("bldg:")]

            # 【核心修复】：兼容复合空间的命中逻辑
            # 如果人工标注的真值(GT)包含在模型预测的复合类型列表中，则视为分类正确
            if gt_type in bldg_types:
                sys_type = gt_type
            else:
                # 若未命中，优先取第一个作为错误预测的主类供统计分析
                sys_type = bldg_types[0] if bldg_types else "Unknown"

            self.y_pred.append(sys_type)

            if sys_type != gt_type:
                adj_zones = sys_node.get("bot:adjacentZone", [])
                topology_degree = len(adj_zones)

                if topology_degree == 0:
                    reason = "Topology Breakage (拓扑断链：失去邻接上下文)"
                else:
                    reason = "LLM Misunderstanding (大模型理解偏差/文本噪声)"

                failed_samples.append({
                    "sys_id": sys_id,
                    "true_label": gt_type,
                    "pred_label": sys_type,
                    "reason": reason
                })

        if not self.y_true:
            print("  [-] Insufficient samples for evaluation.")
            return None

        acc = accuracy_score(self.y_true, self.y_pred)
        precision, recall, f1, _ = precision_recall_fscore_support(self.y_true, self.y_pred, average='macro',
                                                                   zero_division=0)

        print(f"  [+] Accuracy: {acc:.4f}")
        print(f"  [+] Macro F1-Score: {f1:.4f}")

        print("\n  🔍 Error Cascade Analysis:")
        total_errors = len(failed_samples)
        if total_errors == 0:
            print("     ✅ Perfect prediction, zero errors!")
        else:
            geo_miss_count = sum(1 for s in failed_samples if "Geometry" in s["reason"])
            topo_break_count = sum(1 for s in failed_samples if "Topology" in s["reason"])
            llm_error_count = sum(1 for s in failed_samples if "LLM" in s["reason"])

            print(f"     Total {total_errors} semantic classification failures:")
            print(
                f"     ❌ Geometry miss (no semantics): {geo_miss_count} ({geo_miss_count / total_errors * 100:.1f}%)")
            print(
                f"     ❌ Topology breakage (missing context): {topo_break_count} ({topo_break_count / total_errors * 100:.1f}%)")
            print(
                f"     ❌ LLM misunderstanding: {llm_error_count} ({llm_error_count / total_errors * 100:.1f}%)")

        return acc, f1

    # ==========================================
    # Exp 5: SHACL Compliance Checking
    # ==========================================
    def evaluate_compliance_checking(self):
        print("\n" + "=" * 50)
        print("⚖️ [Exp 5] SHACL Compliance Checking")
        print("=" * 50)

        gt_set = set([(v["node_id"], v["rule"]) for v in self.gt_violations])

        sys_set = set()
        for v in self.sys_violations:
            sys_node_id = v["node_id"]
            gt_node_id = self.sys_to_gt_map.get(sys_node_id, sys_node_id)

            match = re.search(r'【违规 ([\d\.]+)】', v["message"])
            rule = match.group(1) if match else "Unknown"
            sys_set.add((gt_node_id, rule))

        true_positives = len(gt_set.intersection(sys_set))
        false_positives = len(sys_set - gt_set)
        false_negatives = len(gt_set - sys_set)

        self.compliance_counts = (true_positives, false_positives, false_negatives)

        precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
        recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

        print(f"  [+] GT total violations: {len(gt_set)}")
        print(f"  [+] System alerts: {len(sys_set)}")
        print(f"  [+] True Positives: {true_positives} | False Positives: {false_positives} | False Negatives: {false_negatives}")
        print("-" * 30)
        print(f"  [+] Precision: {precision * 100:.2f}%")
        print(f"  [+] Recall: {recall * 100:.2f}%")
        print(f"  [+] F1-Score: {f1 * 100:.2f}%")
        return precision, recall, f1

    def run_all(self):
        self.evaluate_geometry_extraction()
        self.evaluate_topological_similarity()
        self.evaluate_geometric_computation()
        self.evaluate_semantic_enrichment()
        self.evaluate_compliance_checking()
        print("\n🎉 All experiments complete! Results ready for paper tables.")

    # ==========================================
    # 面向 DatasetEvaluator 的批量数据提取接口
    # ==========================================
    def get_geometry_metrics(self):
        if not self.mapping_done:
            self.evaluate_geometry_extraction()
        rate_1to1 = sum(1 for v in self.gt_status.values() if v == "1-to-1") / len(
            self.gt_status) if self.gt_status else 0
        mean_iou = np.mean(self.iou_scores) if self.iou_scores else 0
        return rate_1to1, mean_iou, self.iou_scores

    def get_topology_raw_counts(self):
        if sum(self.topo_counts) == 0:
            self.evaluate_topological_similarity()
        return self.topo_counts

    def get_computation_errors(self):
        if not self.area_errors and not self.width_errors:
            self.evaluate_geometric_computation()
        return self.area_errors, self.width_errors

    def get_semantic_labels(self):
        if not self.y_true:
            self.evaluate_semantic_enrichment()
        return self.y_true, self.y_pred

    def get_compliance_raw_counts(self):
        if sum(self.compliance_counts) == 0:
            self.evaluate_compliance_checking()
        return self.compliance_counts


# =====================================================================
# CLI 入口：单文件评估（从配置文件读取路径）
# =====================================================================
if __name__ == "__main__":
    import sys

    from src.config.config import settings

    # 1. 从配置读取所有路径
    gt_jsonld_path = settings.eval_gt_jsonld
    sys_jsonld_path = settings.eval_sys_jsonld
    gt_svg_path = settings.eval_gt_svg
    sys_svg_path = settings.eval_sys_svg
    violations_path = settings.eval_violations_json

    # 2. 检查必填路径
    missing = []
    if not gt_jsonld_path or not os.path.exists(str(gt_jsonld_path)):
        missing.append(f"GT JSON-LD: {gt_jsonld_path or '(not configured)'}")
    if not sys_jsonld_path or not os.path.exists(str(sys_jsonld_path)):
        missing.append(f"System JSON-LD: {sys_jsonld_path or '(not configured)'}")

    if missing:
        print("❌ Missing required evaluation files. Please set in settings.yaml [evaluation]:")
        for m in missing:
            print(f"    - {m}")
        print("\n   Example configuration:")
        print('''  evaluation:
    gt_jsonld: "output/gt/nanyangmingmen150_gt.jsonld"
    sys_jsonld: "output/jsonld/nanyangmingmen150.jsonld"
    gt_svg: "output/processed/nanyangmingmen150_gt.svg"    # optional
    sys_svg: "input_data/svg/nanyangmingmen150.svg"              # optional
    violations_json: "output/violations/nanyangmingmen150_violations.json"  # optional''')
        sys.exit(1)

    # 3. Load ground truth
    with open(str(gt_jsonld_path), "r", encoding="utf-8") as f:
        ground_truth_data = json.load(f)
    print(f"  [+] Loaded GT JSON-LD from: {gt_jsonld_path}")

    # 4. Load system output
    with open(str(sys_jsonld_path), "r", encoding="utf-8") as f:
        system_output_data = json.load(f)
    print(f"  [+] Loaded system JSON-LD from: {sys_jsonld_path}")

    # 5. Load system violations (optional)
    system_violations = []
    if violations_path and os.path.exists(str(violations_path)):
        with open(str(violations_path), "r", encoding="utf-8") as f:
            system_violations = json.load(f)
        print(f"  [+] Loaded violations from: {violations_path}")
    else:
        print(f"  [-] Violations file not configured or not found, using empty list.")

    # 6. Summary
    print("=" * 50)
    print("📋 Evaluation Configuration:")
    print(f"  - GT JSON-LD:      {gt_jsonld_path}")
    print(f"  - System JSON-LD:  {sys_jsonld_path}")
    print(f"  - GT SVG:          {gt_svg_path or '(not provided)'}")
    print(f"  - System SVG:      {sys_svg_path or '(not provided)'}")
    print(f"  - Violations:      {violations_path or '(not provided)'}")
    print("=" * 50)

    # 7. Run evaluation
    evaluator = PipelineEvaluator(
        ground_truth_data, system_output_data, system_violations,
        gt_svg_path=str(gt_svg_path) if gt_svg_path else None,
        sys_svg_path=str(sys_svg_path) if sys_svg_path else None,
    )
    evaluator.run_all()