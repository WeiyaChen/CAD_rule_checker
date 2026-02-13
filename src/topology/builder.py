# src/topology/builder.py
import os
from collections import defaultdict

import cv2
from matplotlib import pyplot as plt
from matplotlib.collections import LineCollection
from shapely import Polygon, wkt

from .bot_builder import BotGraphGenerator
from .generate_virtual_wall import FloorPlanMeshBuilder
from .preprocessing import clean_lines
from .patching import create_patches
from ..utils.graph_viz import BotGraphVisualizer
from ..utils.visualize import plot_floor_plan
from src.config.config import settings


# 1. 定义构件类 (保持不变)
class Component:
    def __init__(self, uid, category, specific_type, geometry, properties=None):
        self.uid = uid
        self.category = category
        self.specific_type = specific_type
        self.geometry = geometry
        self.properties = properties if properties else {}
        self.parent_room = None


# 辅助函数：计算一组图元的整体包围盒或几何并集
def aggregate_geometry(sub_elements):
    """
    不依赖 create_patches，直接从原始图元中提取坐标计算 AABB 包围盒。

    Args:
        sub_elements: 包含多个图元字典的列表，例如:
                      [{'type': 'line', 'coords': [[0,0], [1,1]]}, ...]

    Returns:
        list: 包含矩形四个顶点的列表 [[min_x, min_y], [max_x, min_y], ...]
              如果是无效数据则返回 None
    """
    all_x = []
    all_y = []

    # 1. 遍历该组内的每一个图元（门框、门扇、圆弧等）
    for element in sub_elements:
        # 获取原始坐标列表，通常格式为 [[x1, y1], [x2, y2], ...]
        coords = element.get('coords', [])

        if len(coords) == 0:
            continue

        # 2. 提取所有点的 x 和 y 坐标
        # 注意：这里假设 coords 是二维点列表。
        # 如果 coords 是扁平列表 [x1, y1, x2, y2]，需要先 reshape，或者步进读取
        for point in coords:
            all_x.append(point[0])
            all_y.append(point[1])

    # 3. 边界检查
    if not all_x or not all_y:
        return None

    # 4. 计算极值 (Min/Max)
    min_x = int(round(min(all_x)))
    max_x = int(round(max(all_x)))
    min_y = int(round(min(all_y)))
    max_y = int(round(max(all_y)))

    # 5. 构造逆时针方向的闭合矩形 (CDT 约束边)
    # 顺序：左下 -> 右下 -> 右上 -> 左上
    aabb_box = [
        (min_x, min_y),  # Bottom-Left
        (max_x, min_y),  # Bottom-Right
        (max_x, max_y),  # Top-Right
        (min_x, max_y)  # Top-Left
    ]

    return aabb_box


# --- 3. 核心处理函数：聚合与实例化 ---
def process_compound_instances(raw_elements, target_category):
    """
    将离散图元按 instance_id 聚合并封装为 Component 对象
    """
    # A. 分组 (Grouping)
    grouped = defaultdict(list)
    for e in raw_elements:
        # 必须有 instance_id 才能聚合，否则作为噪声丢弃或作为独立物体处理
        if 'instance_id' in e:
            grouped[e['instance_id']].append(e)

    instances = []

    # B. 实例化 (Instantiation)
    for iid, subs in grouped.items():
        # 1. 计算融合几何 (AABB)
        unified_geom = aggregate_geometry(subs)
        if not unified_geom: continue

        # 2. 确定代表性类型 (优先取非line的类型)
        # 简单策略：取出现次数最多的类型，或优先取 'panel'/'leaf'
        raw_types = [e['type'] for e in subs]
        specific_type = raw_types[0]  # 简化处理，取第一个作为具体类型

        # 3. 计算属性 (简单计算长宽)
        a = max(p[0] for p in unified_geom) - min(p[0] for p in unified_geom)
        b = max(p[1] for p in unified_geom) - min(p[1] for p in unified_geom)
        length = int(max(a, b))
        width = int(min(a, b))

        # 4. 创建对象
        comp = Component(
            uid=f"{target_category.upper()}_{iid}",
            category=target_category,
            specific_type=specific_type,
            geometry=unified_geom,
            properties={"length": length, "width": width}
        )
        instances.append(comp)

    return instances


class TopologyBuilder:
    def __init__(self):
        pass

    def build(self, raw_elements):
        """
        Main pipeline: Elements -> FloorPlan Object
        """

        # 墙线的预处理 (可选：简单的线段合并)
        walls = [e for e in raw_elements if 'wall' in e['type']]
        clean_walls = clean_lines(walls)

        # 提取并合并门
        raw_doors = [e for e in raw_elements if 'door' in e['type']]
        door_objs = process_compound_instances(raw_doors, target_category="Door")

        # 提取合并窗
        raw_windows = [e for e in raw_elements if 'window' in e['type'] or 'opening' in e['type']]
        window_objs = process_compound_instances(raw_windows, target_category="Window")

        # 提取合并家具
        raw_furn = [
            e for e in raw_elements
            if "wall" not in e['type']
               and "door" not in e['type']
               and "window" not in e['type']
               and "opening" not in e['type']
               and e['type'] != "text"
        ]
        furn_objs = process_compound_instances(raw_furn, target_category="Furniture")

        # patches提取
        # 正确写法 (转为 Shapely 对象):
        door_patches = []
        for d in door_objs:
            if d.geometry:
                try:
                    door_patches.append(Polygon(d.geometry))
                except Exception as e:
                    print(f"Invalid geometry for Door {d.uid}: {e}")

        window_patches = []
        for w in window_objs:
            if w.geometry:
                try:
                    window_patches.append(Polygon(w.geometry))
                except Exception as e:
                    print(f"Invalid geometry for Window {w.uid}: {e}")

        # 生成房间种子
        rooms = [e for e in raw_elements if e['type'] == 'text']
        room_tags = []
        for room in rooms:
            content = room.get('text')
            cord = room.get('coords')
            room_tag = (content, (cord[0], cord[1]))
            room_tags.append(room_tag)

        # 构建房间轮廓
        builder = FloorPlanMeshBuilder()  # 容差设小点，测试长窗户是否能通过
        room_results = builder.build(clean_walls, door_patches, window_patches, room_tags)

        # 调用可视化
        plot_floor_plan(builder, room_results)

        # bot构建
        comps = door_objs + window_objs + furn_objs
        generator = BotGraphGenerator(room_results, comps)
        json_output = generator.generate()
        # 实例化可视化工具
        viz = BotGraphVisualizer(json_output)

        # 1. 保存数据
        viz.save_json(os.path.join(settings.output_jsonld_dir, "floorplan.jsonld"))

        # 2. 画拓扑关系 (圆圈图) -> 验证逻辑连接
        viz.draw_topology(os.path.join(settings.output_html_dir, "topology.html"))


        return room_results
