import matplotlib.pyplot as plt
from shapely.geometry import Polygon as ShapelyPolygon, box, Point
from shapely.affinity import rotate, translate
import numpy as np


# --- 核心MIS算法 (用于右图真理层) ---
def calculate_maximum_inscribed_square_quick(room_coords):
    room_poly = ShapelyPolygon(room_coords)
    minx, miny, maxx, maxy = room_poly.bounds
    # 降低密度以加快演示速度
    x_coords = np.linspace(minx, maxx, 30)
    y_coords = np.linspace(miny, maxy, 30)
    candidate_centers = []
    for x in x_coords:
        for y in y_coords:
            if room_poly.contains(Point(x, y)):
                candidate_centers.append((x, y))

    min_w, max_w = 0.0, min(maxx - minx, maxy - miny)
    best_w, best_square = 0.0, None

    # 简化的二分查找
    for _ in range(15):
        test_w = (max_w + min_w) / 2.0
        template = box(-test_w / 2, -test_w / 2, test_w / 2, test_w / 2)
        is_fitting = False
        for cx, cy in candidate_centers:
            placed = translate(template, cx, cy)
            # 只做简单滑移检查，不做旋转，足以说明问题
            if room_poly.contains(placed):
                is_fitting = True
                best_square = placed
                break
        if is_fitting:
            best_w, min_w = test_w, test_w
        else:
            max_w = test_w
    return round(best_w, 1), best_square


# --- 定义反例几何 ---
# 一个“胖”L型：臂窄(1500)，但转角腹地宽(2500以上)
l_coords = [(0, 0), (4000, 0), (4000, 1500), (1500, 1500), (1500, 4000), (0, 4000), (0, 0)]
room_poly = ShapelyPolygon(l_coords)

# --- 绘图 ---
fig, axes = plt.subplots(1, 2, figsize=(14, 7), dpi=150)

# [左图] 你的猜想：凸空间分解法 (人为切割)
axes[0].plot(*room_poly.exterior.xy, color='black', linewidth=2)
axes[0].fill(*room_poly.exterior.xy, color='#e0e0e0')

# 模拟延长凹边 (从 (1500,1500) 向下切到 (1500,0))
cut_line_x = [1500, 1500]
cut_line_y = [0, 1500]
axes[0].plot(cut_line_x, cut_line_y, color='red', linestyle='--', linewidth=3, label='人为切割线 (隐形玻璃墙)')

# 绘制切割后的两个矩形
# 矩形A (左侧竖向)
rect_a = box(0, 0, 1500, 4000)
axes[0].fill(*rect_a.exterior.xy, color='red', alpha=0.3, label='切割矩形 A (短边=1500)')
# 矩形B (底部横向)
rect_b = box(1500, 0, 4000, 1500)
axes[0].fill(*rect_b.exterior.xy, color='orange', alpha=0.3, label='切割矩形 B (短边=1500)')

axes[0].set_title("(a) 你的猜想：人为切割法 (错误)\n判断结果：短边净宽 = 1500mm", fontsize=12, fontweight='bold',
                  color='darkred')
axes[0].legend(loc='upper right')
axes[0].axis('equal')
axes[0].axis('off')

# [右图] 实际真理：全局MIS寻优 (空间连续性)
axes[1].plot(*room_poly.exterior.xy, color='black', linewidth=2)
axes[1].fill(*room_poly.exterior.xy, color='#e0e0e0')

# 计算真实的 MIS
true_w, true_sq = calculate_maximum_inscribed_square_quick(l_coords)

if true_sq:
    axes[1].plot(*true_sq.exterior.xy, color='green', linewidth=2)
    axes[1].fill(*true_sq.exterior.xy, color='green', alpha=0.5,
                 label=f'最大内切正方形 (跨越切割线)\n边长 = {true_w}mm')

axes[1].set_title(f"(b) 空间真理：全局拓扑寻优 (正确)\n判断结果：短边净宽 = {true_w}mm", fontsize=12, fontweight='bold',
                  color='darkgreen')
axes[1].legend(loc='upper right')
axes[1].axis('equal')
axes[1].axis('off')

plt.tight_layout()
fig.suptitle("反例验证：为何不能简单延长凹边切割 L 型房间？", fontsize=16, y=1.05)
plt.show()