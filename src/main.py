import os
import sys
import openai

# 引入配置与引擎
from src.config.config import settings
from src.compliance.shacl_engine import ShaclValidationEngine
from src.processor import process_single_drawing, process_directory


def setup_llm_client():
    """初始化大语言模型客户端"""
    LLM_API_KEY = "68c58c6b481a4d328d2fdf295240c1fb.Zt1Itx9ICDK5VIGB"
    llm_client = None
    if LLM_API_KEY:
        try:
            llm_client = openai.Client(api_key=LLM_API_KEY, base_url="https://open.bigmodel.cn/api/paas/v4/")
            print(f"🎉 大模型客户端初始成功！")
        except Exception as e:
            print(f"⚠️ 大模型客户端初始化失败: {e}，将使用沙盒降级模式。")
    return llm_client


def main():
    # =====================================================================
    # 1. 运行模式配置区 (直接在此处修改参数)
    # =====================================================================

    # RUN_MODE 可选值:
    #   "SINGLE"  : 处理单张特定的图纸
    #   "BATCH"   : 批量处理您指定的特定目录下的所有图纸
    #   "DEFAULT" : 批量处理系统 config.py 中配置的默认图纸目录
    RUN_MODE = "SINGLE"

    # 若 RUN_MODE = "SINGLE"，请在此指定单个 SVG 文件的路径
    TARGET_FILE_DIR = "test"
    FILE_NAME = "南阳名门150.svg"
    TARGET_FILE = os.path.join(settings.raw_svg_data_path, TARGET_FILE_DIR, FILE_NAME)

    # 若 RUN_MODE = "BATCH"，请在此指定包含多个 SVG 的文件夹路径
    TARGET_DIR = os.path.join(settings.raw_svg_data_path, TARGET_FILE_DIR)

    # =====================================================================
    # 2. 全局基础依赖初始化
    # =====================================================================
    output_json_dir = settings.exp_jsonld_dir

    os.makedirs(output_json_dir, exist_ok=True)

    validator = ShaclValidationEngine()
    llm_client = setup_llm_client()

    # =====================================================================
    # 3. 路由分发机制
    # =====================================================================
    if RUN_MODE == "SINGLE":
        if not os.path.exists(TARGET_FILE):
            print(f"🛑 错误：找不到指定的文件 '{TARGET_FILE}'")
            sys.exit(1)
        print(f"🚀 启动单图审查模式: {TARGET_FILE}")
        process_single_drawing(TARGET_FILE, output_json_dir, validator, llm_client)

    elif RUN_MODE == "BATCH":
        if not os.path.exists(TARGET_DIR) or not os.path.isdir(TARGET_DIR):
            print(f"🛑 错误：指定的目录无效或不存在 '{TARGET_DIR}'")
            sys.exit(1)
        print(f"🚀 启动指定目录批处理模式: {TARGET_DIR}")
        process_directory(TARGET_DIR, output_json_dir, validator, llm_client)

    elif RUN_MODE == "DEFAULT":
        default_dir = settings.raw_svg_data_path
        print(f"🚀 启动系统默认配置目录批处理模式: {default_dir}")
        if not os.path.exists(default_dir):
            print(f"🛑 错误：系统默认目录不存在 '{default_dir}'")
            sys.exit(1)
        process_directory(default_dir, output_json_dir, validator, llm_client)

    else:
        print(f"🛑 错误：未知的运行模式 '{RUN_MODE}'，请检查配置区的 RUN_MODE 设置。")


if __name__ == "__main__":
    main()