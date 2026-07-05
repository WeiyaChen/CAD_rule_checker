import json
import os
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from shapely import wkt
from pyvis.network import Network


class BotGraphVisualizer:
    def __init__(self, json_ld_data):
        self.data = json_ld_data
        self.G = nx.Graph()
        self._build_topology_graph()

    def _build_topology_graph(self):
        """(原有逻辑) 构建拓扑关系图"""
        graph_list = self.data.get("@graph", [])
        for item in graph_list:
            node_id = item["@id"]
            node_type = item["@type"]
            label = item.get("rdfs:label", node_id)

            # 简化标签，去掉 uri 前缀
            short_label = label.split(":")[-1] if ":" in label else label

            if "bot:Space" in node_type:
                self.G.add_node(node_id, label=short_label, group="Room", color="#97C2FC")
            elif "bot:Element" in node_type:
                # 只有当它是接口时才作为拓扑节点显示
                if "bot:interfaceOf" in item:
                    self.G.add_node(node_id, label="Door", group="Door", color="#FBAD50")

        # 添加边
        for item in graph_list:
            src = item["@id"]
            if "bot:adjacentZone" in item:
                targets = item["bot:adjacentZone"]
                if not isinstance(targets, list): targets = [targets]
                for t in targets:
                    self.G.add_edge(src, t["@id"], type="adjacent", color="gray")

            if "bot:interfaceOf" in item:
                targets = item["bot:interfaceOf"]
                if not isinstance(targets, list): targets = [targets]
                for t in targets:
                    self.G.add_edge(src, t["@id"], type="interface", color="orange")

    def _parse_wkt(self, wkt_obj):
        """辅助函数：解析 WKT 数据（兼容字符串或字典格式）"""
        if isinstance(wkt_obj, dict):
            raw_wkt = wkt_obj.get("@value", "")
        else:
            raw_wkt = str(wkt_obj)

        try:
            return wkt.loads(raw_wkt)
        except Exception as e:
            print(f"⚠️ WKT 解析失败: {e}")
            return None

    def save_json(self, filepath):
        folder = os.path.dirname(filepath)
        if folder and not os.path.exists(folder):
            os.makedirs(folder)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        print(f"✅ 知识图谱 JSON 已保存: {filepath}")

    def draw_topology(self, filepath="output/topology_view.html"):
        """画拓扑结构图 (圆圈连线)"""
        folder = os.path.dirname(filepath)
        if folder and not os.path.exists(folder): os.makedirs(folder)

        net = Network(height="600px", width="100%", bgcolor="#ffffff", notebook=False)
        net.from_nx(self.G)
        net.toggle_physics(True)
        net.save_graph(filepath)
        print(f"✅ 拓扑结构图已生成: {filepath}")
