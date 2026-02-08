from locale import normalize

import ezdxf
import os
import math
from ezdxf import bbox
from ezdxf import colors
from collections import Counter
import xml.etree.ElementTree as ET

from numpy import cross


def get_entity_color(entity):
    # 优先 TrueColor（24位）
    if entity.dxf.hasattr("true_color"):
        r, g, b = colors.aci2rgb(entity.dxf.true_color)
        return (r, g, b)

    # 若为 ByLayer 或 ByBlock，需要读取图层颜色
    color_index = entity.dxf.color
    if color_index in (0, 256):  # ByBlock 或 ByLayer
        try:
            layer = entity.dxf.layer
            layer_obj = entity.doc.layers.get(layer)
            if layer_obj is not None:
                color_index = layer_obj.color
        except Exception:
            color_index = 7  # 默认白色

    # 转换 AutoCAD 颜色索引为 RGB
    r, g, b = colors.aci2rgb(color_index)

    # 亮度
    brightness = (0.299 * r + 0.587 * g + 0.114 * b)

    # 白色 → 黑色
    if (r, g, b) == (255, 255, 255):
        return 0, 0, 0

    # 太亮 → 压暗（保留颜色风格）
    if brightness > 200:
        factor = 0.5
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)

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
        # 2️⃣ 计算偏移，让图形居中
        new_w = s * (xmax - xmin)
        new_h = s * (ymax - ymin)
        offset_x = (140 - new_w) / 2
        offset_y = (140 - new_h) / 2

        # 3️⃣ 应用变换 + 翻转 y
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
    layers_color = {}
    layers = {}
    for e in msp:
        layer_name = e.dxf.layer
        if layer_name not in layers:
            layers[layer_name] = []
        layers[layer_name].append(e)

    # 变换坐标
    for layer_name, entities in layers.items():
        g = ET.SubElement(svg, 'g', id=layer_name)
        for e in entities:
            rgb_r, rgb_g, rgb_b = get_entity_color(e)
            color_str = f"rgb({rgb_r},{rgb_g},{rgb_b})"
            if e.dxftype() == 'LINE':
                x1, y1 = e.dxf.start.x, e.dxf.start.y
                x2, y2 = e.dxf.end.x, e.dxf.end.y
                if abs(x1 - x2) > 1e-6 or abs(y1 - y2) > 1e-6:
                    x1_new, y1_new = scale_point(x1, y1)
                    x2_new, y2_new = scale_point(x2, y2)
                    d = f"M {x1_new},{y1_new} L {x2_new},{y2_new}"
                else:
                    continue
                ET.SubElement(g, 'path', d=d,
                              fill="none", stroke=color_str, **{"stroke-width": "0.1"})

            elif e.dxftype() == 'LWPOLYLINE':
                points = e.get_points()
                if not points:
                    continue

                # 去除相邻重复点
                clean_points = []
                for p in points:
                    if not clean_points or (
                            abs(p[0] - clean_points[-1][0]) > 1e-6 or abs(p[1] - clean_points[-1][1]) > 1e-6):
                        clean_points.append(p)

                if len(clean_points) >= 2:
                    x0_new, y0_new = scale_point(clean_points[0][0], clean_points[0][1])
                    d = f"M {x0_new},{y0_new}"
                    for pt in clean_points[1:]:
                        x_new, y_new = scale_point(pt[0], pt[1])
                        d += f" L {x_new},{y_new}"

                # 如果 polyline 是闭合的，加上 Z
                if hasattr(e, 'closed') and e.closed:
                    d += " Z"

                ET.SubElement(g, 'path', d=d,
                              fill="none", stroke=color_str, **{"stroke-width": "0.1"})

            elif e.dxftype() == 'CIRCLE':
                cx, cy, r = e.dxf.center.x, e.dxf.center.y, e.dxf.radius
                cx, cy = scale_point(cx, cy)
                # 选较小的，保持完整显示
                r = scale_length(r)
                ET.SubElement(g, 'circle',
                              cx=str(cx), cy=str(cy), r=str(r),
                              fill="none", stroke=color_str, **{"stroke-width": "0.1"})

            elif e.dxftype() == "ARC":
                # 弧线转path
                cx, cy, r = e.dxf.center.x, e.dxf.center.y, e.dxf.radius
                start, end = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
                x1, y1 = cx + r * math.cos(start), cy + r * math.sin(start)
                x2, y2 = cx + r * math.cos(end), cy + r * math.sin(end)
                # 坐标转化
                x1, y1 = scale_point(x1, y1)
                x2, y2 = scale_point(x2, y2)
                r = scale_length(r)
                # 是否是大于180弧度
                delta_angle = (e.dxf.end_angle - e.dxf.start_angle) % 360
                large_arc = 1 if delta_angle > 180 else 0
                sweep_flag = 0
                d = f"M {x1} {y1} A {r} {r} 0 {large_arc} {sweep_flag} {x2} {y2}"
                ET.SubElement(g, 'path', d=d,
                              fill="none", stroke=color_str, **{"stroke-width": "0.1"})

            elif e.dxftype() == "TEXT":
                # 提取文本内容
                content = e.dxf.text
                # 提取插入点
                insert = e.dxf.insert
                x = insert.x
                y = insert.y
                # 坐标转换
                x, y = scale_point(x, y)
                # 提取文本高度
                height = e.dxf.height
                height = scale_length(height)
                # 提取旋转角度
                rotation = e.dxf.rotation

                # 构建SVG文本元素
                # 创建空元素
                text_elem = ET.SubElement(g, 'text')

                # 逐个设置属性
                text_elem.set('x', str(x))
                text_elem.set('y', str(y))
                text_elem.set('font-size', str(height))
                text_elem.set('transform', f'rotate({-rotation} {x} {y})')
                text_elem.set('fill', color_str)

                # 设置文本内容
                text_elem.text = content

            elif e.dxftype() == "ELLIPSE":
                # 中心与轴参数
                cx, cy = e.dxf.center.x, e.dxf.center.y
                rx = e.dxf.major_axis.magnitude
                ry = rx * e.dxf.ratio
                print(e.dxf.ratio)
                dxf_angle = math.degrees(math.atan2(e.dxf.major_axis.y, e.dxf.major_axis.x)) # 椭圆主轴的旋转角度，在dxf坐标系中正代表逆时针旋转
                svg_angle = -dxf_angle # 椭圆主轴的旋转角度，在dxf坐标系中负代表逆时针旋转

                # 起止参数（弧度）
                start_t = e.dxf.start_param
                end_t = e.dxf.end_param

                # 起点（局部坐标系）
                x1_local = rx * math.cos(start_t)
                y1_local = ry * math.sin(start_t)
                x2_local = rx * math.cos(end_t)
                y2_local = ry * math.sin(end_t)

                # 全局坐标系
                angle_rad = math.radians(dxf_angle)
                cos_angle = math.cos(angle_rad)
                sin_angle = math.sin(angle_rad)
                x1 = cx + x1_local * cos_angle - y1_local * sin_angle
                y1 = cy + x1_local * sin_angle + y1_local * cos_angle
                x2 = cx + x2_local * cos_angle - y2_local * sin_angle
                y2 = cy + x2_local * sin_angle + y2_local * cos_angle

                # DXF坐标系Y向上，SVG向下 → 翻转Y坐标
                x1, y1 = scale_point(x1, y1)
                x2, y2 = scale_point(x2, y2)
                cx, cy = scale_point(cx, cy)

                # rx和ry的缩放
                rx = scale_length(rx)
                ry = scale_length(ry)

                def is_full_ellipse(start_param, end_param, tolerance=1e-6):
                    """
                    判断椭圆弧是否构成完整的椭圆

                    参数:
                    - start_param: 起始参数（弧度）
                    - end_param: 结束参数（弧度）
                    - tolerance: 容差值，用于处理浮点数精度问题

                    返回:
                    - 布尔值，True表示是完整椭圆，False表示是椭圆弧
                    """
                    # 计算参数差值
                    param_diff = abs(end_param - start_param)

                    # 如果差值接近2π，则认为是完整椭圆
                    return abs(param_diff - 2 * math.pi) < tolerance

                if is_full_ellipse(start_t, end_t):
                    # 创建SVG椭圆元素
                    ellipse_attrs = {
                        'cx': f"{cx}",
                        'cy': f"{cy}",
                        'rx': f"{rx}",
                        'ry': f"{ry}",
                        'fill': 'none',
                        'stroke': color_str,
                        'stroke-width': '0.1'
                    }

                    # 如果有旋转角度，添加变换
                    if abs(svg_angle) > 1e-6:
                        ellipse_attrs['transform'] = f'rotate({svg_angle} {cx} {cy})'

                    ET.SubElement(g, 'ellipse', ellipse_attrs)

                else:
                    # 判断是否是大弧
                    delta_angle = end_t - start_t
                    if delta_angle < 0:
                        delta_angle += 2 * math.pi
                    large_arc_flag = 1 if delta_angle > math.pi else 0

                    # 默认方向：逆时针,椭圆弧的画线方向
                    # 转为向量
                    v1x, v1y = x1 - cx, y1 - cy
                    v2x, v2y = x2 - cx, y2 - cy

                    # 叉积
                    cross = v1x * v2y - v1y * v2x
                    sweep_flag = 0
                    if cross > 0: # 逆时针
                        sweep_flag = 1
                    elif cross < 0:
                        sweep_flag = 0

                    # 生成 SVG path 弧
                    d = (
                        f'M {x1} {y1} '
                        f'A {rx} {ry} {svg_angle} {large_arc_flag} {sweep_flag} {x2} {y2}'
                    )
                    print(d)
                    ET.SubElement(g, 'path', d=d, fill="none", stroke=color_str, **{"stroke-width": "0.1"})

                    # 设置viewbox
    viewbox_width = 140
    viewbox_height = 140
    svg.attrib['viewBox'] = f"{0} {0} {viewbox_width} {viewbox_height}"

    # 保存 SVG 文件
    tree = ET.ElementTree(svg)
    tree.write(svg_path, xml_declaration=True)

def main():
    input_path = "../../static/dxf/apartment.dxf"
    output_path = "../../static/svg/apartment.svg"
    convert_dxf_to_svg(input_path, output_path)

if __name__ == "__main__":
    main()

