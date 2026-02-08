import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial import Delaunay
import matplotlib.patches as patches

# 设置绘图风格，确保中文显示
plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial']
plt.rcParams['axes.unicode_minus'] = False


def calculate_circumcircle(p1, p2, p3):
    """
    计算三角形 (p1, p2, p3) 的外接圆圆心和半径
    """
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3

    D = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))

    center_x = ((x1 ** 2 + y1 ** 2) * (y2 - y3) + (x2 ** 2 + y2 ** 2) * (y3 - y1) + (x3 ** 2 + y3 ** 2) * (y1 - y2)) / D
    center_y = ((x1 ** 2 + y1 ** 2) * (x3 - x2) + (x2 ** 2 + y2 ** 2) * (x1 - x3) + (x3 ** 2 + y3 ** 2) * (x2 - x1)) / D

    radius = np.sqrt((center_x - x1) ** 2 + (center_y - y1) ** 2)
    return (center_x, center_y), radius


def visualize_delaunay_properties():
    # -------------------------------------------------
    # 1. 数据准备：模拟一个有干扰点的缺口场景
    # -------------------------------------------------
    # 墙体缺口：(4,0) 和 (6,0) 是需要连接的端点
    # 干扰点：(5, 3) 是房间里的家具或柱子
    points = np.array([
        [0, 0], [2, 0], [4, 0],  # 左墙
        [6, 0], [8, 0], [10, 0],  # 右墙
        [5, 3]  # 房间内部的一个点 (干扰项)
    ])

    # -------------------------------------------------
    # 2. 生成三角剖分
    # -------------------------------------------------
    tri = Delaunay(points)

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_aspect('equal')
    ax.set_title("Delaunay '空圆特性' 可视化证明", fontsize=16, fontweight='bold', pad=20)

    # --- A. 绘制所有的点 ---
    ax.plot(points[:, 0], points[:, 1], 'ko', markersize=8, zorder=10, label='墙体/结构点')

    # --- B. 绘制三角网 (灰色虚线) ---
    ax.triplot(points[:, 0], points[:, 1], tri.simplices, 'k--', alpha=0.3, lw=1, label='三角剖分网格')

    # --- C. 重点演示：为什么 (4,0) 会连向 (6,0)？ ---
    # 找到连接缺口的那两个点：索引 2 和 3
    # 以及它们构成的三角形

    # 遍历所有三角形，找到包含点2和点3的那个三角形
    target_simplex = None
    for simplex in tri.simplices:
        if 2 in simplex and 3 in simplex:
            target_simplex = simplex
            break

    if target_simplex is not None:
        # 获取三角形的三个顶点坐标
        p_tri = points[target_simplex]

        # 1. 高亮这个三角形 (填充颜色)
        poly = plt.Polygon(p_tri, facecolor='skyblue', alpha=0.3, edgecolor='blue', lw=2, label='连接缺口的三角形')
        ax.add_patch(poly)

        # 2. 绘制这条关键的连接边 (缺口修复线)
        ax.plot([4, 6], [0, 0], 'r-', linewidth=3, label='生成的虚拟连接 (Gap Connection)')

        # 3. 计算并绘制外接圆 (空圆)
        center, radius = calculate_circumcircle(p_tri[0], p_tri[1], p_tri[2])
        circle = patches.Circle(center, radius, fill=False, edgecolor='green', linestyle='--', linewidth=2,
                                label='外接圆 (Empty Circle)')
        ax.add_patch(circle)

        # 绘制圆心
        ax.plot(center[0], center[1], 'gx', markersize=8)

        # 添加注释解释
        ax.text(5, 1.5, "三角网连接了缺口", color='blue', ha='center', fontweight='bold')
        ax.text(center[0], center[1] + radius + 0.2, "空圆特性：\n圆内没有任何其他点\n所以这三点互为邻居",
                color='green', ha='center', fontsize=11, bbox=dict(facecolor='white', alpha=0.8, edgecolor='green'))

    # 标记坐标点
    for i, p in enumerate(points):
        ax.text(p[0], p[1] - 0.4, f"P{i}\n({p[0]},{p[1]})", ha='center', fontsize=9)

    ax.set_xlim(-1, 11)
    ax.set_ylim(-2, 7)
    ax.legend(loc='upper right', frameon=True)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    visualize_delaunay_properties()