"""
svg_modifier.py
----------------
Module:
- Read model output pkl file (with instance predictions)
- Assign semantic / instance labels to corresponding SVG primitives
- Save the modified SVG file
- Return the modified SVG file path
"""

import os
import pickle
from pathlib import Path

from src.config.config import settings
from src.io.svg_loader import load_svg


def modify_svg(input_svg_path, tree, primitives):
    # 1. Build pkl file path
    input_svg_name = os.path.basename(input_svg_path)
    input_file_sem = os.path.splitext(input_svg_name)[0]

    ins_save_path = os.path.join(settings.pickle_dir, f"{input_file_sem}.pkl")

    if not os.path.exists(ins_save_path):
        raise FileNotFoundError(f"pkl file not found: {ins_save_path}")

    # Read instance prediction results
    with open(ins_save_path, "rb") as f:
        instances = pickle.load(f)

    # 2. Iterate over pkl instances and inject predictions
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

    # 3. Save modified SVG
    output_svg_name = f"{input_file_sem}_modified.svg"
    output_svg_path = os.path.join(settings.processed_dir, output_svg_name)
    save_dest = Path(output_svg_path)
    save_dest.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output_svg_path, pretty_print=True, xml_declaration=True, encoding="utf-8")
    return output_svg_path


# if __name__ == "__main__":
#     # Test example
#     input_svg_name = "apartment.svg"
#     input_svg_path = os.path.join(settings.svg_dir, input_svg_name)
#     print("[svg_loader] Loading raw SVG...")
#     tree, primitives = load_svg(input_svg_path)
#     print("[svg_loader] Load complete!")
#     print("[svg_modifier] Modifying...")
#     output_svg_path = modify_svg(input_svg_path, tree, primitives)
#     print("[svg_modifier] Modification complete!")
#     print(f"[svg_modifier] File saved to {output_svg_path}")
