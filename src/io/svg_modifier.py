"""
svg_modifier.py
----------------
模块功能：
- 读取模型输出 pkl 文件（包含实例预测）
- 将语义标签和实例标签赋给对应 SVG 图元
- 保存修改后的 SVG 文件
- 返回修改后的 SVG 文件路径
"""

import os
import pickle
from pathlib import Path

from src.config.config import settings
from src.io.svg_loader import load_svg

import os
import pickle


# 假设 settings 已在文件头部导入

def modify_svg(input_svg_path, tree, primitives):
    # 1. 构造 pkl 文件路径
    input_svg_name = os.path.basename(input_svg_path)
    input_file_sem = os.path.splitext(input_svg_name)[0]

    # 获取文件夹名称
    input_svg_path_parse = Path(input_svg_path)
    folder_name = input_svg_path_parse.parent.name

    ins_save_path = os.path.join(settings.raw_pickle_data_path, folder_name, f"{input_file_sem}.pkl")

    if not os.path.exists(ins_save_path):
        raise FileNotFoundError(f"pkl 文件不存在: {ins_save_path}")

    # 读取实例预测结果
    with open(ins_save_path, "rb") as f:
        instances = pickle.load(f)

    # 2. 遍历 pkl 实例，注入预测结果
    for i, instance in enumerate(instances):
        masks = instance["masks"]
        labels = instance["labels"]
        scores = instance.get("scores", None)

        for j, mask in enumerate(masks):
            if mask:
                primitive = primitives[j]
                primitive.set("semantic_label", str(labels))
                primitive.set("instance_label", str(i))
                if scores is not None:
                    primitive.set("score", str(scores))

    # 4. 保存修改后的 SVG
    output_svg_name = f"{input_file_sem}_modified.svg"
    output_svg_path = os.path.join(settings.processed_svg_data_path, folder_name, output_svg_name)
    save_dest = Path(output_svg_path)
    # 确保父目录存在，不存在则自动创建
    save_dest.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_svg_path, pretty_print=True, xml_declaration=True, encoding="utf-8")
    return output_svg_path


# if __name__ == "__main__":
#     # 测试示例
#     input_svg_name = "apartment.svg"  # svg文件名
#     input_svg_path = os.path.join(settings.raw_svg_data_path, input_svg_name)
#     print("[svg_loader] 正在加载原始svg...")
#     tree, primitives = load_svg(input_svg_path)  # 获取xml树和图元列表
#     print("[svg_loader] 加载完成!")
#     print("[svg_modifier] 正在修改...")
#     output_svg_path = modify_svg(input_svg_path, tree, primitives)  # 运行修改器
#     print("[svg_modifier] 修改完成!")
#     print(f"[svg_modifier] 文件保存至{output_svg_path}")
