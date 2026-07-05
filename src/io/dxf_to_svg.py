from locale import normalize

import ezdxf
import os
import math
from ezdxf import bbox
from ezdxf import colors
from collections import Counter
import xml.etree.ElementTree as ET

from numpy import cross
from ezdxf import path

from src.config.config import settings


def get_entity_color(entity, override_layer=None):
    """获取图元颜色，支持图层覆盖逻辑以适配块引用"""
    # 优先使用 TrueColor（24位）
    if entity.dxf.hasattr("true_color"):
        r, g, b = colors.aci2rgb(entity.dxf.true_color)
        return (r, g, b)

    # 若为 ByLayer 或 ByBlock，读取最终继承的颜色索引
    color_index = entity.dxf.color
    if color_index in (0, 256):  # ByBlock 或 ByLayer
        try:
            # 优先使用覆盖图层（即块所在的图层）进行颜色索引查找
            layer = override_layer if override_layer else entity.dxf.layer
            layer_obj = entity.doc.layers.get(layer)
            if layer_obj is not None:
                color_index = layer_obj.color
        except Exception:
            color_index = 7  # 默认白色

    # 转换 AutoCAD 颜色索引为 RGB
    r, g, b = colors.aci2rgb(color_index)

    # 亮度计算
    brightness = (0.299 * r + 0.587 * g + 0.114 * b)

    # 视觉优化：白色在白底 SVG 中反转为黑色
    if (r, g, b) == (255, 255, 255):
        return 0, 0, 0

    # 太亮则压暗处理
    if brightness > 200:
        factor = 0.5
        r, g, b = int(r * factor), int(g * factor), int(b * factor)

    return (r, g, b)


