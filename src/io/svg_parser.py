"""
svg_parser.py
--------------
模块功能：
- 读取带标签的 SVG 文件
- 提取每个图元的类型、实例ID、语义标签和坐标
- 输出列表，可用于生成结构化对象
"""

import os
import re

from lxml import etree
import numpy as np
from typing import List, Dict, Any

from svgpathtools import parse_path, Line, Arc

from src.config.labels import get_label_list


def parse_svg(tree, primitives) -> List[Dict[str, Any]]:
    """
    解析带标签的 SVG 文件，提取图元信息

    输出:
        List[Dict[str, Any]]: 每个元素为一个图元，包含字段：
            - type: str, 图元类型 ('wall', 'door', 'window', 'furniture')
            - instance_id: int
            - semantic_label: str
            - coords: np.ndarray, Nx2
    """

    scale = float(tree.getroot().attrib.get("scale"))  # dxf到svg的缩放比例

    elements = []
    label_list = get_label_list()

    # 只会是path, arc和ellipse
    for elem in primitives:
        tag = elem.tag.split('}')[-1]  # 去掉命名空间

        # 获取类型、语义、实例ID
        semantic_id = int(elem.get("semantic_label", "-1"))
        instance_id = int(elem.get("instance_label", "-1"))
        if semantic_id == -1 or instance_id == -1:
            semantic_label = "unknown"

        else:
            semantic_label = label_list[semantic_id]

        # 获取图元坐标
        coords = _parse_coords(elem, tag)
        coords = _transform_points(coords, scale)
        if coords is None:
            continue

        elements.append({
            'type': semantic_label,  # 或根据标签映射成 wall/door/window/furniture/None
            'instance_id': instance_id,
            'semantic_label': semantic_label,
            'coords': coords  # np.ndarray, Nx2
        })

    return elements


def parse_svg_texts(tree):
    root = tree.getroot()
    ns = root.tag[:-3]  # 命名空间
    scale = float(tree.getroot().attrib.get("scale"))  # dxf到svg的缩放比例

    texts = []
    # 分图层遍历
    for g in root.iter(ns + 'g'):
        for text in g.iter(ns + 'text'):
            texts.append(text)

    text_element = []
    for node in texts:
        content = "".join(node.itertext()).strip()

        # 1. 过滤
        # 过滤空标签或纯空白字符
        if not content:
            continue

        if len(content) < 2:
            continue

        if content == "热水器":
            continue

        if re.match(r'^[a-zA-Z0-9\.]+$', content):
            # 调试打印，看看过滤了什么 (可选)
            # print(f"[Filter] 过滤掉非语义标签: {content}")
            continue

        # -------------------------------------------------
        # 2. 提取坐标 (Coordinate Extraction)
        # -------------------------------------------------
        try:
            # 尝试直接从 <text> 属性获取
            raw_x = node.get('x')
            raw_y = node.get('y')
            # 3. 坐标清洗与整型化 (Integer Conversion)
            real_x, real_y = _transform_point((float(raw_x), float(raw_y)), scale)
            x = int(real_x)
            y = int(real_y)

            # 4. 构建标准对象
            element = {
                'type': 'text',
                'instance_id': -1,  # 文字通常不参与实例补丁，留空即可
                'semantic_label': 'room_label',  # 可以在这里加一个统一的子类型
                'text': content,  # 核心内容
                'coords': [x, y]  # 核心位置
            }
            text_element.append(element)

        except (ValueError, TypeError) as e:
            print(f"[Warning] 解析文字坐标失败，内容: '{content}', 错误: {e}")
            continue

    return text_element


def _parse_coords(elem: etree._Element, tag: str, n_points_curve: int = 20) -> np.ndarray:
    """
    解析 SVG 元素坐标，支持：
    - path（包含直线、贝塞尔曲线、圆弧）
    - circle
    - ellipse
    """
    if tag == "path":
        d_attr = elem.attrib.get("d", "")
        if not d_attr:
            return None
        path_obj = parse_path(d_attr)
        coords = _parse_path_coords(path_obj)
        return coords

    elif tag == "circle":
        cx = float(elem.get("cx", "0"))
        cy = float(elem.get("cy", "0"))
        r = float(elem.get("r", "0"))
        angles = np.linspace(0, 2 * np.pi, n_points_curve)
        coords = np.stack([cx + r * np.cos(angles), cy + r * np.sin(angles)], axis=1)
        return coords

    elif tag == "ellipse":
        cx = float(elem.get("cx", "0"))
        cy = float(elem.get("cy", "0"))
        rx = float(elem.get("rx", "0"))
        ry = float(elem.get("ry", "0"))
        angles = np.linspace(0, 2 * np.pi, n_points_curve)
        coords = np.stack([cx + rx * np.cos(angles), cy + ry * np.sin(angles)], axis=1)
        # 获取并应用 transform
        transform_str = elem.get("transform")
        if transform_str:
            coords = _apply_transform(coords, transform_str)

        return coords

    else:
        return None


