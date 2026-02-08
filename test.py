import matplotlib.pyplot as plt
import matplotlib.patches as patches

# 设置绘图风格
fig, ax = plt.subplots(1, 2, figsize=(12, 5))


# 定义画门和墙的辅助函数
def draw_scenario(ax, title, door_x, door_y, door_w, door_h, wall_y, label_gap=False):
    # 1. 画墙 (Wall) - 灰色基准线
    ax.axhline(y=wall_y, color='gray', linewidth=3, linestyle='--', label='Wall / Baseline')

    # 2. 画门 (Door) - 蓝色矩形 (OBB)
    door = patches.Rectangle((door_x, door_y), door_w, door_h,
                             linewidth=2, edgecolor='blue', facecolor='lightblue', alpha=0.6, label='Door (OBB)')
    ax.add_patch(door)

    # 3. 计算并画交线 (Intersection) - 红色
    # 门的底部是 door_y，顶部是 door_y + door_h
    # 墙的位置是 wall_y
    # 只有当 door_y <= wall_y <= door_y + door_h 时才有交线
    if door_y <= wall_y <= door_y + door_h:
        intersect_start = door_x
        intersect_end = door_x + door_w
        # 这里简化处理，假设x方向完全重叠，只看y方向接触
        # 如果有错位，x也会变化。
        # 场景2：错位。墙是从 x=0 开始的。
        wall_start_x = 0
        wall_end_x = 10  # 假设墙很长

        # 计算X轴的交集
        x_start = max(door_x, wall_start_x)
        x_end = min(door_x + door_w, wall_end_x)

        if x_end > x_start:
            ax.plot([x_start, x_end], [wall_y, wall_y], color='red', linewidth=6,
                    label='Intersection Length (Unstable)')
            ax.text((x_start + x_end) / 2, wall_y - 0.5, f"Intersection: {x_end - x_start:.1f}m", color='red',
                    ha='center', fontweight='bold')
        else:
            ax.text(door_x + door_w / 2, wall_y - 0.5, "Intersection: 0.0m", color='red', ha='center',
                    fontweight='bold')
    else:
        # 没有接触 (Gap)
        ax.text(door_x + door_w / 2, wall_y - 0.5, "Intersection: 0.0m (FAIL)", color='red', ha='center',
                fontweight='bold')

    # 4. 画投影 (Projection) - 绿色
    # 投影只看门在X轴上的跨度
    proj_y = wall_y - 1.5  # 往下画一点，错开显示
    ax.plot([door_x, door_x + door_w], [proj_y, proj_y], color='green', linewidth=4, marker='|', markersize=10,
            label='Projection Length (Robust)')

    # 画投影虚线
    ax.plot([door_x, door_x], [door_y, proj_y], color='green', linestyle=':', alpha=0.5)
    ax.plot([door_x + door_w, door_x + door_w], [door_y, proj_y], color='green', linestyle=':', alpha=0.5)

    ax.text(door_x + door_w / 2, proj_y - 0.5, f"Projection: {door_w:.1f}m (CORRECT)", color='green', ha='center',
            fontweight='bold')

    ax.set_title(title, fontsize=12)
    ax.set_xlim(-1, 5)
    ax.set_ylim(-3, 3)
    ax.set_aspect('equal')
    ax.axis('off')  # 隐藏坐标轴
    if label_gap:
        ax.annotate('Gap / Jitter', xy=(door_x + 0.5, door_y), xytext=(door_x + 1.5, door_y - 0.8),
                    arrowprops=dict(facecolor='black', shrink=0.05))


# --- 场景 1: 微小缝隙 (The Gap) ---
# 门宽 2.0，位置 (1, 0.2)，墙在 y=0。门悬浮在墙上方 0.2m。
draw_scenario(ax[0], "Scenario A: Positional Jitter (Gap)\nIntersection Fails, Projection Works",
              door_x=1.0, door_y=0.2, door_w=2.0, door_h=1.0, wall_y=0, label_gap=True)

# --- 场景 2: 错位/部分重叠 (Partial Overlap) ---
# 门宽 2.0，位置 (2.5, -0.5)。假设墙只画到 x=3.0 就结束了（模拟房间边缘）。
# 为了演示，我们让墙是一条线，门偏了。
# 这里我们模拟门的一半在墙上，一半在外面。
# 墙定义：y=0, x from 0 to 3.0
ax[1].plot([0, 3.0], [0, 0], color='gray', linewidth=3, linestyle='--')  # 墙只到3.0
# 门从 2.0 到 4.0 (宽2.0)。
# 交集：2.0 到 3.0 (长1.0) -> 错误
# 投影：2.0 到 4.0 (长2.0) -> 正确
draw_scenario(ax[1], "Scenario B: Partial Overlap / Misalignment\nIntersection Cut Short, Projection Full",
              door_x=2.0, door_y=-0.5, door_w=2.0, door_h=1.0, wall_y=0)
# 修正场景2的绘制逻辑以匹配特定描述
ax[1].patches.pop()  # 移除旧的
ax[1].lines.pop()  # 移除旧的
# 重新手动绘制场景2
ax[1].plot([0, 3.0], [0, 0], color='gray', linewidth=3, linestyle='--', label='Room Boundary')  # 房间轮廓
door2 = patches.Rectangle((2.0, -0.5), 2.0, 1.0, linewidth=2, edgecolor='blue', facecolor='lightblue', alpha=0.6)
ax[1].add_patch(door2)

# 交线 (只有重叠部分)
ax[1].plot([2.0, 3.0], [0, 0], color='red', linewidth=6)
ax[1].text(2.5, -0.5, "Intersect: 1.0m (Error)", color='red', ha='center', fontweight='bold')

# 投影
proj_y2 = -1.5
ax[1].plot([2.0, 4.0], [proj_y2, proj_y2], color='green', linewidth=4, marker='|')
ax[1].plot([2.0, 2.0], [-0.5, proj_y2], color='green', linestyle=':', alpha=0.5)
ax[1].plot([4.0, 4.0], [-0.5, proj_y2], color='green', linestyle=':', alpha=0.5)
ax[1].text(3.0, proj_y2 - 0.5, "Projection: 2.0m (Correct)", color='green', ha='center', fontweight='bold')
ax[1].set_title("Scenario B: Misalignment / Partial Overlap", fontsize=12)
ax[1].axis('off')

plt.tight_layout()
plt.legend(loc='upper right')
plt.show()