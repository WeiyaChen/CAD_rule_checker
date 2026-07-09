import os
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as MplPolygon
from shapely.geometry import MultiPoint

from src.config.labels import get_wall


def visualize_elements(elements, SVG_CATEGORIES, save_dir, filename, alpha=0.25):
    """
    可视化 SVG 提取出的基础元素，并保存到指定文件夹
    """
    # --- 字体设置 ---
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
    plt.rcParams['axes.unicode_minus'] = False

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')

    # ------------------------------------------------------------
    # 1) 将 SVG_CATEGORIES id → color 构建成字典（归一化到 0~1）
    # ------------------------------------------------------------
    id2color = {
        c["name"]: [c["color"][0] / 255, c["color"][1] / 255, c["color"][2] / 255]
        for c in SVG_CATEGORIES
    }

    # ------------------------------------------------------------
    # 2) 收集实例点
    # ------------------------------------------------------------
    instance_points = {}
    instance_types = {}  # 记录每个实例的 type，用于排除墙体

    def add_points_to_instance(e, pts):
        inst = int(e.get("instance_id", -1))
        if inst == -1:
            return

        if inst not in instance_points:
            instance_points[inst] = []
        instance_points[inst].extend(pts)

        # 记录类型（如 wall、door 等）
        if inst not in instance_types:
            instance_types[inst] = e["type"]

    # ------------------------------------------------------------
    # 3) 主循环：绘制元素 + 收集点
    # ------------------------------------------------------------
    for e in elements:
        etype = e["type"]

        # ----- 文本：画并记录 -----
        if etype == "text":
            x, y = e["coords"]
            content = e.get("text", "N/A")

            ax.text(
                x, y,
                content,
                fontsize=8,
                color='purple',
                ha='left',
                va='bottom',
                clip_on=True
            )

            add_points_to_instance(e, [(x, y)])
            continue

        # ----- 非文本：画线 -----
        coords = np.array(e["coords"])
        x, y = coords[:, 0], coords[:, 1]

        semantic_label = e.get("semantic_label")
        if semantic_label in id2color:
            rgb = id2color[semantic_label]
        else:
            rgb = [0.5, 0.5, 0.5]

        if etype.lower() in get_wall():
            rgb = [0.72, 0.52, 0.04]
            ax.plot(x, y, color=rgb, linewidth=0.5)
        else:
            ax.plot(x, y, color=rgb, linewidth=0.5)

        add_points_to_instance(e, coords.tolist())

    # ------------------------------------------------------------
    # 4) 为每个实例绘制透明包围盒（跳过墙体）
    # ------------------------------------------------------------
    for inst, pts in instance_points.items():
        pts = np.array(pts)
        if pts.shape[0] == 0:
            continue

        etype = instance_types.get(inst, "")

        # 跳过墙体及 wall 类别
        if etype.lower() in get_wall():
            continue

        # 获取颜色（默认灰）
        color_id = None
        for e in elements:
            if (e.get("instance_id") == inst) or (e.get("id") == inst) or (e.get("label") == inst):
                color_id = e.get("semantic_label")
                break

        if color_id in id2color:
            rgb = id2color[color_id]
        else:
            rgb = [0.5, 0.5, 0.5]

        # # ---- 使用 Shapely 计算最小外接矩形 (MRR) ----
        # mrr_poly = MultiPoint(pts).minimum_rotated_rectangle

        # 使用Shapely计算正交包围盒
        obb_poly = MultiPoint(pts).envelope

        # 防御性处理：防止点集完全共线导致退化为线，施加极小缓冲
        if obb_poly.geom_type in ['LineString', 'Point']:
            obb_poly = obb_poly.buffer(1.0).minimum_rotated_rectangle

        if obb_poly.geom_type == 'Polygon':
            obb_coords = list(obb_poly.exterior.coords)

            # ---- 绘制透明包围盒 (使用 Polygon 替代 Rectangle 以支持倾斜) ----
            poly_patch = MplPolygon(
                obb_coords,
                closed=True,
                linewidth=1,
                edgecolor=rgb,
                facecolor=rgb + [alpha]
            )
            ax.add_patch(poly_patch)

            # ---- 绘制实例标签 (放置在 MRR 质心位置) ----
            ax.text(
                obb_poly.centroid.x,
                obb_poly.centroid.y,
                etype,
                fontsize=8,
                color=rgb,
                ha='center',
                va='center',
                fontweight='bold'
            )

    # ------------------------------------------------------------
    # 5) 自动创建目录并保存图片
    # ------------------------------------------------------------
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    print(f"✅ Element visualization saved to: {save_path}")
    plt.close(fig)  # 释放内存