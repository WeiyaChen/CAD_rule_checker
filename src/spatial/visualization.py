# src/spatial/visualization.py
"""空间轮廓提取结果的可视化（与具体算法无关）。

左图由算法自身的 ``get_visualization_data()`` 提供（CDT 是三角网，其他算法可以是
空三角网），右图统一绘制最终提取出的房间轮廓，因此任何实现了
:class:`~src.spatial.contracts.ISpatialContourExtractor` 的算法都能复用。

（历史模块名 ``src/utils/cdt_viz.py`` 已被删除，其函数就是本模块。）
"""

import os
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import Polygon

__all__ = ["plot_floor_plan"]


def plot_floor_plan(extractor, room_results, save_dir, filename):
    """可视化底层算法的中间数据及最终生成的房间，并保存到指定文件夹

    Args:
        extractor: 空间轮廓提取算法实例，需提供 ``get_visualization_data()``
        room_results: 算法返回的房间结果列表 (``id`` / ``label`` / ``geometry``)
        save_dir: 保存结果的文件夹路径
        filename: 保存的图片文件名
    """
    # 1. 从提取算法内部提取数据
    real_walls, virtual_walls, triangles, points = extractor.get_visualization_data()

    if points is not None and len(points) > 0:
        points = np.array(points)
    else:
        print("No valid point cloud data, cannot plot.")
        return

    # --- 字体设置 ---
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
    plt.rcParams['axes.unicode_minus'] = False

    # 创建画布
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 9))

    # ------------------------------------------
    # 左图：算法视角 (Mesh & Constraints)
    # ------------------------------------------
    # CDT 会提供三角网，其他算法（如 RGP）可能没有，标题据此自适应
    view_kind = "Mesh" if triangles is not None and len(triangles) > 0 else "Geometry"
    ax1.set_title(f"Algorithm View: {view_kind} & Detected Walls\n(Virtual Walls: {len(virtual_walls)})", fontsize=14)

    # A. 画背景三角网 (灰色细线)
    if triangles is not None and len(triangles) > 0:
        ax1.triplot(points[:, 0], points[:, 1], triangles, color='#e0e0e0', linewidth=0.5, zorder=1)
        ax1.scatter(points[:, 0], points[:, 1], s=5, c='gray', alpha=0.5, zorder=2)

    # B. 画真实墙体 (黑色实线)
    for line in real_walls:
        x, y = line.xy
        ax1.plot(x, y, color='black', linewidth=2.0, alpha=0.8, zorder=10, label='Real Wall')

    # C. 画识别出的虚拟阻断线 (红色粗虚线)
    if virtual_walls:
        for i, line in enumerate(virtual_walls):
            x, y = line.xy
            label = 'Detected Virtual Wall' if i == 0 else "_nolegend_"
            ax1.plot(x, y, color='red', linewidth=3.0, linestyle='--', zorder=20, label=label)
    else:
        ax1.text(0.5, 0.5, "No Virtual Walls Detected!", transform=ax1.transAxes,
                 ha='center', color='red', fontsize=12, fontweight='bold')

    # 图例去重
    handles, labels = ax1.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    if by_label:
        ax1.legend(by_label.values(), by_label.keys(), loc='upper right')
    ax1.set_aspect('equal')

    # ------------------------------------------
    # 右图：结果视角 (Final Rooms)
    # ------------------------------------------
    ax2.set_title(f"Result View: Extracted Rooms ({len(room_results)})", fontsize=14)

    # A. 淡淡地画出墙体作为底图
    for line in real_walls:
        x, y = line.xy
        ax2.plot(x, y, color='lightgray', linewidth=1, zorder=1)

    # B. 填充房间颜色
    colors = ['#FFB7B2', '#B5EAD7', '#C7CEEA', '#E2F0CB', '#FFDAC1', '#FF9AA2']

    for i, room in enumerate(room_results):
        coords = room.get('geometry', [])
        if not coords: continue

        label_text = room.get('id', f'Room_{i}')
        poly = Polygon(coords)
        x, y = poly.exterior.xy

        color = colors[i % len(colors)]

        # 填充多边形
        ax2.fill(x, y, fc=color, ec='black', alpha=0.6, linewidth=1.5, zorder=5)

        # 标注文字
        cx, cy = poly.centroid.x, poly.centroid.y
        ax2.text(cx, cy, label_text, fontsize=9, ha='center', va='center', fontweight='bold', color='#333333',
                 zorder=10)

    ax2.set_aspect('equal')
    plt.tight_layout()

    # ------------------------------------------
    # 自动创建目录并保存图片
    # ------------------------------------------
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, filename)
    plt.savefig(save_path, bbox_inches='tight', dpi=300)
    print(f"✅ Spatial reconstruction visualization saved to: {save_path}")
    plt.close(fig)  # 释放内存