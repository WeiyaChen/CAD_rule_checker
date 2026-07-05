import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from shapely.wkt import loads as wkt_loads
from shapely.geometry import Polygon, MultiPolygon, LineString
import numpy as np

from src.config.config import settings


class JSONLDVisualizer:
    def __init__(self, jsonld_path):
        """
        初始化知识图谱可视化器
        :param jsonld_path: JSON-LD 文件的路径
        """
        self.jsonld_path = jsonld_path
        if not os.path.exists(jsonld_path):
            raise FileNotFoundError(f"找不到文件: {jsonld_path}")

        with open(jsonld_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

        self.nodes = self.data.get("@graph", [])

        # 数据缓存
        self.spaces = {}  # 存储房间信息
        self.doors = {}  # 存储门洞信息
        self.facilities = []  # 存储设施图元 (水槽、浴缸、灶具等)

        # 建筑语义配色表 (与 GT 可视化脚本保持高度一致)
        self.color_map = {
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


    def _extract_wkt(self, node):
        """安全提取节点的 WKT 几何字符串"""
        geo_wkt = node.get("geo:asWKT")
        if not geo_wkt:
            return None
        return geo_wkt.get("@value", geo_wkt) if isinstance(geo_wkt, dict) else geo_wkt

    def _extract_semantic_types(self, types):
        """提取建筑功能的所有标签，支持多重功能复合空间"""
        if isinstance(types, str): types = [types]
        sem_types = []
        for t in types:
            if t.startswith("bldg:") and "Door" not in t and t != "bldg:Suite":
                sem_types.append(t.replace("bldg:", ""))
        return sem_types if sem_types else ["Unknown"]

    def _extract_references(self, refs):
        """提取并展平关联节点 ID 列表"""
        if not isinstance(refs, list): refs = [refs]
        return [r.get("@id") if isinstance(r, dict) else r for r in refs if r]

    def parse_graph(self):
        """解析 JSON-LD 图谱数据，建立内存索引"""
        for node in self.nodes:
            node_id = node.get("@id")
            types = node.get("@type", [])
            if isinstance(types, str): types = [types]

            wkt_str = self._extract_wkt(node)
            if not wkt_str: continue

            try:
                geom = wkt_loads(wkt_str)
            except Exception as e:
                print(f"解析节点 {node_id} 的 WKT 失败: {e}")
                continue

            # 提取空间节点 (Space)
            if "bot:Space" in types:
                sem_types = self._extract_semantic_types(types)
                adjacencies = self._extract_references(node.get("bot:adjacentZone", []))

                self.spaces[node_id] = {
                    "geom": geom,
                    "types": sem_types,  # 存储所有标签列表
                    "label": node_id.split(":")[-1],
                    "adjacencies": adjacencies,
                    "area": node.get("props:hasArea", "N/A")
                }

            # 提取门洞节点 (Door)
            elif "beo:Door" in types:
                interfaces = self._extract_references(node.get("bot:interfaceOf", []))

                # 提取具体的门类型以分配颜色
                door_type = "InteriorDoor"
                for t in types:
                    if t.startswith("bldg:") and "Door" in t:
                        door_type = t.replace("bldg:", "")

                self.doors[node_id] = {
                    "geom": geom,
                    "interfaces": interfaces,
                    "door_type": door_type,
                    "clear_width": node.get("props:clearWidth")
                }

            # 提取内部设施节点 (Functional Elements)
            elif "beo:FunctionalElement" in types or any(t.startswith("beo:") and "Door" not in t for t in types):
                sem_type = "Unknown"
                for t in types:
                    if t.startswith("beo:") and t != "beo:FunctionalElement":
                        sem_type = t

                label = node.get("rdfs:label", sem_type.replace("beo:", ""))
                self.facilities.append({
                    "geom": geom,
                    "semantic": sem_type,
                    "label": label
                })

    def _plot_polygon(self, ax, geom, facecolor, edgecolor, alpha=0.5, zorder=1, lw=1):
        """辅助函数：绘制多边形实体 (与 GT 一致的参数风格)"""
        if geom.geom_type == 'Polygon':
            polys = [geom]
        elif geom.geom_type == 'MultiPolygon':
            polys = geom.geoms
        else:
            return

        for p in polys:
            x, y = p.exterior.xy
            ax.fill(x, y, alpha=alpha, fc=facecolor, ec=edgecolor, lw=lw, zorder=zorder)
            # 绘制内部空洞
            for interior in p.interiors:
                ix, iy = interior.xy
                ax.plot(ix, iy, color=edgecolor, linewidth=lw, zorder=zorder + 1, alpha=alpha)

    def draw(self, output_path):
        """绘制房间轮廓与拓扑关系图 (严格对齐 Ground Truth 风格)"""
        print(f"🎨 正在渲染图谱: {len(self.spaces)} 个空间, {len(self.doors)} 扇门, {len(self.facilities)} 个设施...")

        # 设置全局字体以支持中文
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Songti SC', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False

        fig, ax = plt.subplots(figsize=(10, 8), dpi=300)
        fig.patch.set_facecolor('#FFFFFF')

        # ====================================================
        # 1. 绘制房间轮廓及多重文字标签
        # ====================================================
        for s_id, space in self.spaces.items():
            geom = space["geom"]
            # 颜色获取：若为复合空间，优先使用第一个标签查询底色
            primary_type = space["types"][0] if space["types"] else "Unknown"

            # 使用 GT 风格：天然公共空间用灰色，私有空间用特定色彩兜底浅蓝
            fc_color = self.color_map.get(primary_type, "#ADD8E6")

            self._plot_polygon(ax, geom, facecolor=fc_color, edgecolor="black", alpha=0.5, zorder=1, lw=1)

            # 房间中心标注：动态拼接所有的功能类型，支持多标签展示
            centroid = geom.centroid
            types_str = space["types"][0]
            area_str = f"({space['area']}㎡)" if space['area'] != "N/A" else ""

            label_text = f"{types_str}\n{area_str}"
            ax.text(centroid.x, centroid.y, label_text,
                    ha='center', va='center', fontsize=12, fontweight='bold', color="#333333", zorder=10)

        # ====================================================
        # 2. 绘制门洞 (应用 GT 风格的入户/内部门分色)
        # ====================================================
        for d_id, door in self.doors.items():
            geom = door["geom"]
            is_entr = ("EntranceDoor" in door["door_type"])
            door_color = '#E74C3C' if is_entr else '#FAD7A1'
            edge_color = '#C0392B' if is_entr else '#E67E22'

            if geom.geom_type in ['Polygon', 'MultiPolygon']:
                self._plot_polygon(ax, geom, facecolor=door_color, edgecolor=edge_color, alpha=0.8, zorder=3, lw=2)
            elif geom.geom_type == 'LineString':
                x, y = geom.xy
                ax.plot(x, y, color=door_color, lw=3, zorder=3)

            # # 标注门洞净宽
            # clear_width = door.get("clear_width")
            # if clear_width:
            #     centroid = geom.centroid if geom.geom_type in ['Polygon', 'MultiPolygon'] else geom.interpolate(0.5,
            #                                                                                                     normalized=True)
            #     ax.text(centroid.x, centroid.y, f"W:{clear_width}m",
            #             ha='center', va='center', fontsize=7, color='red', zorder=11)

        # # ====================================================
        # # 3. 绘制挂载的设施图元质心
        # # ====================================================
        # for fac in self.facilities:
        #     geom = fac["geom"]
        #     centroid = geom.centroid
        #     cx, cy = centroid.x, centroid.y
        #     f_label = fac["label"].lower()
        #
        #     # 依据语义分类标记不同形状和颜色 (只绘制指定的四种设施)
        #     if "sink" in f_label:
        #         marker, color = 'v', 'blue'
        #     elif "bath" in f_label:
        #         marker, color = 's', 'cyan'
        #     elif "gas" in f_label or "stove" in f_label:
        #         marker, color = '^', 'red'
        #     elif "toilet" in f_label:
        #         marker, color = 'o', '#8B4513'  # 使用明显的棕色圆点
        #     else:
        #         continue  # 忽略其他设施
        #
        #     ax.scatter(cx, cy, marker=marker, color=color, s=50, edgecolors='black', zorder=5)
        #     # 添加微小偏移量防止文字重叠
        #     ax.text(cx, cy + (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.015, fac["label"],
        #             fontsize=6, ha='center', color='darkblue', zorder=6)

        # ====================================================
        # 4. 差异化绘制拓扑连通关系 (绿虚线 vs 蓝实线)
        # ====================================================
        door_edges = set()

        # 4.1 绘制门桥接关系 (绿色虚线加粗)
        for d_id, door in self.doors.items():
            interfaces = door["interfaces"]
            if len(interfaces) == 2:
                id1, id2 = interfaces[0], interfaces[1]
                edge_key = tuple(sorted([id1, id2]))
                door_edges.add(edge_key)

                if id1 in self.spaces and id2 in self.spaces:
                    p1 = self.spaces[id1]["geom"].centroid
                    p2 = self.spaces[id2]["geom"].centroid
                    ax.plot([p1.x, p2.x], [p1.y, p2.y],  'g--', color='#27AE60', lw=2.0, alpha=0.8, zorder=6)

        # 4.2 绘制边界直接重合关系 (蓝色实线带透明度)
        drawn_adj_edges = set()
        for s_id, space in self.spaces.items():
            p1 = space["geom"].centroid
            for adj_id in space["adjacencies"]:
                edge_key = tuple(sorted([s_id, adj_id]))

                if edge_key not in drawn_adj_edges and edge_key not in door_edges:
                    drawn_adj_edges.add(edge_key)
                    if adj_id in self.spaces:
                        p2 = self.spaces[adj_id]["geom"].centroid
                        ax.plot([p1.x, p2.x], [p1.y, p2.y], color='#2980B9', linestyle='-', lw=1.5, alpha=0.4, zorder=5)

        ax.set_aspect('equal')
        plt.title("全局拓扑语义解析预览 (System Output)", pad=15, fontsize=14)
        plt.axis('off')

        plt.tight_layout()
        save_dest = Path(output_path)
        # 确保父目录存在，不存在则自动创建
        save_dest.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_dest, bbox_inches='tight')
        print(f"✅ 可视化结果已对齐保存至: {save_dest}")


if __name__ == "__main__":
    # 使用示例
    # 请将此处替换为您的 JSON-LD 文件路径
    TARGET_JSONLD = os.path.join(settings.exp_jsonld_dir, "北京保利140+135.jsonld")

    # 确保输出目录存在
    os.makedirs(settings.exp_viz_dir, exist_ok=True)

    if os.path.exists(TARGET_JSONLD):
        visualizer = JSONLDVisualizer(TARGET_JSONLD)
        visualizer.parse_graph()
        visualizer.draw("北京保利140+135.png")
    else:
        print(f"❌ 找不到输入文件: {TARGET_JSONLD}")