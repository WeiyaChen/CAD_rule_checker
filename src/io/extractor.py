# src/io/processor.py

from .svg_loader import load_svg
from .svg_modifier import modify_svg
from .svg_parser import parse_svg, parse_svg_texts


class ElementExtractor:
    """
    IO 处理流水线 (Facade Pattern)
    职责：管理文件的加载、清洗和解析，对外提供统一的提取接口。
    """

    def __init__(self, source_type="svg"):
        self.source_type = source_type

        # 可以在这里初始化一些复用的组件
        # 比如日志记录器，或者特定的配置

    def process(self, file_path):
        """
        执行标准 ElementExtractor 流程：Load -> Modify -> Parse
        :param file_path: 文件路径
        :return: 原始图元列表 (elements list)
        """

        # 1. Loading strategy (可以根据 source_type 切换)
        if self.source_type == 'svg':
            print("[svg_loader] 正在加载原始svg...")
            tree, primitives = load_svg(file_path)  # 获取xml树和图元列表
            print("[svg_loader] 加载完成!")

            print("[svg_modifier] 正在修改...")
            output_svg_path = modify_svg(file_path, tree, primitives)  # 运行修改器
            print("[svg_modifier] 修改完成!")
            print(f"[svg_modifier] 文件保存至{output_svg_path}")

            print("[svg_parser] 正在转换")
            print("[svg_loader] 正在加载有标签的svg")
            tree, primitives = load_svg(output_svg_path)
            print("[svg_loader] 加载完成")
            elements = parse_svg(tree, primitives)
            texts_elements = parse_svg_texts(tree)
            elements.extend(texts_elements)
            print("[svg_parser] 转换完成")
            return elements
        else:
            raise ValueError(f"Unsupported type: {self.source_type}")
