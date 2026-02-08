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

    def save_json(self, filepath="output/floorplan_kg.jsonld"):
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

    def draw_geometry(self, filepath="output/geometry_view.png"):
        """
        可视化几何信息：绘制房间轮廓 + 门窗包围盒
        """
        # 1. 创建画布
        fig, ax = plt.subplots(figsize=(12, 12))  # 创建一个正方形画布

        # 2. 定义样式配置 (Style Configuration)
        # alpha: 透明度, zorder: 图层层级 (越大越靠上)
        styles = {
            "Room": {
                "facecolor": "#E6F3FF",  # 浅蓝色填充
                "edgecolor": "#4F81BD",  # 深蓝色边框
                "alpha": 0.6,  # 稍微透明，方便看重叠
                "linewidth": 2,
                "zorder": 1  # 最底层
            },
            "Door": {
                "facecolor": "#FFEBCC",  # 浅橙色填充
                "edgecolor": "#FF9900",  # 深橙色边框 (强调)
                "alpha": 0.9,  # 不透明，强调显示
                "linewidth": 2,
                "zorder": 10  # 放在最上层！
            },
            "Window": {
                "facecolor": "#CCFFFF",  # 浅青色填充
                "edgecolor": "#00CCFF",  # 深青色边框
                "alpha": 0.9,
                "linewidth": 2,
                "zorder": 10  # 放在最上层！
            }
        }

        # 用于自动调整视野范围
        all_geoms = []

        graph_list = self.data.get("@graph", [])

        # 3. 遍历节点并绘图
        for item in graph_list:
            # 跳过没有几何信息的节点
            if "props:geometryWKT" not in item:
                continue

            # 解析 WKT
            wkt_data = item["props:geometryWKT"]
            # 兼容处理：有些 JSON-LD 可能是 {"@value": "..."} 格式，有些直接是字符串
            wkt_str = wkt_data.get("@value") if isinstance(wkt_data, dict) else wkt_data

            try:
                geom = wkt.loads(wkt_str)
            except Exception:
                continue  # 解析失败则跳过

            if geom.is_empty:
                continue

            all_geoms.append(geom)

            # 4. 判断类型并获取样式
            node_type = item.get("@type", [])
            # 转换为字符串列表方便判断
            types_str = str(node_type)

            current_style = None
            label_text = None

            if "bot:Space" in types_str:
                current_style = styles["Room"]
                # 提取房间名称用于标注 (例如 "LivingRoom_0" -> "LivingRoom")
                raw_label = item.get("rdfs:label", "")
                label_text = raw_label.split("_")[0] if "_" in raw_label else raw_label

            elif "Door" in types_str:  # 覆盖 beo:Door 或自定义 Door
                current_style = styles["Door"]

            elif "Window" in types_str:  # 覆盖 beo:Window 或自定义 Window
                current_style = styles["Window"]

            # 如果不是我们关心的类型（如家具），可以选择跳过或给个默认灰色
            if current_style is None:
                continue

            # 5. 绘制多边形 (Polygon Patch)
            if geom.geom_type == 'Polygon':
                x, y = geom.exterior.xy
                patch = mpatches.Polygon(
                    list(zip(x, y)),
                    closed=True,
                    facecolor=current_style["facecolor"],
                    edgecolor=current_style["edgecolor"],
                    alpha=current_style["alpha"],
                    linewidth=current_style["linewidth"],
                    zorder=current_style["zorder"]
                )
                ax.add_patch(patch)

                # 如果是房间，在中心画文字
                if label_text:
                    cx, cy = geom.centroid.x, geom.centroid.y
                    ax.text(cx, cy, label_text,
                            ha='center', va='center', fontsize=10,
                            fontweight='bold', color='#333333', zorder=5)

        # 6. 自动调整坐标轴范围 (Auto-scale)
        if all_geoms:
            # 收集所有几何体的边界
            min_x = min(g.bounds[0] for g in all_geoms)
            min_y = min(g.bounds[1] for g in all_geoms)
            max_x = max(g.bounds[2] for g in all_geoms)
            max_y = max(g.bounds[3] for g in all_geoms)

            # 设置范围并留出一点边距 (Margin)
            margin = 500  # 假设单位是mm
            ax.set_xlim(min_x - margin, max_x + margin)
            ax.set_ylim(min_y - margin, max_y + margin)

            # 关键：强制等比例显示，防止房子被拉伸变形
            ax.set_aspect('equal')

            # 翻转Y轴（可选）：计算机视觉中通常(0,0)在左上，如果你的图倒了，取消注释下面这行
            # ax.invert_yaxis()

            plt.title("Geometric Reconstruction (Rooms & Components)", fontsize=14)
            plt.axis('off')  # 隐藏坐标轴刻度

            # 保存
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            print(f"✅ 几何可视化图已保存至: {filepath}")
            plt.show()
        else:
            print("⚠️ 未找到有效的几何数据，无法绘图。")