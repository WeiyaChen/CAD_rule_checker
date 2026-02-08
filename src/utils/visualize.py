import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from matplotlib.lines import Line2D
from shapely import Polygon, wkt


def visualize_elements(elements, SVG_CATEGORIES, alpha=0.25):
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Rectangle

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
        inst = int(e.get("instance_id"))
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
            print(content)

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
        coords = e["coords"]
        x, y = coords[:, 0], coords[:, 1]

        semantic_label = e.get("semantic_label")
        if semantic_label in id2color:
            rgb = id2color[semantic_label]
        else:
            rgb = [0.5, 0.5, 0.5]
        if "wall" in etype or "window" in etype or "door" in etype or "opening" in etype:
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

        # 跳过墙体及 wall 类别（SVG id=33 也跳过）
        if "wall" in etype.lower():
            continue

        # 获取颜色（默认灰）
        color_id = None
        # 如果 elements 中元素含有 id 字段，则取出来
        for e in elements:
            if (e.get("instance_id") == inst) or (e.get("id") == inst) or (e.get("label") == inst):
                color_id = e.get("semantic_label")
                break

        if color_id in id2color:
            rgb = id2color[color_id]
        else:
            rgb = [0.5, 0.5, 0.5]

        # 计算 bbox
        xmin, ymin = pts.min(axis=0)
        xmax, ymax = pts.max(axis=0)
        width, height = xmax - xmin, ymax - ymin

        # ---- 绘制透明包围盒（用 Rectangle）----
        rect = Rectangle(
            (xmin, ymin),
            width,
            height,
            linewidth=1,
            edgecolor=rgb,
            facecolor=rgb + [alpha],  # 添加透明度
        )
        ax.add_patch(rect)

        # ---- 绘制实例标签 ----
        ax.text(
            xmin,
            ymax,
            etype,
            fontsize=8,
            color=rgb,
            va='bottom'
        )

    plt.show()


def plot_floor_plan(builder, room_results):
    """
    Args:
        builder: 运行完 build 的 FloorPlanMeshBuilder 实例
        room_results: build 返回的房间结果列表
    """
    # 1. 从 Builder 内部提取数据
    real_walls, virtual_walls, tri, points = builder.get_visualization_data()

    # 转换为 numpy 方便绘图
    points = np.array(points)

    # 创建画布
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 9))

    # ------------------------------------------
    # 左图：算法视角 (Mesh & Constraints)
    # ------------------------------------------
    ax1.set_title(f"Algorithm View: Mesh & Detected Walls\n(Virtual Walls: {len(virtual_walls)})", fontsize=14)

    # A. 画背景三角网 (灰色细线)
    if tri is not None:
        ax1.triplot(points[:, 0], points[:, 1], tri.simplices, color='#e0e0e0', linewidth=0.5, zorder=1)
        ax1.scatter(points[:, 0], points[:, 1], s=5, c='gray', alpha=0.5, zorder=2)

    # B. 画真实墙体 (黑色实线)
    for line in real_walls:
        x, y = line.xy
        ax1.plot(x, y, color='black', linewidth=2.0, alpha=0.8, zorder=10, label='Real Wall')

    # C. 画识别出的虚拟阻断线 (红色粗虚线) - 这是核心！
    # 如果代码工作正常，这里应该能看到门洞被封住了
    if virtual_walls:
        for i, line in enumerate(virtual_walls):
            x, y = line.xy
            label = 'Detected Virtual Wall' if i == 0 else "_nolegend_"
            ax1.plot(x, y, color='red', linewidth=3.0, linestyle='--', zorder=20, label=label)
    else:
        # 如果没识别出来，在图上写个警告
        ax1.text(0.5, 0.5, "No Virtual Walls Detected!", transform=ax1.transAxes,
                 ha='center', color='red', fontsize=12, fontweight='bold')

    # 图例去重
    handles, labels = ax1.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
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
    # 预设一组好看的颜色
    colors = ['#FFB7B2', '#B5EAD7', '#C7CEEA', '#E2F0CB', '#FFDAC1', '#FF9AA2']

    for i, room in enumerate(room_results):
        coords = room['geometry']
        label = room['label']

        poly = Polygon(coords)
        x, y = poly.exterior.xy

        color = colors[i % len(colors)]

        # 填充多边形
        ax2.fill(x, y, fc=color, ec='black', alpha=0.6, linewidth=1.5, zorder=5)

        # 标注文字
        cx, cy = poly.centroid.x, poly.centroid.y
        ax2.text(cx, cy, label, fontsize=9, ha='center', va='center', fontweight='bold', color='#333333', zorder=10)

    ax2.set_aspect('equal')

    plt.tight_layout()
    plt.show()