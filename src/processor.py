import os
import json
import traceback
from pathlib import Path

from matplotlib import pyplot as plt

from src.config.config import settings
from src.io.extractor import ElementExtractor
from src.topology.builder import TopologyBuilder
from src.enricher.enricher_pipeline import GraphEnrichmentPipeline
from src.config.labels import get_color
from src.utils.json_to_floorplan_viz import JSONLDVisualizer
from src.utils.svg_ins_viz import visualize_elements


def process_single_drawing(input_svg_path, output_json_dir, llm_client):
    """
    核心原子函数：端到端解析单张 CAD/SVG 图纸（对应评估实验 Exp 1-4）。
    流程：元素提取 → 拓扑白模型构建 → 全链路语义富化 → 可视化。
    SHACL 合规审查不在此执行，请使用 src/experiment/compliance_reviewer.py。
    返回: status_code (str) - "PASSED" 或 "ERROR"
    """
    svg_name = os.path.basename(input_svg_path)
    base_name = os.path.splitext(svg_name)[0]

    # 路径构造
    raw_jsonld_path = os.path.join(str(output_json_dir), f"{base_name}_raw.jsonld")
    enriched_jsonld_path = os.path.join(str(output_json_dir), f"{base_name}.jsonld")
    exp_viz_path = os.path.join(str(settings.viz_dir), f"{base_name}_topology.png")

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

        print(">>> Phase 3: Generating knowledge graph topology visualization...")
        try:
            viz = JSONLDVisualizer(enriched_jsonld_path)
            viz.parse_graph()
            viz.draw(output_path=exp_viz_path)
            plt.close('all')  # 强制释放画布，防止批量处理时引发内存溢出 (OOM)
        except Exception as e:
            print(f"  ⚠️ Graph visualization generation failed: {e}")

        print(f"\n🎉 解析完成：图纸 {svg_name} 已生成富化图谱与可视化。")
        return "PASSED"

    except Exception as e:
        error_details = traceback.format_exc()
        print(f"\n⚠️ 🚨 Drawing {svg_name} encountered a critical error in pipeline, skipping.")
        print("=" * 60)
        print(error_details)
        print("=" * 60 + "\n")
        return "ERROR"


def process_directory(svg_dir, output_json_dir, llm_client):
    """
    批量模式：处理指定目录下的所有图纸（仅解析，对应 Exp 1-4）
    """
    svg_files = [f for f in os.listdir(svg_dir) if f.endswith('.svg')]

    if not svg_files:
        print(f"🛑 No SVG files found in directory {svg_dir}, exiting.")
        return

    print(f"🔍 Found {len(svg_files)} drawings to review, starting automated batch pipeline...\n")

    total_files = len(svg_files)
    passed_files = 0
    error_files = 0

    for svg_name in svg_files:
        input_svg_path = os.path.join(svg_dir, svg_name)
        status = process_single_drawing(
            input_svg_path, output_json_dir, llm_client
        )

        if status == "PASSED":
            passed_files += 1
        else:
            error_files += 1

    # 输出全局汇总统计报告
    print("\n" + "★" * 60)
    print("📊 Batch parsing complete!")
    print(f"Total drawings processed: {total_files}")
    print(f"✅ Parsed successfully: {passed_files}")
    if error_files > 0:
        print(f"⚠️ Errors: {error_files}")
    print("★" * 60)