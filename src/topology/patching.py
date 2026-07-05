# src/topology/patching.py
import numpy as np
from shapely.geometry import MultiPoint, box


def create_patches(elements):
    """
    输入：门窗图元列表 (包含 instance_id)
    输出：每个门窗实例对应的几何补丁 (Polygon) 列表
    """
    # 1. 按 Instance ID 分组
    instances = {}
    for e in elements:
        iid = e['instance_id']
        if iid not in instances:
            instances[iid] = []
        instances[iid].extend(e['coords'])  # 收集坐标

    patches = []
    for iid, coords in instances.items():
        all_points = np.vstack(coords)

        # 策略 A: 轴对齐包围盒 (适合正交门)
        min_x, min_y = np.min(all_points, axis=0)
        max_x, max_y = np.max(all_points, axis=0)
        patch = box(min_x, min_y, max_x, max_y)

        # 策略 B: 凸包 (Convex Hull) - 更鲁棒，适合斜门、圆弧门
        # patch = MultiPoint(all_points).convex_hull

        patches.append(patch)

    return patches
