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
    parser = argparse.ArgumentParser(description="CAD Rule Checker - Main Entry")
    parser.add_argument("--config", default="src/config/settings.yaml", help="Path to config file")
    parser.add_argument("--mode", choices=["SINGLE", "BATCH"], default=None, help="Run mode: SINGLE or BATCH")
    parser.add_argument("--target-dir", default=None, help="Input SVG directory name")
    parser.add_argument("--target-file", default=None, help="Single SVG file name or path")
    parser.add_argument("--output-dir", default=None, help="Output directory for results")
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
    """Initialize the LLM client."""
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
            print(f"ERROR: Target file not found '{target_file}'")
            sys.exit(1)
        print(f"Starting single-drawing review: {target_file}")
        process_single_drawing(str(target_file), output_json_dir, validator, llm_client)

    elif run_mode == "BATCH":
        if not target_dir.exists() or not target_dir.is_dir():
            print(f"ERROR: Invalid or missing target directory '{target_dir}'")
            sys.exit(1)
        print(f"Starting batch review for directory: {target_dir}")
        process_directory(str(target_dir), output_json_dir, validator, llm_client)

    else:
        print(f"🛑 ERROR: Unknown run mode '{run_mode}'. Check RUN_MODE configuration.")


if __name__ == "__main__":
    main()