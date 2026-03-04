import os
import sys
import traceback
# 假设你已经将我们之前写的类放入了 src.compliance 包中
from src.compliance.shacl_engine import ShaclValidationEngine
from src.compliance.geometric_checker import GeometryChecker
from src.config.config import settings
from src.io.extractor import ElementExtractor
from src.topology.builder import TopologyBuilder


# from src.compliance.topological_checker import TopologicalChecker


def main():
    svg_dir = settings.raw_svg_data_path
    output_json_dir = settings.output_jsonld_dir
    output_html_dir = settings.output_html_dir

    # 获取目录下所有的 SVG 文件
    svg_files = [f for f in os.listdir(svg_dir) if f.endswith('.svg')]

    if not svg_files:
        print(f"🛑 在目录 {svg_dir} 中未找到任何 SVG 文件，程序退出。")
        sys.exit(0)

    print(f"🔍 共发现 {len(svg_files)} 份待审查的图纸，正在启动自动化批处理流水线...\n")

    # 初始化全局验证引擎，由于它是无状态的，在循环外实例化一次即可复用
    validator = ShaclValidationEngine()

    # 初始化全局统计变量
    total_files = len(svg_files)
    passed_files = 0
    failed_files = 0

    for svg_name in svg_files:
        input_svg_path = os.path.join(svg_dir, svg_name)
        # 动态生成输出的 JSON-LD 文件名，保持与输入图纸同名
        base_name = os.path.splitext(svg_name)[0]
        jsonld_output_path = output_json_dir / f"{base_name}.jsonld"
        html_output_path = output_html_dir/ f"{base_name}.html"

        print("\n" + "=" * 60)
        print(f"📐 正在处理并审查图纸: {svg_name}")
        print("=" * 60)

        try:
            print(">>> 阶段 1: 正在识别图纸元素...")
            extractor = ElementExtractor()
            elements = extractor.process(input_svg_path)

            print(">>> 阶段 2: 正在构建拓扑与知识图谱...")
            topology_builder = TopologyBuilder()
            topology_builder.build(elements, str(jsonld_output_path), str(html_output_path))

        except Exception as e:
            # 利用 traceback 捕获并格式化完整的堆栈报错信息（包含文件名和精准行号）
            error_details = traceback.format_exc()
            print(f"\n⚠️ 🚨 图纸 {svg_name} 在前端解析阶段发生严重异常，已跳过该文件。")
            print("👇 详细的代码行数定位与报错堆栈如下：")
            print("=" * 60)
            print(error_details)
            print("=" * 60 + "\n")

            failed_files += 1
            continue

        print(">>> 阶段 3: 启动多层级自动化合规审查...")
        file_violations = 0

        # [L1层] 基础语义审查
        print("--- [L1] 执行语义结构审查 ---")
        l1_passed, l1_report = validator.run_validation(jsonld_output_path, "rules/l1_semantic_check.ttl")
        if not l1_passed:
            print("⚠️ 发现 L1 语义违规，图谱结构不完整，跳过后续几何与拓扑推演！详细报告：\n", l1_report)
            failed_files += 1
            continue
        print("✅ L1 语义审查通过。")

        # [L2层] 几何特征富化与尺寸审查
        print("--- [L2] 执行几何尺寸审查 ---")
        geo_checker = GeometryChecker(jsonld_output_path)
        geo_checker.run_all_enrichments()

        l2_passed, l2_report = validator.run_validation(jsonld_output_path, "rules/l2_geometric_check.ttl")
        if not l2_passed:
            print("⚠️ 发现 L2 几何违规！详细报告：\n", l2_report)
            file_violations += 1
        else:
            print("✅ L2 几何审查通过。")

        # [L3层] 拓扑分析与连通性审查
        print("--- [L3] 执行拓扑连通审查 ---")
        # topo_checker = TopologicalChecker(jsonld_output_path)
        # topo_checker.run_all_enrichments()

        l3_passed, l3_report = validator.run_validation(jsonld_output_path, "rules/l3_topological_check.ttl")
        if not l3_passed:
            print("⚠️ 发现 L3 拓扑违规！详细报告：\n", l3_report)
            file_violations += 1
        else:
            print("✅ L3 拓扑审查通过。")

        # 单文件结论核算
        if file_violations == 0:
            print(f"\n🎉 结论：图纸 {svg_name} 顺利通过全部合规审查！")
            passed_files += 1
        else:
            print(f"\n❌ 结论：图纸 {svg_name} 存在 {file_violations} 个层级的违规项。")
            failed_files += 1

    # 输出全局汇总统计报告
    print("\n" + "★" * 60)
    print("📊 批量审查任务全部完成！")
    print(f"共计处理图纸: {total_files} 份")
    print(f"✅ 完全合规图纸: {passed_files} 份")
    print(f"❌ 存在违规图纸: {failed_files} 份")
    print("★" * 60)


if __name__ == "__main__":
    main()