def convert_dxf_to_svg(dxf_path, svg_path):
    # 读取 DXF 文件
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    # 背景颜色:默认设置为白色
    svg_bg_color = "#FFFFFF"

    # 统计各类型数量
    types = Counter(e.dxftype() for e in msp)
    for t, n in types.items():
        print(f"{t}: {n}")

    # 计算边界
    ext = bbox.extents(msp)
    xmin, xmax = ext.extmin[0], ext.extmax[0]
    ymin, ymax = ext.extmin[1], ext.extmax[1]

    # 缩放长度，反转y轴
    def scale_point(x, y):
        # 选较小的，保持完整显示
        sx = 140 / (xmax - xmin)
        sy = 140 / (ymax - ymin)
        s = min(sx, sy)
        # 计算偏移，让图形居中
        new_w = s * (xmax - xmin)
        new_h = s * (ymax - ymin)
        offset_x = (140 - new_w) / 2
        offset_y = (140 - new_h) / 2

        # 应用变换 + 翻转 y
        x_new = offset_x + s * (x - xmin)
        y_new = 140 - (offset_y + s * (y - ymin))
        return x_new, y_new

    # 缩放长度
    def scale_length(length):
        # 选较小的，保持完整显示
        sx = 140 / (xmax - xmin)
        sy = 140 / (ymax - ymin)
        s = min(sx, sy)
        length = s * length
        return length

    # 创建 SVG 根元素
    sx = 140 / (xmax - xmin)
    sy = 140 / (ymax - ymin)
    s = min(sx, sy)
    svg = ET.Element('svg', {"xmlns": "http://www.w3.org/2000/svg", "style": f"background-color:{svg_bg_color}", "scale":str(s)})

    # 按图层收集对象
    layer_groups = {}
    def get_layer_group(layer_name):
        if layer_name not in layer_groups:
            layer_groups[layer_name] = ET.SubElement(svg, 'g', id=layer_name)
        return layer_groups[layer_name]

    def process_entities(entities, override_layer=None):
        """递归处理图元集合，实现块引用的深度遍历"""
        for e in entities:
            # 1. 跳过被标记为不可见的图元 (动态块可见性状态通常通过此属性控制)
            if e.dxf.hasattr('invisible') and e.dxf.invisible:
                continue

            # ==========================================================
            # 【修复 1】：前置 current_layer 的计算，确立外部容器图层的绝对优先级
            # ==========================================================
            current_layer = override_layer if override_layer else str(e.dxf.layer)

            # ==========================================================
            # 【修复 2】：判断 current_layer 的可见性，防止底层硬编码图层处于关闭状态而遭到误杀
            # ==========================================================
            try:
                layer_obj = doc.layers.get(current_layer)
                if layer_obj is not None and (layer_obj.is_off() or layer_obj.is_frozen()):
                    continue
            except Exception:
                pass

            # --- 深度遍历逻辑：处理 INSERT 图元 ---
            if e.dxftype() == 'INSERT':
                try:
                    # ==========================================================
                    # 【修复 3】：向下传递 current_layer，防止嵌套子块重置 override_layer
                    # ==========================================================
                    process_entities(e.virtual_entities(), override_layer=current_layer)
                except Exception as ex:
                    print(f"  [-] 展开块 {e.dxf.name} 失败: {ex}")
                continue

            # 处理标注线实体 (自动拆解为线段、文字与箭头)
            elif e.dxftype() in ('DIMENSION', 'ARC_DIMENSION', 'LARGE_RADIAL_DIMENSION', 'LEADER', 'MULTILEADER'):
                try:
                    process_entities(e.virtual_entities(), override_layer=current_layer)
                except Exception as ex:
                    print(f"  [-] 解析标注 {e.dxftype()} 失败: {ex}")
                continue

            # 获取图元最终所属图层的分组
            g = get_layer_group(current_layer)
            rgb_r, rgb_g, rgb_b = get_entity_color(e, override_layer=current_layer)
            color_str = f"rgb({rgb_r},{rgb_g},{rgb_b})"
            common_attr = {"fill": "none", "stroke": color_str, "stroke-width": "0.1"}

            # ==========================================================
            # 【新增逻辑】：SVG 坐标序列去重与防退化过滤器
            # ==========================================================
            def filter_consecutive_points(pts, tol=1e-4):
                """过滤连续重复或极度接近的点，防止生成 M x,y L x,y 退化路径"""
                if not pts: return []
                clean_pts = [pts[0]]
                for p in pts[1:]:
                    if abs(p[0] - clean_pts[-1][0]) > tol or abs(p[1] - clean_pts[-1][1]) > tol:
                        clean_pts.append(p)
                return clean_pts

            if e.dxftype() == 'LINE':
                x1, y1 = scale_point(e.dxf.start.x, e.dxf.start.y)
                x2, y2 = scale_point(e.dxf.end.x, e.dxf.end.y)
                # 提高容差阈值至 1e-4，彻底阻断肉眼不可见的零长度线
                if abs(x1 - x2) > 1e-4 or abs(y1 - y2) > 1e-4:
                    d = f"M {x1:.4f},{y1:.4f} L {x2:.4f},{y2:.4f}"
                    ET.SubElement(g, 'path', d=d, **common_attr)

            elif e.dxftype() == 'LWPOLYLINE':
                try:
                    entity_path = path.make_path(e)
                    raw_points = list(entity_path.flattening(3.0))
                    # 1. 缩放点坐标
                    scaled_pts = [scale_point(pt.x, pt.y) for pt in raw_points]
                    # 2. 执行连续点去重
                    clean_pts = filter_consecutive_points(scaled_pts)

                    # 3. 只有去重后剩余2个及以上有效点才生成路径
                    if len(clean_pts) >= 2:
                        d_path = f"M {clean_pts[0][0]:.4f},{clean_pts[0][1]:.4f}"
                        for p in clean_pts[1:]:
                            d_path += f" L {p[0]:.4f},{p[1]:.4f}"
                        if e.closed:
                            d_path += " Z"
                        ET.SubElement(g, 'path', d=d_path, **common_attr)
                except Exception as ex:
                    print(f"  [-] 解析 LWPOLYLINE 失败: {ex}")

            elif e.dxftype() == 'SPLINE':
                try:
                    raw_points = list(e.flattening(3.0))
                    scaled_pts = [scale_point(pt.x, pt.y) for pt in raw_points]
                    clean_pts = filter_consecutive_points(scaled_pts)

                    if len(clean_pts) >= 2:
                        d_path = f"M {clean_pts[0][0]:.4f},{clean_pts[0][1]:.4f}"
                        for p in clean_pts[1:]:
                            d_path += f" L {p[0]:.4f},{p[1]:.4f}"
                        if hasattr(e, 'closed') and e.closed:
                            d_path += " Z"
                        ET.SubElement(g, 'path', d=d_path, **common_attr)
                except Exception as ex:
                    print(f"  [-] 离散化解析 SPLINE 失败: {ex}")
                continue

            elif e.dxftype() == 'ARC':
                try:
                    p1_wcs = e.start_point
                    p2_wcs = e.end_point

                    x1, y1 = scale_point(p1_wcs.x, p1_wcs.y)
                    x2, y2 = scale_point(p2_wcs.x, p2_wcs.y)

                    r = scale_length(e.dxf.radius)

                    delta_angle = (e.dxf.end_angle - e.dxf.start_angle) % 360
                    large_arc = 1 if delta_angle > 180 else 0

                    sweep_flag = 1 if e.ocs().uz.z < 0 else 0

                    if abs(x1 - x2) > 1e-4 or abs(y1 - y2) > 1e-4:
                        d_path = f"M {x1:.4f},{y1:.4f} A {r:.4f},{r:.4f} 0 {large_arc} {sweep_flag} {x2:.4f},{y2:.4f}"
                        ET.SubElement(g, 'path', d=d_path, **common_attr)
                except Exception as ex:
                    print(f"  [-] 解析 ARC 失败: {ex}")
                continue

            elif e.dxftype() == 'CIRCLE':
                wcs_center = e.ocs().to_wcs(e.dxf.center)
                cx, cy = scale_point(wcs_center.x, wcs_center.y)
                r = scale_length(e.dxf.radius)
                ET.SubElement(g, 'circle', cx=f"{cx:.4f}", cy=f"{cy:.4f}", r=f"{r:.4f}", **common_attr)
                continue

            elif e.dxftype() in ("TEXT", "MTEXT"):
                content = str(e.plain_text() if hasattr(e, 'plain_text') else e.dxf.text)

                if e.dxftype() == "TEXT":
                    wcs_insert = e.ocs().to_wcs(e.dxf.insert)
                else:
                    wcs_insert = e.dxf.insert

                x, y = scale_point(wcs_insert.x, wcs_insert.y)
                height = scale_length(getattr(e.dxf, 'height', getattr(e.dxf, 'char_height', 100)))

                rotation = getattr(e.dxf, 'rotation', 0)
                if e.ocs().uz.z < 0:
                    rotation = -rotation

                text_elem = ET.SubElement(g, 'text', {
                    'x': f"{x:.4f}", 'y': f"{y:.4f}", 'font-size': f"{height:.4f}",
                    'fill': color_str, 'transform': f'rotate({-rotation:.4f} {x:.4f} {y:.4f})'
                })
                text_elem.text = content
                continue

            elif e.dxftype() == "ELLIPSE":
                try:
                    is_full = abs(e.dxf.end_param - e.dxf.start_param) >= (2 * math.pi - 1e-6)

                    if is_full:
                        cx, cy = scale_point(e.dxf.center.x, e.dxf.center.y)
                        vx, vy = e.dxf.major_axis.x, e.dxf.major_axis.y

                        rx = scale_length(math.hypot(vx, vy))
                        ry = rx * e.dxf.ratio

                        svg_angle_deg = math.degrees(math.atan2(-vy, vx))

                        ellipse_attr = {
                            'cx': f"{cx:.4f}",
                            'cy': f"{cy:.4f}",
                            'rx': f"{rx:.4f}",
                            'ry': f"{ry:.4f}",
                            **common_attr
                        }

                        if abs(svg_angle_deg) > 1e-4:
                            ellipse_attr['transform'] = f"rotate({svg_angle_deg:.4f} {cx:.4f} {cy:.4f})"

                        ET.SubElement(g, 'ellipse', ellipse_attr)
                    else:
                        points = list(e.flattening(3.0))

                        if len(points) >= 2:
                            p0 = scale_point(points[0].x, points[0].y)
                            d_path = f"M {p0[0]:.4f},{p0[1]:.4f}"
                            for pt in points[1:]:
                                pn = scale_point(pt.x, pt.y)
                                d_path += f" L {pn[0]:.4f},{pn[1]:.4f}"

                            ET.SubElement(g, 'path', d=d_path, **common_attr)
                except Exception as ex:
                    print(f"  [-] 解析 ELLIPSE 失败: {ex}")
                continue

    # 设置viewbox
    viewbox_width = 140
    viewbox_height = 140
    svg.attrib['viewBox'] = f"{0} {0} {viewbox_width} {viewbox_height}"

    # 开始全图递归处理
    process_entities(msp)

    # 保存 SVG 文件
    tree = ET.ElementTree(svg)
    tree.write(svg_path, xml_declaration=True)


