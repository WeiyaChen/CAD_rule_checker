import argparse
import os
import sys
from pathlib import Path

import openai

# 引入配置与引擎
from src.config.config import Settings
from src.compliance.shacl_engine import ShaclValidationEngine
from src.processor import process_single_drawing, process_directory


def parse_args():
    parser = argparse.ArgumentParser(description="CAD 规则检查主入口")
    parser.add_argument("--config", default="src/config/settings.yaml", help="配置文件路径")
    parser.add_argument("--mode", choices=["SINGLE", "BATCH"], default=None, help="运行模式")
    parser.add_argument("--target-dir", default=None, help="输入 SVG 目录")
    parser.add_argument("--target-file", default=None, help="单张 SVG 文件名或路径")
    parser.add_argument("--output-dir", default=None, help="结果输出目录")
    args, _ = parser.parse_known_args()

    settings = Settings(config_file=args.config)
    parser.set_defaults(
        mode=args.mode or settings.run_mode,
        target_dir=args.target_dir or settings.runtime_target_dir,
        target_file=args.target_file or settings.runtime_target_file,
        output_dir=args.output_dir or str(settings.runtime_output_dir),
    )
    return parser.parse_args()


def setup_llm_client(settings_obj):
    """初始化大语言模型客户端"""
    llm_client = None
    api_key = settings_obj.llm_api_key
    base_url = settings_obj.llm_base_url
    if api_key:
        try:
            llm_client = openai.Client(api_key=api_key, base_url=base_url)
            print("大模型客户端初始化成功！")
        except Exception as e:
            print(f"大模型客户端初始化失败: {e}，将使用沙盒降级模式。")
    else:
        print("未配置大模型 API Key，将使用沙盒降级模式。")
    return llm_client


def main():
    args = parse_args()
    settings = Settings(config_file=args.config)
    run_mode = args.mode.upper()

    target_file = settings.resolve_runtime_target_path(target_dir=args.target_dir, target_file=args.target_file)
    target_dir = settings.resolve_runtime_input_dir(target_dir=args.target_dir)
    output_json_dir = Path(args.output_dir) if args.output_dir else settings.runtime_output_dir

    output_json_dir.mkdir(parents=True, exist_ok=True)

    validator = ShaclValidationEngine()
    llm_client = setup_llm_client(settings)

    if run_mode == "SINGLE":
        if not target_file.exists():
            print(f"错误：找不到指定的文件 '{target_file}'")
            sys.exit(1)
        print(f"启动单图审查模式: {target_file}")
        process_single_drawing(str(target_file), output_json_dir, validator, llm_client)

    elif run_mode == "BATCH":
        if not target_dir.exists() or not target_dir.is_dir():
            print(f"错误：指定的目录无效或不存在 '{target_dir}'")
            sys.exit(1)
        print(f"启动指定目录批处理模式: {target_dir}")
        process_directory(str(target_dir), output_json_dir, validator, llm_client)

    else:
        print(f"🛑 错误：未知的运行模式 '{run_mode}'，请检查配置区的 RUN_MODE 设置。")


if __name__ == "__main__":
    main()