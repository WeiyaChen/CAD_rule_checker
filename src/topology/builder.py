# src/topology/builder.py
import math
import os
from collections import defaultdict
from pathlib import Path

import cv2
from matplotlib import pyplot as plt
from matplotlib.collections import LineCollection
from shapely import Polygon, wkt, LineString, MultiPoint, Point, STRtree

from .bot_builder import BotGraphGenerator
from .generate_virtual_wall import FloorPlanMeshBuilderCDT
from .preprocessing import clean_lines
from .patching import create_patches
from ..utils.cdt_viz import plot_floor_plan
from ..utils.graph_viz import BotGraphVisualizer
from src.config.config import settings
from src.config.labels import get_wall, get_window, get_door


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


def process_compound_instances(raw_elements, target_category):
    """
    第一步：将离散图元按 instance_id 聚合并封装为具备 MRR 几何特征的 Component 对象
    """
    # A. 分组 (Grouping)
    grouped = defaultdict(list)
    for e in raw_elements:
        # 必须有 instance_id 才能聚合，否则作为噪声丢弃或作为独立物体处理
        if 'instance_id' in e:
            iid = e['instance_id']
            # 坚决拦截 -1（不论它是数字类型还是字符串类型）
            if str(iid) == "-1" or iid == -1:
                continue
            grouped[iid].append(e)

    instances = []
    for iid, subs in grouped.items():
        # 1. 收集该实例下所有碎片的顶点以计算融合几何
        all_points = []
        for sub in subs:
            # 假设每个图元具有 'points' 或 'coords' 属性
            pts = sub.get('points', sub.get('coords', []))
            all_points.extend(pts)

        if not all_points:
            continue

        # 2. 计算常规包围盒 (Axis-Aligned Bounding Box / OBB)
        obb_poly = MultiPoint(all_points).envelope

        # 【核心修复】：防止几何退化导致下游 Polygon() 初始化失败
        # 如果点集完全共线或重合导致退化为线/点，则施加极小的缓冲使其成为合法的多边形
        if obb_poly.geom_type in ['LineString', 'Point']:
            obb_poly = obb_poly.buffer(1.0).envelope

        # 此时 obb_poly 必定是合法的 Polygon
        if obb_poly.geom_type == 'Polygon':
            # 提取外接矩形的 5 个顶点坐标（首尾重合以闭合）
            unified_geom = list(obb_poly.exterior.coords)
            if len(unified_geom) >= 3:
                side1 = math.dist(unified_geom[0], unified_geom[1])
                side2 = math.dist(unified_geom[1], unified_geom[2])
                length = int(max(side1, side2))
                width = int(min(side1, side2))
            else:
                length, width = 0, 0
        else:
            continue

        # 3. 确定代表性类型 (优先取非line的类型)
        raw_types = [e['type'] for e in subs]
        specific_type = raw_types[0]  # 简化处理，取第一个作为具体类型

        # 5. 创建 Component 对象
        comp = Component(
            uid=f"{target_category.upper()}_{iid}",
            category=target_category,
            specific_type=specific_type,
            geometry=unified_geom,  # 这里保存的是完整的 MRR 矩形顶点序列
            properties={"length": length, "width": width}
        )

        instances.append(comp)

    return instances


def decompose_components_to_segments(components):
    """
    第二步：读取 Component 对象列表，将其 geometry (矩形轮廓) 拆分为独立的线段元素列表
    """
    decomposed_elements = []

    for comp in components:
        coords = comp.geometry
        # MRR 外部轮廓通常有 5 个点（首尾重合），形成 4 条边
        if not coords or len(coords) < 2:
            continue

        # 尝试从 UID 中恢复纯数字的 instance_id，若失败则回退为 UID 字符串
        try:
            original_iid = int(comp.uid.split('_')[-1])
        except (ValueError, IndexError):
            original_iid = comp.uid

        # 遍历顶点序列，每相邻两个点提取为一条线段
        for i in range(len(coords) - 1):
            p1 = coords[i]
            p2 = coords[i + 1]

            # 构造新的二元线段元素 (Element 字典格式)
            segment_element = {
                'type': 'line',  # 拆分后几何属性严格变为线
                'instance_id': original_iid,
                'semantic_label': comp.category,
                'text': None,  # 线段无文本
                'coords': [list(p1), list(p2)]  # 仅保存该线段的两个端点
            }
            decomposed_elements.append(segment_element)

    return decomposed_elements


class TopologyBuilder:
    def __init__(self):
        pass

    def build(self, raw_elements, json_output_path):
        """
        Main pipeline: Elements -> FloorPlan Object
        """
        walls = [e for e in raw_elements if e['type'] in get_wall()]  # 找到边界图元图元
        clean_walls = clean_lines(walls)

        # 提取并合并门
        raw_doors = [e for e in raw_elements if e['type'] in get_door()]
        door_objs = process_compound_instances(raw_doors, target_category="Door")

        # 提取合并窗
        raw_windows = [e for e in raw_elements if e['type'] in get_window()]
        window_objs = process_compound_instances(raw_windows, target_category="Window")

        # 提取合并家具
        raw_furn = [
            e for e in raw_elements
            if e['type'] not in get_wall()
               and e['type'] not in get_door()
               and e['type'] != "text"
        ]
        fun_objs = process_compound_instances(raw_furn, target_category="FunctionalElement")

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

        # 生成房间标签列表
        rooms = [e for e in raw_elements if e['type'] == 'text']
        room_tags = []
        for room in rooms:
            content = room.get('text')
            cord = room.get('coords')
            room_tag = (content, (cord[0], cord[1]))
            room_tags.append(room_tag)

        # 构建房间轮廓，使用CDT算法
        builder = FloorPlanMeshBuilderCDT()
        room_results = builder.new_build(clean_walls, door_patches, window_patches, room_tags)

        # 调用可视化
        save_dir = str(settings.cdt_dir)
        filename = os.path.basename(json_output_path).replace("_raw.jsonld", ".png")
        plot_floor_plan(builder, room_results, save_dir, filename)

        # bot构建
        comps = door_objs + window_objs + fun_objs
        generator = BotGraphGenerator(room_results, comps)
        json_output = generator.generate()
        # 实例化可视化工具
        viz = BotGraphVisualizer(json_output)
        viz.save_json(json_output_path)