def main():
    file_dir = "test"
    dxf_dir = os.path.join(settings.dxf_data_path, file_dir)
    svg_dir = os.path.join(settings.raw_svg_data_path, file_dir)

    os.makedirs(svg_dir, exist_ok=True)

    if not os.path.exists(dxf_dir):
        print(f"❌ 找不到输入文件夹: {dxf_dir}")
        return

    dxf_files = [f for f in os.listdir(dxf_dir) if f.lower().endswith('.dxf')]

    if not dxf_files:
        print(f"⚠️ 在 {dxf_dir} 中未找到任何 .dxf 文件。")
        return

    print(f"🚀 开始批量转换，共发现 {len(dxf_files)} 个 DXF 文件...\n")

    for idx, file_name in enumerate(dxf_files, 1):
        print(f"[{idx}/{len(dxf_files)}] 🔄 正在处理: {file_name}")
        input_path = os.path.join(dxf_dir, file_name)
        base_name = os.path.splitext(file_name)[0]

        if hasattr(svg_dir, "joinpath"):
            output_path = svg_dir / f"{base_name}.svg"
        else:
            output_path = os.path.join(svg_dir, f"{base_name}.svg")

        # try:
        convert_dxf_to_svg(input_path, str(output_path))
        print(f"✅ 转换成功: {output_path}\n")
        # except Exception as e:
        #     print(f"❌ 转换失败 {file_name}: {e}\n")

    print("🎉 批量转换任务全部完成！")


if __name__ == "__main__":
    main()