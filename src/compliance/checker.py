import json
from rdflib import Graph
from pyshacl import validate
from src.config.config import settings


class SimpleRuleChecker:
    def __init__(self, jsonld_path):
        self.data_graph = Graph()
        try:
            self.data_graph.parse(jsonld_path, format="json-ld")
            print(f"✅ 成功加载数据图谱: {jsonld_path} (包含 {len(self.data_graph)} 个三元组)")
        except Exception as e:
            print(f"❌ 加载 JSON-LD 失败: {e}")

    def _get_shacl_shapes(self):
        """
        定义简单的 SHACL 规则 (Turtle 格式)
        包含三类验证：
        1. 数据完整性 (Data Integrity): 必须有 ID, Type
        2. 几何合规 (Geometry): 面积必须 > 0
        3. 拓扑合规 (Topology): 房间必须有门 (或连接)
        """
        return settings.rules_dir / 'phase1_basic.ttl'


    def run_validation(self):
        """执行 SHACL 验证并打印报告"""
        print("\n🚀 开始执行 SHACL 规则验证...")

        # 加载规则图
        shacl_graph = Graph()
        rule_path = self._get_shacl_shapes()
        with open(rule_path, 'r', encoding='utf-8') as f:
            shacl_content = f.read()

        shacl_graph.parse(data=shacl_content, format="turtle")

        # 执行验证
        conforms, report_graph, report_text = validate(
            self.data_graph,
            shacl_graph=shacl_graph,
            inference='rdfs',
            abort_on_first=False,
            meta_shacl=False,
            debug=False
        )

        if conforms:
            print("🎉 恭喜！数据完全合规，未发现违规项。")
        else:
            print("⚠️ 发现违规项！验证报告如下：")
            print("=" * 60)
            print(report_text)  # 打印详细的文本报告
            print("=" * 60)

            # 你也可以把报告保存为文件
            with open("output/validation_report.txt", "w", encoding="utf-8") as f:
                f.write(report_text)
                print("📄 报告已保存至 output/validation_report.txt")


# --- 测试代码 ---
if __name__ == "__main__":
    # 假设你的 JSON-LD 文件路径是这个
    checker = SimpleRuleChecker(settings.output_jsonld_dir / "floorplan.jsonld")
    checker.run_validation()