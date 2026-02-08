import os

from src.compliance.checker import ComplianceChecker
from src.config.config import settings
from src.config.labels import get_color
from src.io.extractor import ElementExtractor
from src.topology.builder import TopologyBuilder
from src.utils.visualize import visualize_elements


if __name__ == "__main__":
    input_svg_name = "apartment.svg"  # svg文件名
    input_svg_path = os.path.join(settings.raw_svg_data_path, input_svg_name)  # svg路径

    # 1.提取svg文件中的元素
    print(">>> 阶段 1: 正在识别元素...")
    extractor = ElementExtractor()
    elements = extractor.process(input_svg_path)
    color = get_color()
    visualize_elements(elements, color)

    # 2.拓扑重建
    print(">>> 阶段 2: 正在构建拓扑...")
    topology_builder = TopologyBuilder()
    result = topology_builder.build(elements)

    #

    # 3.ttl文件构建
    print(">>> 阶段 3: 正在进行合规检查...")
    # 实例化检查器，指向第一阶段的规则
    checker = ComplianceChecker(rule_file_name="phase1_basic.ttl")

    # 传入识图结果
    checker.run_check(result)
