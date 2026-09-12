# src/spatial/primitives.py
"""边界图元准备：把原始墙体图元整理成轮廓算法的输入。

轮廓提取算法（CDT / RGP）约定的输入是"预测好的边界图元"——一组两点式
Shapely ``LineString``。本模块只负责把 CAD 图元清洗到这个形态：坐标取整、
去重、打断交点、缝合共线，与具体算法无关，因此所有轮廓算法共用同一条输入路径。

    from src.spatial.primitives import clean_lines

    boundary_primitives = clean_lines(wall_elements)
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge, unary_union

__all__ = ["clean_lines"]


def clean_lines(wall_elements, tolerance=0):
    """清洗墙体图元，返回两点式 ``LineString`` 列表（边界图元）。

    流程：坐标取整 → 去除连续重复点 → ``unary_union`` 打断交点并合并重叠 →
    ``linemerge`` 缝合首尾相接的线 → ``simplify`` 去掉共线中间点 → 拆成两点线段。

    Args:
        wall_elements: 原始墙体图元列表，每项需含 ``coords`` 字段。
        tolerance: ``simplify`` 的容差，0 表示仅移除绝对共线的点。
                   如果墙体有微小抖动，可以设为 1 (mm) 或 5 (mm)。
    """
    raw_lines = []

    # 1. 数据预处理 (坐标取整对 CAD 图纸去噪很有用)
    for el in wall_elements:
        coords = el.get('coords')
        if coords is None or len(coords) < 2:
            continue

        # 转换为整数坐标
        pts_arr = np.array(coords)
        int_pts = np.rint(pts_arr).astype(int)

        # 去除连续重复点 (比如 [A, A, B] -> [A, B])，防止生成长度为0的线
        # 使用 numpy 异或操作快速去重
        if len(int_pts) > 1:
            diff = int_pts[1:] != int_pts[:-1]
            mask = np.append([True], diff.any(axis=1))
            int_pts = int_pts[mask]

        if len(int_pts) < 2:
            continue

        geom = LineString(int_pts)
        if geom.length > 0 and geom.is_valid:
            raw_lines.append(geom)

    if not raw_lines:
        return []

    # 2. 几何并集 (处理重叠)
    try:
        # unary_union 会打断交叉点并合并重叠部分
        merged_geom = unary_union(raw_lines)
    except Exception as e:
        print(f"[Warning] unary_union failed: {e}")
        return raw_lines

    # 3. 拓扑缝合 (连接首尾相连的线)
    # linemerge 会尝试把碎片连成尽可能长的线
    merged_geom = linemerge(merged_geom)

    # 4. 结果提取与简化 (替代原来的 flatten 和 is_collinear)
    final_lines = []

    # 统一放入列表处理，不管它是 LineString 还是 MultiLineString
    if isinstance(merged_geom, LineString):
        geoms = [merged_geom]
    elif isinstance(merged_geom, MultiLineString):
        geoms = list(merged_geom.geoms)
    else:
        # 处理 GeometryCollection 等罕见情况
        geoms = [g for g in getattr(merged_geom, 'geoms', []) if isinstance(g, LineString)]

    for line in geoms:
        # simplify(0) 会自动移除共线的中间点
        # 例如: A->B->C (共线) 变成 A->C
        #      A->B->C (不共线) 保持 A->B->C
        simplified_line = line.simplify(tolerance, preserve_topology=True)

        # 轮廓算法要求所有 LineString 都是两点式，这里把简化后的折线拆开
        coords = list(simplified_line.coords)
        for i in range(len(coords) - 1):
            final_lines.append(LineString([coords[i], coords[i + 1]]))

    return final_lines