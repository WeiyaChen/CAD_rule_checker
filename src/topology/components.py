# src/topology/components.py
"""构件聚合：把离散图元按 ``instance_id`` 聚合成构件（Component）。

门窗、家具实例在 SVG 里往往由多个碎图元（门框、门扇、圆弧…）组成；本模块把它们
合成一个构件并给出 MRR / AABB 几何。结果同时供两处使用：

* 轮廓提取算法的门窗补丁（``door_patches`` / ``window_patches``）；
* 拓扑图构建（:class:`~src.topology.bot_builder.BotGraphGenerator`）。

本模块由 :mod:`src.topology.builder` 拆出，使 builder 只负责任务编排。
"""

from __future__ import annotations

import math
from collections import defaultdict

from shapely import MultiPoint

__all__ = [
    "Component",
    "process_compound_instances",
]


# 1. 定义构件类 (保持不变)
class Component:
    def __init__(self, uid, category, specific_type, geometry, properties=None):
        self.uid = uid
        self.category = category
        self.specific_type = specific_type
        self.geometry = geometry
        self.properties = properties if properties else {}
        self.parent_room = None


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
