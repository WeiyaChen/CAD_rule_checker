"""
实验入口 1：图纸解析流水线（对应评估实验 Exp 1-4）
====================================================
对 DXF/SVG 图纸进行端到端解析，产出富化 JSON-LD 知识图谱与可视化：

    Phase 1      元素提取           -> 对应 Exp 1 几何轮廓提取
    Phase 2      拓扑白模型构建     -> 对应 Exp 2 拓扑连通
    Phase 2.5    全链路语义富化     -> 对应 Exp 3/4 几何计算与语义推理
    Phase 3      拓扑可视化

说明：
- SHACL 合规审查（Exp 5）不在此入口执行，请使用 compliance_reviewer.py。
- 本入口与 src/main.py 的解析逻辑一致，独立提供实验级入口以便与评估
  流程严格对齐（解析只覆盖评估的前四步）。
"""

import argparse
import sys
from pathlib import Path

# Windows 控制台默认 GBK 编码，强制 UTF-8 输出避免表情符号触发 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import openai

from src.config.config import Settings
from src.processor import process_single_drawing, process_directory


def setup_llm_client(settings_obj):
    """Initialize the LLM client (used by the parsing pipeline)."""
    llm_client = None
    api_key = settings_obj.llm_api_key
    base_url = settings_obj.llm_base_url
    if api_key:
        try:
            llm_client = openai.Client(api_key=api_key, base_url=base_url)
            print("LLM client initialized successfully!")
        except Exception as e:
            print(f"LLM client initialization failed: {e}, falling back to sandbox mode.")
    else:
        print("No LLM API Key configured, using sandbox fallback mode.")
    return llm_client


def parse_args():
    parser = argparse.ArgumentParser(description="Parsing Pipeline (Exp 1-4)")
    parser.add_argument("--config", default="src/config/settings.yaml", help="Path to config file")
    parser.add_argument("--mode", choices=["SINGLE", "BATCH"], default=None, help="Run mode")
    parser.add_argument("--target-dir", default=None, help="SVG input directory name")
    parser.add_argument("--target-file", default=None, help="Single SVG file name or path")
    parser.add_argument("--output-dir", default=None, help="Output directory for enriched JSON-LD")
    parser.add_argument("--contour-algo", default=None,
                        help="Spatial contour extraction algorithm (default: settings.yaml)")
    parser.add_argument("--classifier-algo", default=None,
                        help="Space type recognition algorithm (default: settings.yaml)")
    parser.add_argument("--list-algos", action="store_true",
                        help="List registered spatial algorithms and exit")
    args, _ = parser.parse_known_args()

    if args.list_algos:
        from src.spatial.factory import (
            available_classifier_algorithms,
            available_contour_algorithms,
        )

        print("Contour extractors      : " + ", ".join(available_contour_algorithms()))
        print("Space type classifiers  : " + ", ".join(available_classifier_algorithms()))
        sys.exit(0)

    settings = Settings(config_file=args.config)
    parser.set_defaults(
        mode=args.mode or settings.run_mode,
        target_dir=args.target_dir or settings.runtime_target_dir,
        target_file=args.target_file or settings.runtime_target_file,
        output_dir=args.output_dir or str(settings.runtime_output_dir),
        contour_algo=args.contour_algo or settings.spatial_contour_algorithm,
        classifier_algo=args.classifier_algo or settings.spatial_classifier_algorithm,
    )
    return parser.parse_args(), settings


def main():
    args, settings = parse_args()
    run_mode = args.mode.upper()

    target_file = settings.resolve_runtime_target_path(target_dir=args.target_dir, target_file=args.target_file)
    target_dir = settings.resolve_runtime_input_dir(target_dir=args.target_dir)
    output_json_dir = Path(args.output_dir)
    output_json_dir.mkdir(parents=True, exist_ok=True)

    llm_client = setup_llm_client(settings)

    if run_mode == "SINGLE":
        if not target_file.exists():
            print(f"ERROR: Target file not found '{target_file}'")
            sys.exit(1)
        print(f"Starting single-drawing parsing: {target_file}")
        process_single_drawing(
            str(target_file), output_json_dir, llm_client,
            contour_algorithm=args.contour_algo,
            classifier_algorithm=args.classifier_algo,
        )

    elif run_mode == "BATCH":
        if not target_dir.exists() or not target_dir.is_dir():
            print(f"ERROR: Invalid or missing target directory '{target_dir}'")
            sys.exit(1)
        print(f"Starting batch parsing for directory: {target_dir}")
        process_directory(
            str(target_dir), output_json_dir, llm_client,
            contour_algorithm=args.contour_algo,
            classifier_algorithm=args.classifier_algo,
        )

    else:
        print(f"🛑 ERROR: Unknown run mode '{run_mode}'.")


if __name__ == "__main__":
    main()
