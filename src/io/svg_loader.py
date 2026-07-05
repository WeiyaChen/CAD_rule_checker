"""
svg_loader.py
----------------
模块功能：
- 读取svg文件，返回:
- tree：xml树
- primitives：所有会被模型预测的图元列表
"""
import os

from lxml import etree


def load_svg(input_svg_path):
    # 解析源 SVG 文件
    tree = etree.parse(input_svg_path)
    root = tree.getroot()
    ns = root.tag[:-3]  # 命名空间

    # 找出所有有预测结果的图元（忽略命名空间），只有path，circle和ellipse图元会有预测结果，text没有
    primitives = []
    # 分图层遍历
    for g in root.iter(ns + 'g'):
        # path
        for path in g.iter(ns + 'path'):
            primitives.append(path)
        # circle
        for circle in g.iter(ns + 'circle'):
            primitives.append(circle)
        # ellipse
        for ellipse in g.iter(ns + 'ellipse'):
            primitives.append(ellipse)
    return tree, primitives

