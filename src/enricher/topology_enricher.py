import json
import os
import sys
from collections import deque

from src.config.config import settings


class TopologyEnricher:
    def __init__(self, enriched_graph_dict):
        """
        初始化拓扑富化引擎（必须在大模型语义定性之后执行）
        """
        self.graph = enriched_graph_dict
        self.space_cache = {}
        self.doors_cache = {}
        self.public_spaces = set()
        self._build_cache()

    def _build_cache(self):
        """缓存所有的 Space 和 Door 节点以加速拓扑查询"""
        for node in self.graph.get("@graph", []):
            types = node.get("@type", [])
            if isinstance(types, str): types = [types]

            if "bot:Space" in types:
                self.space_cache[node.get("@id")] = node
            if "bot:Element" in types and "beo:Door" in types:
                self.doors_cache[node.get("@id")] = node

    def _get_room_semantics(self, room_id):
        """获取指定房间的语义标签（支持室外虚空节点的判断）"""
        if room_id == "inst:UnmodeledExterior":
            return {"Exterior"}

        node = self.space_cache.get(room_id, {})
        types = node.get("@type", [])
        if isinstance(types, str): types = [types]

        return {t.replace("bldg:", "") for t in types if t.startswith("bldg:") and t != "bldg:Suite"}

    def _get_min_topology_distance(self, start_node, target_semantics):
        """利用 BFS 寻找起点到任意目标语义集合的最短拓扑步数"""
        queue = deque([(start_node, 0)])
        visited = {start_node}
        while queue:
            curr, dist = queue.popleft()
            curr_sems = self._get_room_semantics(curr)

            if any(sem in target_semantics for sem in curr_sems):
                return dist

            curr_node = self.space_cache.get(curr, {})
            neighbors = curr_node.get("bot:adjacentZone", [])
            if not isinstance(neighbors, list):
                neighbors = [neighbors]

            for neighbor in neighbors:
                if not neighbor: continue
                n_id = neighbor.get("@id") if isinstance(neighbor, dict) else neighbor
                if n_id not in visited:
                    visited.add(n_id)
                    queue.append((n_id, dist + 1))
        return float('inf')

    def _infer_interior_door_type(self, connected_room_types):
        """基于相连空间推断内部门的具体类型"""
        if "Kitchen" in connected_room_types:
            return "bldg:KitchenDoor"
        if "Bathroom" in connected_room_types:
            return "bldg:BathroomDoor"
        if "Bedroom" in connected_room_types:
            return "bldg:BedroomDoor"
        return "bldg:InteriorDoor"

    def _infer_corridor_type(self, room_semantic, connected_room_types, connected_door_types):
        """基于相连房间与门推断过道的多重复合类型"""
        types = set()

        if room_semantic == "PublicCorridor":
            # 入户过道的判定：必须是外部公共过道，且连接了入户门
            if "bldg:EntranceDoor" in connected_door_types:
                types.add("bldg:EntranceCorridor")

        elif room_semantic == "Corridor":
            # 内部私有过道
            if "Bedroom" in connected_room_types or "LivingRoom" in connected_room_types:
                types.add("bldg:MainCorridor")
            if "Kitchen" in connected_room_types or "Bathroom" in connected_room_types:
                types.add("bldg:SecondaryCorridor")

            if not types:
                types.add("bldg:Corridor")

        return list(types)

    def _classify_public_spaces(self):
        """3.1 识别公共外部空间与内部走廊 (基于拓扑深度的公私裁决法)"""
        print("[TopologyEnricher] 开始基于拓扑深度裁决公私空间属性...")
        PUBLIC_SEEDS = {"ElevatorShaft", "Stairwell", "WaterRoom", "ElectricalRoom", "VentilationRoom", "EquipmentRoom",
                        "Exterior"}
        PRIVATE_SEEDS = {"Bedroom", "LivingRoom", "Kitchen", "Bathroom", "DiningRoom", "Cloakroom", "StudyRoom",
                         "Balcony", "Entrance"}

        # 1. 搜集图谱中天然的公共空间节点
        for r_id, node in self.space_cache.items():
            sems = self._get_room_semantics(r_id)
            if any(sem in PUBLIC_SEEDS for sem in sems):
                self.public_spaces.add(r_id)

        # 2. 裁决 Corridor 的公私属性
        for r_id, node in self.space_cache.items():
            sems = self._get_room_semantics(r_id)
            if "Corridor" in sems:
                dist_to_pub = self._get_min_topology_distance(r_id, PUBLIC_SEEDS)
                dist_to_priv = self._get_min_topology_distance(r_id, PRIVATE_SEEDS)

                # 距离公共区域更近，定性为 PublicCorridor
                if dist_to_pub <= dist_to_priv and dist_to_pub != float('inf'):
                    self.public_spaces.add(r_id)

                    types = node.get("@type", [])
                    if isinstance(types, str): types = [types]
                    if "bldg:PublicCorridor" not in types:
                        types.append("bldg:PublicCorridor")
                    node["@type"] = types

    def _enrich_doors(self):
        """3.2 门洞类型判定 (结合公私空间判定入户门)"""
        print("[TopologyEnricher] 开始基于公私边界定性门洞(Entrance/Interior)...")
        for d_id, door in self.doors_cache.items():
            interfaces = door.get("bot:interfaceOf", [])
            if not isinstance(interfaces, list): interfaces = [interfaces]

            conn_list = [ref.get("@id") if isinstance(ref, dict) else ref for ref in interfaces]

            connected_semantics = []
            for r_id in conn_list:
                connected_semantics.extend(list(self._get_room_semantics(r_id)))

            is_entrance = False
            # 门如果只连接了一个房间（外界缺失），视为通向外围的入户门
            if len(conn_list) < 2:
                is_entrance = True
            else:
                # 若门的连接两端跨越了公私边界（一端公一端私），即为入户门
                r1_pub = conn_list[0] in self.public_spaces or conn_list[0] == "inst:UnmodeledExterior"
                r2_pub = conn_list[1] in self.public_spaces or conn_list[1] == "inst:UnmodeledExterior"
                if r1_pub != r2_pub:
                    is_entrance = True

            if is_entrance:
                door_type = "bldg:EntranceDoor"
            else:
                door_type = self._infer_interior_door_type(connected_semantics)

            # 写入 JSON-LD 图谱属性
            types = door.get("@type", [])
            if isinstance(types, str): types = [types]
            if door_type not in types:
                types.append(door_type)
            door["@type"] = types

            clear_width = door.get("props:clearWidth", door.get("props:length", "未知"))
            width_str = f"{clear_width}m" if isinstance(clear_width, (int, float)) else "未知"
            print(f"  [+] 成功定性门洞 {d_id} -> {door_type} (净宽: {width_str})")

    def _enrich_corridors(self):
        """3.3 细化内部私有过道及公共过道类型"""
        print("[TopologyEnricher] 开始基于拓扑动线细化过道(Corridor)等级...")
        for r_id, room in self.space_cache.items():
            sems = self._get_room_semantics(r_id)

            if "Corridor" in sems or "PublicCorridor" in sems:
                room_semantic = "PublicCorridor" if "PublicCorridor" in sems else "Corridor"

                # 提取相连的房间类型
                neighbors = room.get("bot:adjacentZone", [])
                if not isinstance(neighbors, list): neighbors = [neighbors]
                neighbor_ids = [ref.get("@id") if isinstance(ref, dict) else ref for ref in neighbors]

                neighbor_room_types = []
                for n_id in neighbor_ids:
                    neighbor_room_types.extend(list(self._get_room_semantics(n_id)))

                # 提取与该过道相连的所有门的类型
                connected_door_types = []
                for d_id, door in self.doors_cache.items():
                    interfaces = door.get("bot:interfaceOf", [])
                    if not isinstance(interfaces, list): interfaces = [interfaces]
                    conn_list = [ref.get("@id") if isinstance(ref, dict) else ref for ref in interfaces]

                    if r_id in conn_list:
                        for t in door.get("@type", []):
                            if t.startswith("bldg:") and "Door" in t:
                                connected_door_types.append(t)

                # 推断复合类型
                composite_types = self._infer_corridor_type(room_semantic, neighbor_room_types, connected_door_types)

                if composite_types:
                    types = room.get("@type", [])
                    if isinstance(types, str): types = [types]
                    for ct in composite_types:
                        if ct not in types:
                            types.append(ct)
                    room["@type"] = types
                    print(f"  [+] 细化过道 {r_id} -> {composite_types}")

    def _check_bathroom_kitchen_doors(self):
        """3.4 硬核拓扑检查：精准识别卫生间的门是否直接开向厨房"""
        print("[TopologyEnricher] 开始严格审查卫生间-厨房连通拓扑...")
        for d_id, door in self.doors_cache.items():
            interfaces = door.get("bot:interfaceOf", [])
            if not isinstance(interfaces, list): interfaces = [interfaces]
            connected_room_ids = [ref.get("@id") if isinstance(ref, dict) else ref for ref in interfaces]

            if len(connected_room_ids) == 2:
                r1_sem = self._get_room_semantics(connected_room_ids[0])
                r2_sem = self._get_room_semantics(connected_room_ids[1])

                is_invalid = False
                if ("Bathroom" in r1_sem and "Kitchen" in r2_sem) or \
                        ("Kitchen" in r1_sem and "Bathroom" in r2_sem):
                    is_invalid = True

                if is_invalid:
                    bathroom_id = connected_room_ids[0] if "Bathroom" in r1_sem else connected_room_ids[1]
                    bathroom_node = self.space_cache.get(bathroom_id)

                    if bathroom_node:
                        bathroom_node["props:doorOpensIntoKitchen"] = True
                        print(f"  [-] 警报: 发现门洞 {d_id} 导致卫生间 {bathroom_id} 直接开向厨房！")

    def _assemble_suites(self):
        """3.5 广度优先搜索 (BFS) 识别独立套型 (Suite)，支持多入户门聚合"""
        print("[TopologyEnricher] 开始基于公共空间隔离的套型划分...")
        suites = []

        # 建立严格的公共隔离带黑名单（包含所有非套内私有空间）
        PUBLIC_BLOCKERS = {
            "ElevatorShaft", "Stairwell", "WaterRoom", "ElectricalRoom",
            "VentilationRoom", "EquipmentRoom", "PublicCorridor", "Unknown",
            "Exterior"
        }

        # 预处理：将所有公共空间以及无意义区域直接封锁，绝对不纳入套型聚合
        visited_rooms = set()
        for r_id, room in self.space_cache.items():
            sems = self._get_room_semantics(r_id)
            if not sems or any(sem in PUBLIC_BLOCKERS for sem in sems):
                visited_rooms.add(r_id)

        suite_counter = 1

        for r_id, room in self.space_cache.items():
            # 只有在完全属于私有空间（未被封锁）时，才将其作为新套型的种子
            if r_id not in visited_rooms:
                current_suite = []
                queue = deque([r_id])
                visited_rooms.add(r_id)

                while queue:
                    curr = queue.popleft()
                    current_suite.append(curr)

                    # 获取相邻节点 ID
                    curr_node = self.space_cache.get(curr, {})
                    adj_zones = curr_node.get("bot:adjacentZone", [])
                    if not isinstance(adj_zones, list): adj_zones = [adj_zones]
                    neighbors = [ref.get("@id") if isinstance(ref, dict) else ref for ref in adj_zones]

                    # 严格蔓延机制：仅允许在未被访问过的私有房间之间相互蔓延
                    for neighbor in neighbors:
                        if neighbor not in visited_rooms:
                            neighbor_sems = self._get_room_semantics(neighbor)
                            # 再次严苛校验其语义，确保没有任何公共区域被越权拉入
                            if neighbor_sems and not any(sem in PUBLIC_BLOCKERS for sem in neighbor_sems):
                                visited_rooms.add(neighbor)
                                queue.append(neighbor)

                if current_suite:
                    suite_id = f"inst:Suite_{suite_counter:02d}"
                    suites.append({
                        "@id": suite_id,
                        "@type": ["bot:Zone", "bldg:Suite"],
                        "bot:hasSpace": [{"@id": sid} for sid in current_suite]
                    })
                    print(f"  [+] 成功剥离出套型 {suite_id}，包含 {len(current_suite)} 个私有功能空间。")
                    suite_counter += 1

        if suites:
            self.graph.setdefault("@graph", []).extend(suites)

    def execute_enrichment(self):
        """统一执行拓扑图论推理"""
        print("\n" + "=" * 50)
        print("🚀 [TopologyEnricher] 拓扑动线富化引擎启动...")
        print("=" * 50)

        self._classify_public_spaces()
        self._enrich_doors()
        self._enrich_corridors()
        self._check_bathroom_kitchen_doors()
        self._assemble_suites()

        print("[TopologyEnricher] 拓扑富化与动线检查全部完成！\n")
        return self.graph


if __name__ == "__main__":
    # 测试代码
    target_file = os.path.join(settings.exp_jsonld_dir, "apartment_semantic_suites_geo.jsonld")
    if len(sys.argv) > 1:
        target_file = sys.argv[1]

    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8") as f:
            graph_data = json.load(f)

        topology_enricher = TopologyEnricher(graph_data)
        final_data = topology_enricher.execute_enrichment()

        out_file = target_file.replace(".json", "_topo.json")
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)
            print(f"[TopologyEnricher] 拓扑富化结果已保存至: {out_file}")
    else:
        print(f"[TopologyEnricher] 错误：找不到输入文件 {target_file}")