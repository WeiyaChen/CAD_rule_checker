import os
from rdflib import Graph
from pyshacl import validate
# 导入同目录下的生成器
from .rdf_generator import FloorPlanRDFGenerator
from ..config import config


class ComplianceChecker:
    def __init__(self, rule_file_name="phase1_basic.ttl"):
        self.rule_path = os.path.join(config.PROJECT_ROOT, "rules", rule_file_name)
        self.output_dir = os.path.join(config.PROJECT_ROOT, "output")

        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)

    def run_check(self, rooms_data, project_name="my_project"):
        print(f"--- 开始检查: {project_name} ---")

        # 1. 生成数据
        generator = FloorPlanRDFGenerator()
        data_graph = generator.generate_phase1_data(rooms_data, project_name)

        # 保存中间结果 (方便调试)
        output_ttl = os.path.join(self.output_dir, f"{project_name}_data.ttl")
        generator.save_to_file(output_ttl)

        # 2. 加载规则
        if not os.path.exists(self.rule_path):
            print(f"❌ 错误：找不到规则文件 {self.rule_path}")
            return False

        shacl_graph = Graph()
        shacl_graph.parse(self.rule_path, format="turtle")

        # 3. 验证
        conforms, _, report_text = validate(
            data_graph,
            shacl_graph=shacl_graph,
            inference='rdfs',
            serialize_report_graph=True
        )

        if conforms:
            print("✅ 检查通过！")
        else:
            print("❌ 发现违规项：")
            print(report_text)

        return conforms