def _parse_path_coords(path_obj, n_points_curve=20):
    """
    解析 SVG path 元素坐标
    - Line 段直接保留端点
    - Curve / Arc 均匀采样 n_points_curve 个点
    """
    coords = []

    for segment in path_obj:
        if isinstance(segment, Line):
            # 如果前面有点，避免重复添加起点
            if len(coords) == 0:
                coords.append([segment.start.real, segment.start.imag])
            coords.append([segment.end.real, segment.end.imag])
        elif isinstance(segment, Arc):
            # 对曲线/弧段采样
            for t in np.linspace(0, 1, n_points_curve):
                pt = segment.point(t)
                coords.append([pt.real, pt.imag])
        else:
            # 其他未知段，保守处理
            for t in np.linspace(0, 1, n_points_curve):
                pt = segment.point(t)
                coords.append([pt.real, pt.imag])

    return np.array(coords)


def _transform_points(coords: np.ndarray, scale: float, svg_height: float = 140) -> np.ndarray:
    """
    批量将 SVG 坐标转为 DXF 坐标
    coords: np.ndarray, shape (N,2)
    返回: np.ndarray, shape (N,2)
    """
    if coords is None or len(coords) == 0:
        return coords

    # 直接向量化处理
    coords = np.array(coords)  # 确保是 np.ndarray
    real_x = coords[:, 0] / scale
    real_y = (svg_height - coords[:, 1]) / scale
    return np.stack([real_x, real_y], axis=1)


def _transform_point(point, scale: float, svg_height: float = 140):
    x, y = point[0], point[1]
    real_x = x / scale
    real_y = (svg_height - y) / scale
    return real_x, real_y


def _parse_transform_str(transform_str):
    """
    解析 SVG transform 字符串并返回一个 3x3 变换矩阵。
    支持: matrix, translate, scale, rotate
    注意：SVG 变换顺序通常是从右到左应用，但矩阵乘法结合律允许我们按顺序累乘。
    """
    # 初始单位矩阵
    matrix = np.identity(3)

    if not transform_str:
        return matrix

    # 正则匹配类似于 'cmd(args)' 的结构
    transforms = re.findall(r'([a-z]+)\s*\(([^)]+)\)', transform_str.lower())

    for cmd, args in transforms:
        # 提取数值，处理逗号或空格分隔
        params = [float(x) for x in re.split(r'[,\s]+', args.strip()) if x]

        current_mat = np.identity(3)

        if cmd == 'translate':
            tx = params[0]
            ty = params[1] if len(params) > 1 else 0
            current_mat = np.array([
                [1, 0, tx],
                [0, 1, ty],
                [0, 0, 1]
            ])

        elif cmd == 'scale':
            sx = params[0]
            sy = params[1] if len(params) > 1 else sx
            current_mat = np.array([
                [sx, 0, 0],
                [0, sy, 0],
                [0, 0, 1]
            ])

        elif cmd == 'rotate':
            angle_deg = params[0]
            angle_rad = np.deg2rad(angle_deg)
            c = np.cos(angle_rad)
            s = np.sin(angle_rad)

            # 基础旋转矩阵
            rot_mat = np.array([
                [c, -s, 0],
                [s, c, 0],
                [0, 0, 1]
            ])

            # 如果有旋转中心 (rotate(angle, cx, cy))
            if len(params) == 3:
                cx, cy = params[1], params[2]
                # 步骤：移回原点 -> 旋转 -> 移回中心
                t1 = np.array([[1, 0, cx], [0, 1, cy], [0, 0, 1]])
                t2 = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]])
                current_mat = t1 @ rot_mat @ t2
            else:
                current_mat = rot_mat

        elif cmd == 'matrix':
            # SVG matrix(a, b, c, d, e, f) 对应:
            # [a c e]
            # [b d f]
            # [0 0 1]
            if len(params) == 6:
                a, b, c, d, e, f = params
                current_mat = np.array([
                    [a, c, e],
                    [b, d, f],
                    [0, 0, 1]
                ])

        # 累乘矩阵 (注意：新矩阵乘在右边还是左边取决于你的坐标是行向量还是列向量)
        # 这里假设 points @ matrix.T，所以变换顺序按照 SVG 字符串顺序左乘
        matrix = matrix @ current_mat

    return matrix


def _apply_transform(coords, transform_str):
    if not transform_str:
        return coords

    matrix = _parse_transform_str(transform_str)

    # 转换为齐次坐标 (N, 2) -> (N, 3)，增加一列 1
    ones = np.ones((coords.shape[0], 1))
    coords_homo = np.hstack([coords, ones])

    # 应用变换: (N, 3) dot (3, 3).T -> (N, 3)
    transformed_homo = coords_homo @ matrix.T

    # 返回 (N, 2)
    return transformed_homo[:, :2]


# if __name__ == "__main__":
#     # 测试示例
#     input_svg_name = "apartment.svg"  # svg文件名
#     input_svg_path = os.path.join(settings.raw_svg_data_path, input_svg_name)
#     print("[svg_loader] 正在加载原始svg...")
#     tree, primitives = load_svg(input_svg_path)  # 获取xml树和图元列表
#     print("[svg_loader] 加载完成!")
#     print("[svg_modifier] 正在修改...")
#     output_svg_path = modify_svg(input_svg_path, tree, primitives)  # 运行修改器
#     print("[svg_modifier] 修改完成!")
#     print(f"[svg_modifier] 文件保存至{output_svg_path}")
#
#     print(f"[svg_parser] 正在转换")
#     print(f"[svg_loader] 正在加载有标签的svg")
#     tree, primitives = load_svg(output_svg_path)
#     print(f"[svg_loader] 加载完成")
#     elements = parse_svg(tree, primitives)
#     print(f"[svg_parser] 转换完成")


