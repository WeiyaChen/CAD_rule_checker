import math
import numpy as np
import matplotlib.pyplot as plt
from shapely.geometry import Polygon as ShapelyPolygon, box, Point
from shapely.affinity import rotate, translate
from shapely.ops import polylabel
import matplotlib.font_manager as fm


# --- 配置字体 (保持不变) ---
def configure_chinese_font():
    potential_fonts = ['SimHei', 'Microsoft YaHei', 'Songti SC', 'Heiti TC', 'WenQuanYi Micro Hei']
    system_fonts = [f.name for f in fm.fontManager.ttflist]
    for font_name in potential_fonts:
        if font_name in system_fonts:
            plt.rcParams['font.sans-serif'] = [font_name] + plt.rcParams['font.sans-serif']
            break
    plt.rcParams['axes.unicode_minus'] = False


configure_chinese_font()


# --- 核心算法引擎 (保持不变) ---
def calculate_maximum_inscribed_square(room_coords, tolerance=10.0):
    room_poly = ShapelyPolygon(room_coords)
    minx, miny, maxx, maxy = room_poly.bounds
    # 提高采样密度以应对更复杂的形状
    x_coords = np.linspace(minx, maxx, 25)
    y_coords = np.linspace(miny, maxy, 25)

    candidate_centers = []
    for x in x_coords:
        for y in y_coords:
            pt = Point(x, y)
            if room_poly.contains(pt):
                candidate_centers.append((x, y))

    pole = polylabel(room_poly, tolerance=1.0)
    candidate_centers.append((pole.x, pole.y))

    min_w = 0.0
    max_w = min(maxx - minx, maxy - miny)
    best_w = 0.0
    best_square = None

    while (max_w - min_w) > tolerance:
        test_w = (max_w + min_w) / 2.0
        template_square = box(-test_w / 2.0, -test_w / 2.0, test_w / 2.0, test_w / 2.0)

        is_fitting = False
        for cx, cy in candidate_centers:
            placed_square = translate(template_square, cx, cy)
            # 提高旋转精度以应对梯形斜边
            for angle in range(0, 90, 2):
                rotated_square = rotate(placed_square, angle, origin='center')
                if room_poly.contains(rotated_square):
                    is_fitting = True
                    best_square = rotated_square
                    break
            if is_fitting:
                break

        if is_fitting:
            best_w = test_w
            min_w = test_w
        else:
            max_w = test_w

    return round(best_w, 1), best_square


# --- 通用绘图函数 ---
def plot_case(ax, coords, title_prefix):
    w, sq = calculate_maximum_inscribed_square(coords)
    poly = ShapelyPolygon(coords)
    ax.plot(*poly.exterior.xy, color='black', linewidth=2)
    ax.fill(*poly.exterior.xy, color='#e0e0e0')
    if sq:
        ax.plot(*sq.exterior.xy, color='#2ca02c', linewidth=2)
        ax.fill(*sq.exterior.xy, color='#2ca02c', alpha=0.5)
    ax.set_title(f"{title_prefix}\nMIS边长(短边净宽): {w}mm", fontsize=12, fontweight='bold')
    ax.axis('equal')
    ax.axis('off')


# ---------------- 定义所有测试案例坐标 ----------------

# 案例1: L型 (原有)
coords_L = [(0, 0), (4000, 0), (4000, 3200), (2200, 3200), (2200, 5000), (0, 5000), (0, 0)]

# 案例2: 正六边形 (原有)
radius = 1154.7
angles_hex = [i * 60 + 30 for i in range(6)]
coords_hex = [(radius * math.cos(math.radians(a)), radius * math.sin(math.radians(a))) for a in angles_hex]

# 案例3: 梯形/楔形 (新增 - 测试斜边与旋转)
coords_trap = [(0, 0), (4500, 0), (4500, 2500), (1500, 5000), (0, 5000), (0, 0)]

# 案例4: 受柱子侵蚀的矩形 (新增 - 测试细碎边界碰撞)
# 5000x4000的大房间，左下和右上角被柱子吃掉一块
coords_cols = [
    (600, 0), (5000, 0), (5000, 3400), (4400, 3400),
    (4400, 4000), (0, 4000), (0, 600), (600, 600), (600, 0)
]

# 案例5: Z型多口袋空间 (新增 - 测试全局寻优)
# 下部口袋较小，上部口袋较大
coords_z = [
    (0, 0), (3500, 0), (3500, 2000), (6500, 2000),
    (6500, 5000), (3000, 5000), (3000, 3000), (0, 3000), (0, 0)
]

# ---------------- 执行可视化绘制 ----------------

# 创建 2行3列 的画布
fig, axes = plt.subplots(2, 3, figsize=(18, 12), dpi=150)
axes = axes.flatten()  # 展平方便索引

# 绘制前五个案例
plot_case(axes[0], coords_L, "(a) L型非凸空间")
plot_case(axes[1], coords_trap, "(b) 梯形斜边空间")
plot_case(axes[2], coords_cols, "(c) 结构柱侵蚀空间")
plot_case(axes[3], coords_hex, "(d) 正六边形收缩空间")
plot_case(axes[4], coords_z, "(e) Z型多口袋空间")

# 隐藏最后一个多余的子图
axes[5].axis('off')

plt.tight_layout()
# 添加总标题，提升学术感
fig.suptitle("图 4-X 基于最大内切正方形(MIS)算法的复杂异型卧室短边净宽自动化推演验证", fontsize=16, y=1.02)
plt.show()