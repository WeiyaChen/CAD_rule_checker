"""
实验入口 2：独立 SHACL 合规审查（对应评估实验 Exp 5）
====================================================
对已经解析并富化好的 JSON-LD 知识图谱（默认 output/jsonld/）执行
L1 语义 / L2 几何 / L3 拓扑 三级合规审查，产出：

    - output/violations/<base>_violations.json      系统违规报告
    - output/html/<base>_compliance_report.html     交互式批注报告

说明：
- 本入口不进行图纸解析（解析请用 parsing_pipeline.py），它只消费
  富化 JSON-LD，因此可以与解析完全解耦地独立运行。
- 系统违规报告文件名与数据集评估器 (dataset_evaluator.py) 期望的
  <base>_violations.json 一致，可直接用于 Exp 5 合规对比。
"""

import argparse
import json
import sys
from pathlib import Path

# Windows 控制台默认 GBK 编码，强制 UTF-8 输出避免表情符号触发 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.config.config import settings
from src.compliance.shacl_engine import ShaclValidationEngine
from src.utils.compliance_visualizer import ComplianceVisualizer

# 合规规则：(标签, 规则文件名)
COMPLIANCE_RULES = [
    ("L1", "l1_semantic_check.ttl"),
    ("L2", "l2_geometric_check.ttl"),
    ("L3", "l3_topological_check.ttl"),
]


def _resolve_svg(base_name):
    """定位原始 SVG 图纸作为批注底图（可选，找不到则跳过）。"""
    svg_dir = Path(settings.svg_dir)
    for name in (f"{base_name}.svg", f"{base_name}_modified.svg"):
        cand = svg_dir / name
        if cand.exists():
            return str(cand)
    return ""


def review_single(jsonld_path, save_html=True):
    """对单个富化 JSON-LD 执行 L1/L2/L3 合规审查。

    返回: (status, violations)  status 为 "VIOLATIONS" 或 "PASSED"
    """
    jsonld_path = Path(jsonld_path)
    base_name = jsonld_path.stem
    violations_path = Path(settings.violations_dir) / f"{base_name}_violations.json"
    html_path = Path(settings.html_dir) / f"{base_name}_compliance_report.html"

    validator = ShaclValidationEngine()
    all_violations = []

    print(f"\n>>> 合规审查: {base_name}")
    for label, rule_file in COMPLIANCE_RULES:
        rule_path = Path(settings.rules_dir) / rule_file
        print(f"--- [{label}] 执行 {rule_file} ---")
        passed, report, v_list = validator.run_validation(str(jsonld_path), str(rule_path))
        if not passed:
            all_violations.extend(v_list)
            print(f"⚠️ 发现 {label} 违规 {len(v_list)} 条！")
            print(report)
        else:
            print(f"✅ {label} 审查通过。")

    # 保存系统违规报告
    violations_path.parent.mkdir(parents=True, exist_ok=True)
    with open(violations_path, 'w', encoding='utf-8') as f:
        json.dump(all_violations, f, ensure_ascii=False, indent=2)
    print(f"✅ 系统违规报告已保存至: {violations_path}")

    # 生成交互式批注报告（仅当存在违规时）
    if save_html and all_violations:
        svg_path = _resolve_svg(base_name)
        visualizer = ComplianceVisualizer(svg_path, str(jsonld_path))
        visualizer.draw_annotated_report(all_violations, output_path=str(html_path))
        print(f"✅ 交互式批注报告已生成: {html_path}")

    status = "VIOLATIONS" if all_violations else "PASSED"
    print(f"结论: {base_name} -> {status} ({len(all_violations)} 条违规)")
    return status, all_violations


def review_directory(jsonld_dir=None, save_html=True):
    """对目录下所有富化 JSON-LD 批量执行合规审查（跳过 *_raw.jsonld）。"""
    if jsonld_dir is None:
        jsonld_dir = str(settings.jsonld_dir)
    jsonld_dir_path = Path(jsonld_dir)

    if not jsonld_dir_path.is_dir():
        print(f"❌ Invalid directory: {jsonld_dir}")
        return

    files = sorted(p for p in jsonld_dir_path.glob("*.jsonld") if not p.name.endswith("_raw.jsonld"))
    if not files:
        print(f"🛑 No enriched JSON-LD files found in {jsonld_dir}")
        return

    total = len(files)
    print(f"🔍 Found {total} enriched JSON-LD files for compliance review...\n")

    v_count, p_count = 0, 0
    for i, f in enumerate(files, 1):
        print("\n" + "─" * 60)
        print(f"[{i}/{total}] {f.name}")
        print("─" * 60)
        status, _ = review_single(f, save_html=save_html)
        if status == "VIOLATIONS":
            v_count += 1
        else:
            p_count += 1

    print("\n" + "★" * 60)
    print("📊 Compliance review complete!")
    print(f"  Total: {total} | ⚠️ With violations: {v_count} | ✅ Passed: {p_count}")
    print("★" * 60)


def main():
    parser = argparse.ArgumentParser(description="SHACL Compliance Review (Exp 5)")
    parser.add_argument("--mode", choices=["SINGLE", "BATCH"], default=None,
                        help="SINGLE: review one JSON-LD; BATCH: review all JSON-LD in a directory")
    parser.add_argument("--target-dir", default=None,
                        help="JSON-LD directory for BATCH mode (default: output/jsonld)")
    parser.add_argument("--target-file", default=None,
                        help="Single JSON-LD file name (relative to output/jsonld)")
    parser.add_argument("--no-html", action="store_true",
                        help="Skip interactive HTML report generation")
    args = parser.parse_args()

    mode = (args.mode or settings.run_mode).upper()

    if mode == "SINGLE":
        target_file = args.target_file or "sample.jsonld"
        target_file_path = Path(settings.jsonld_dir) / target_file
        if not target_file_path.exists():
            print(f"ERROR: JSON-LD not found: {target_file_path}")
            sys.exit(1)
        review_single(target_file_path, save_html=not args.no_html)

    elif mode == "BATCH":
        review_directory(args.target_dir, save_html=not args.no_html)

    else:
        print(f"🛑 ERROR: Unknown run mode '{mode}'.")


if __name__ == "__main__":
    main()
