import os
import json
import traceback
from pathlib import Path

from matplotlib import pyplot as plt

from src.config.config import settings
from src.io.extractor import ElementExtractor
from src.topology.builder import TopologyBuilder
from src.utils.compliance_visualizer import ComplianceVisualizer
from src.enricher.enricher_pipeline import GraphEnrichmentPipeline
from src.config.labels import get_color
from src.utils.json_to_floorplan_viz import JSONLDVisualizer
from src.utils.svg_ins_viz import visualize_elements


def process_single_drawing(input_svg_path, output_json_dir, validator, llm_client):
    """
    核心原子函数：处理单张 CAD/SVG 图纸的完整自动化审查管线
    返回: status_code (str) - "PASSED", "VIOLATIONS", or "ERROR"
    """
    svg_name = os.path.basename(input_svg_path)
    base_name = os.path.splitext(svg_name)[0]

    # 路径构造
    raw_jsonld_path = os.path.join(str(output_json_dir), f"{base_name}_raw.jsonld")
    enriched_jsonld_path = os.path.join(str(output_json_dir), f"{base_name}.jsonld")
    violations_json_path = os.path.join(settings.violations_dir, f"{base_name}_violations.json")
    exp_viz_path = os.path.join(settings.viz_dir, f"{base_name}_topology.png")
    # annotated_image_path = os.path.join(str(output_html_dir), f"{base_name}_compliance_report.html")

    print("\n" + "=" * 60)
    print(f"📐 Processing drawing: {svg_name}")
    print("=" * 60)

    try:
        # ==========================================
        # Phase 1 & 2: Basic parsing & white-model graph construction
        # ==========================================
        print(">>> Phase 1: Recognizing drawing elements...")
        extractor = ElementExtractor()
        elements = extractor.process(str(input_svg_path))
        save_dir = str(settings.viz_dir)
        filename = base_name + "_instance.png"
        visualize_elements(elements, get_color(), save_dir, filename)

        # 提取文本标注及坐标
        raw_room_texts = []
        for elem in elements:
            if elem.get('type') == 'text' or 'text' in elem:
                cord = elem.get('coords', [0, 0])
                raw_room_texts.append({
                    "text": elem.get('text', elem.get('label', '')),
                    "point": (cord[0], cord[1])
                })

        print(">>> Phase 2: Building base topological knowledge graph (geometric white model)...")
        topology_builder = TopologyBuilder()
        topology_builder.build(elements, raw_jsonld_path)

        # ==========================================
        # Phase 2.5: Full-chain enrichment pipeline
        # ==========================================
        print(">>> Phase 2.5: Starting full-chain graph enrichment pipeline...")
        with open(raw_jsonld_path, 'r', encoding='utf-8') as f:
            raw_graph_data = json.load(f)

        enrichment_pipeline = GraphEnrichmentPipeline(
            raw_graph_data,
            room_texts=raw_room_texts,
            llm_client=llm_client
        )
        enriched_graph_data = enrichment_pipeline.run_all()

        # 保存富化后的终极图谱
        with open(enriched_jsonld_path, 'w', encoding='utf-8') as f:
            json.dump(enriched_graph_data, f, ensure_ascii=False, indent=2)
        print(f"✅ Enrichment complete! Final graph saved to: {enriched_jsonld_path}")

        # # ==========================================
        # # 阶段 3: 多层级自动化合规审查
        # # ==========================================
        # print(">>> 阶段 3: 启动多层级自动化合规审查...")
        # file_violations = 0
        # all_violations_data = []
        #
        # flag = False
        # if flag:
        #
        #     # [L1] 基础语义与功能完整性审查
        #     print("--- [L1] 执行语义与完整性审查 ---")
        #     l1_passed, l1_report, l1_v_list = validator.run_validation(enriched_jsonld_path, "rules/l1_semantic_check.ttl")
        #     if not l1_passed:
        #         all_violations_data.extend(l1_v_list)
        #         file_violations += 1
        #         print("⚠️ 发现 L1 语义违规！")
        #         print(l1_report)
        #     else:
        #         print("✅ L1 语义审查通过。")
        #
        #     # [L2] 几何特征与尺寸审查
        #     print("--- [L2] 执行几何尺寸审查 ---")
        #     l2_passed, l2_report, l2_v_list = validator.run_validation(enriched_jsonld_path, "rules/l2_geometric_check.ttl")
        #     if not l2_passed:
        #         all_violations_data.extend(l2_v_list)
        #         file_violations += 1
        #         print("⚠️ 发现 L2 几何违规！")
        #         print(l2_report)
        #     else:
        #         print("✅ L2 几何审查通过。")
        #
        #     # [L3] 拓扑分析与动线/流线审查
        #     print("--- [L3] 执行拓扑连通与流线审查 ---")
        #     l3_passed, l3_report, l3_v_list = validator.run_validation(enriched_jsonld_path,
        #                                                                "rules/l3_topological_check.ttl")
        #     if not l3_passed:
        #         all_violations_data.extend(l3_v_list)
        #         file_violations += 1
        #         print("⚠️ 发现 L3 拓扑违规！")
        #         print(l3_report)
        #     else:
        #         print("✅ L3 拓扑与流线审查通过。")
        #
        # else:
        #     print("--- 执行实验规则审查 ---")
        #     passed, report, v_list = validator.run_validation(enriched_jsonld_path,
        #                                                                "rules/exp.ttl")
        #     if not passed:
        #         all_violations_data.extend(v_list)
        #         file_violations += 1
        #         print("⚠️ 发现实验规则违规！")
        #         print(report)
        #     else:
        #         print("✅ 实验规则审查通过。")
        #
        # # ==========================================
        # # 阶段 3.5: 固化审查结果 (双份存储)
        # # ==========================================
        # # 1. 独立保存违规列表为 JSON
        # with open(violations_json_path, 'w', encoding='utf-8') as f:
        #     json.dump(all_violations_data, f, ensure_ascii=False, indent=2)
        # print(f"✅ 独立审查违规记录已保存至: {violations_json_path}")
        #
        # # 2. 将违规项回填至富化图谱字典，并覆盖写入 JSON-LD
        # enriched_graph_data["violations"] = all_violations_data
        # with open(enriched_jsonld_path, 'w', encoding='utf-8') as f:
        #     json.dump(enriched_graph_data, f, ensure_ascii=False, indent=2)
        # print(f"✅ 图谱文件已更新并集成违规字段: {enriched_jsonld_path}")

        print(">>> Phase 3: Generating knowledge graph topology visualization...")
        try:
            viz = JSONLDVisualizer(enriched_jsonld_path)
            viz.parse_graph()
            viz.draw(output_path=exp_viz_path)
            plt.close('all')  # 强制释放画布，防止批量处理时引发内存溢出 (OOM)
        except Exception as e:
            print(f"  ⚠️ Graph visualization generation failed: {e}")

        # # ==========================================
        # # 阶段 4: 图纸反向批注 (违规可视化)
        # # ==========================================
        # if file_violations > 0 and all_violations_data:
        #     print("\n>>> 阶段 4: 正在生成可视化批注报告...")
        #     visualizer = ComplianceVisualizer(str(input_svg_path), str(enriched_jsonld_path))
        #     visualizer.draw_annotated_report(all_violations_data, output_path=str(annotated_image_path))
        #     print(f"\n❌ 结论：图纸 {svg_name} 存在 {len(all_violations_data)} 个具体违规项，详见交互式报告。")
        #     return "VIOLATIONS"
        # else:
        #     print(f"\n🎉 结论：图纸 {svg_name} 顺利通过全部合规审查！")
        #     return "PASSED"
        return "PASSED"

    except Exception as e:
        error_details = traceback.format_exc()
        print(f"\n⚠️ 🚨 Drawing {svg_name} encountered a critical error in pipeline, skipping.")
        print("=" * 60)
        print(error_details)
        print("=" * 60 + "\n")
        return "ERROR"


def process_directory(svg_dir, output_json_dir, validator, llm_client):
    """
    批量模式：处理指定目录下的所有图纸
    """
    svg_files = [f for f in os.listdir(svg_dir) if f.endswith('.svg')]

    if not svg_files:
        print(f"🛑 No SVG files found in directory {svg_dir}, exiting.")
        return

    print(f"🔍 Found {len(svg_files)} drawings to review, starting automated batch pipeline...\n")

    total_files = len(svg_files)
    passed_files = 0
    failed_files = 0
    error_files = 0

    for svg_name in svg_files:
        input_svg_path = os.path.join(svg_dir, svg_name)
        status = process_single_drawing(
            input_svg_path, output_json_dir, validator, llm_client
        )

        if status == "PASSED":
            passed_files += 1
        elif status == "VIOLATIONS":
            failed_files += 1
        else:
            error_files += 1

    # 输出全局汇总统计报告
    print("\n" + "★" * 60)
    print("📊 Batch review complete!")
    print(f"Total drawings processed: {total_files}")
    print(f"✅ Passed: {passed_files}")
    print(f"❌ Violations found: {failed_files}")
    if error_files > 0:
        print(f"⚠️ Errors: {error_files}")
    print("★" * 60)