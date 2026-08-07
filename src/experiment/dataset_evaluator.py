"""
Batch dataset evaluator.

Runs the single-file PipelineEvaluator over an entire dataset directory,
aggregates per-file metrics, and writes the results to separate output files:

- ``overall_results.json`` / ``individual_results.csv`` — geometry / topology /
  geometric computation / semantic results (grouped together).
- ``compliance_results.json`` / ``compliance_individual_results.csv`` — SHACL
  compliance results (Exp 5), saved and displayed on their own.
"""

import json
import os
import re
import sys
import traceback
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

# Windows 控制台默认 GBK 编码，强制 UTF-8 输出避免表情符号触发 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

from src.config.config import settings
from src.experiment.evaluator import PipelineEvaluator


class BatchDatasetEvaluator:
    def __init__(self, gt_dir: str, sys_out_dir: str, violation_dir: Optional[str], output_dir: str):
        """
        Initialize the batch dataset evaluation engine.

        :param gt_dir: Directory holding the human-annotated Ground Truth JSON files.
        :param sys_out_dir: Directory holding the system-generated JSON-LD files.
        :param violation_dir: Directory holding the system violation report JSON files (optional).
        :param output_dir: Directory where evaluation results (CSV/JSON) are saved.
        """
        self.gt_dir = gt_dir
        self.sys_out_dir = sys_out_dir
        self.violation_dir = violation_dir
        self.output_dir = output_dir

        os.makedirs(self.output_dir, exist_ok=True)

        # Per-file individual results (geometry / topology / geometric computation / semantic)
        self.individual_results: List[Dict[str, Any]] = []

        # Per-file SHACL compliance results (Exp 5) — kept separate from the core metrics
        self.compliance_individual_results: List[Dict[str, Any]] = []

        # Global aggregation data collected across all files
        self.global_data: Dict[str, Any] = {
            "gt_rooms": 0,
            "1to1_rooms": 0,
            "all_iou_scores": [],
            "topo_tp": 0, "topo_fp": 0, "topo_fn": 0,
            "area_errors": [],
            "width_errors": [],
            "y_true": [],
            "y_pred": [],
            "comp_tp": 0, "comp_fp": 0, "comp_fn": 0
        }

    @staticmethod
    def _extract_base_name(filename: str) -> Optional[str]:
        """Extract the base sample name from a Ground Truth filename.

        Handles both ``.json`` and ``.jsonld`` extensions, strips a trailing
        ``_gt`` marker and an ``_annotated`` source marker so the GT name maps
        onto the system-output name, e.g.
        ``2suite_annotated (1)_gt.jsonld`` -> ``2suite (1)``.
        """
        for ext in (".jsonld", ".json"):
            if filename.endswith(ext):
                name = filename[: -len(ext)]
                break
        else:
            return None

        if name.endswith("_gt"):
            name = name[:-3]
        name = re.sub(r"_annotated", "", name, flags=re.IGNORECASE)
        return name

    def _find_system_output(self, base_name: str) -> Optional[str]:
        """Locate the matching system output file for a given base name."""
        if not os.path.isdir(self.sys_out_dir):
            return None
        for ext in (".jsonld", ".json"):
            candidate = os.path.join(self.sys_out_dir, f"{base_name}{ext}")
            if os.path.exists(candidate):
                return candidate
        return None

    def _match_files(self) -> List[Dict[str, str]]:
        """Scan and pair up the Ground Truth / system output files in the directories."""
        matched_pairs: List[Dict[str, str]] = []
        if not os.path.isdir(self.gt_dir):
            return matched_pairs

        for gt_filename in os.listdir(self.gt_dir):
            if not (gt_filename.endswith(".json") or gt_filename.endswith(".jsonld")):
                continue

            base_name = self._extract_base_name(gt_filename)
            if not base_name:
                continue

            sys_path = self._find_system_output(base_name)
            if not sys_path:
                continue

            vio_path = ""
            if self.violation_dir:
                temp_vio = os.path.join(self.violation_dir, f"{base_name}_violations.json")
                if os.path.exists(temp_vio):
                    vio_path = temp_vio

            matched_pairs.append({
                "base_name": base_name,
                "gt_path": os.path.join(self.gt_dir, gt_filename),
                "sys_path": sys_path,
                "vio_path": vio_path,
            })

        return matched_pairs

    @staticmethod
    def _calculate_metrics(tp: float, fp: float, fn: float) -> Tuple[float, float, float]:
        """Compute precision, recall, and F1 from TP / FP / FN counts."""
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        return precision, recall, f1

    def run_evaluation(self) -> None:
        """Run the batch evaluation core logic."""
        file_pairs = self._match_files()
        if not file_pairs:
            print("[-] No matched test data found in the specified directory.")
            return

        print(f"[+] Starting full evaluation, found {len(file_pairs)} valid samples...")

        for pair in file_pairs:
            base_name = pair["base_name"]
            print(f"\n>>> Evaluating: {base_name}")

            # Load the input data files
            with open(pair["gt_path"], 'r', encoding='utf-8') as f:
                gt_data = json.load(f)
            with open(pair["sys_path"], 'r', encoding='utf-8') as f:
                sys_data = json.load(f)

            sys_violations: List[Any] = []
            if pair["vio_path"]:
                with open(pair["vio_path"], 'r', encoding='utf-8') as f:
                    sys_violations = json.load(f)

            # Run the single-file evaluator (the getters trigger evaluation lazily)
            try:
                evaluator = PipelineEvaluator(gt_data, sys_data, sys_violations)
                rate_1to1, mean_iou, iou_scores = evaluator.get_geometry_metrics()
                topo_tp, topo_fp, topo_fn = evaluator.get_topology_raw_counts()
                area_errors, width_errors = evaluator.get_computation_errors()
                y_true, y_pred = evaluator.get_semantic_labels()
                comp_tp, comp_fp, comp_fn = evaluator.get_compliance_raw_counts()
            except Exception as exc:  # noqa: BLE001 - keep going on a per-file failure
                print(f"[-] Evaluation error for {base_name}: {exc}")
                traceback.print_exc()
                continue

            # --- 1. Record the per-file individual result ---
            topo_p, topo_r, topo_f1 = self._calculate_metrics(topo_tp, topo_fp, topo_fn)
            comp_p, comp_r, comp_f1 = self._calculate_metrics(comp_tp, comp_fp, comp_fn)

            if y_true:
                sem_acc = accuracy_score(y_true, y_pred)
                _, _, sem_macro_f1, _ = precision_recall_fscore_support(
                    y_true, y_pred, average='macro', zero_division=0
                )
                sem_macro_f1 = float(sem_macro_f1)
            else:
                sem_acc, sem_macro_f1 = 0.0, 0.0

            ind_result = {
                "File_Name": base_name,
                "Geom_1to1_Rate": round(rate_1to1, 4),
                "Geom_mIoU": round(mean_iou, 4),
                "Topo_Precision": round(topo_p, 4),
                "Topo_Recall": round(topo_r, 4),
                "Topo_F1": round(topo_f1, 4),
                "Error_MAE_Area": round(np.mean(area_errors), 4) if area_errors else 0.0,
                "Error_MAE_Width": round(np.mean(width_errors), 4) if width_errors else 0.0,
                "Sem_Accuracy": round(sem_acc, 4),
                "Sem_Macro_F1": round(sem_macro_f1, 4)
            }
            self.individual_results.append(ind_result)

            # SHACL compliance metrics are recorded separately (Exp 5)
            comp_result = {
                "File_Name": base_name,
                "Comp_Precision": round(comp_p, 4),
                "Comp_Recall": round(comp_r, 4),
                "Comp_F1": round(comp_f1, 4)
            }
            self.compliance_individual_results.append(comp_result)

            # --- 2. Accumulate the global aggregation data ---
            self.global_data["gt_rooms"] += len(evaluator.gt_rooms)
            self.global_data["1to1_rooms"] += sum(1 for v in evaluator.gt_status.values() if v == "1-to-1")
            self.global_data["all_iou_scores"].extend(iou_scores)

            self.global_data["topo_tp"] += topo_tp
            self.global_data["topo_fp"] += topo_fp
            self.global_data["topo_fn"] += topo_fn

            self.global_data["area_errors"].extend(area_errors)
            self.global_data["width_errors"].extend(width_errors)

            self.global_data["y_true"].extend(y_true)
            self.global_data["y_pred"].extend(y_pred)

            self.global_data["comp_tp"] += comp_tp
            self.global_data["comp_fp"] += comp_fp
            self.global_data["comp_fn"] += comp_fn

        self._save_results()

    def _save_results(self) -> None:
        """Compute the final global metrics and save the results.

        The SHACL compliance results (Exp 5) are saved in their own files
        (``compliance_results.json`` / ``compliance_individual_results.csv``),
        while the geometry / topology / geometric computation / semantic
        results are grouped together (``overall_results.json`` /
        ``individual_results.csv``).
        """
        if not self.individual_results and not self.compliance_individual_results:
            return

        # 1. Save the per-file individual results as CSVs (core vs. compliance)
        if self.individual_results:
            df = pd.DataFrame(self.individual_results)
            ind_csv_path = os.path.join(self.output_dir, "individual_results.csv")
            df.to_csv(ind_csv_path, index=False, encoding='utf-8-sig')
            print(f"\n[+] Individual evaluation results saved to: {ind_csv_path}")

        if self.compliance_individual_results:
            comp_df = pd.DataFrame(self.compliance_individual_results)
            comp_csv_path = os.path.join(self.output_dir, "compliance_individual_results.csv")
            comp_df.to_csv(comp_csv_path, index=False, encoding='utf-8-sig')
            print(f"[+] Compliance individual results saved to: {comp_csv_path}")

        # 2. Compute the global metrics
        gt_rooms = self.global_data["gt_rooms"]
        g_1to1_rate = self.global_data["1to1_rooms"] / gt_rooms if gt_rooms > 0 else 0.0
        g_miou = np.mean(self.global_data["all_iou_scores"]) if self.global_data["all_iou_scores"] else 0.0

        g_topo_p, g_topo_r, g_topo_f1 = self._calculate_metrics(
            self.global_data["topo_tp"], self.global_data["topo_fp"], self.global_data["topo_fn"]
        )

        g_mae_area = np.mean(self.global_data["area_errors"]) if self.global_data["area_errors"] else 0.0
        g_mae_width = np.mean(self.global_data["width_errors"]) if self.global_data["width_errors"] else 0.0

        if self.global_data["y_true"]:
            g_sem_acc = accuracy_score(self.global_data["y_true"], self.global_data["y_pred"])
            _, _, g_sem_macro_f1, _ = precision_recall_fscore_support(
                self.global_data["y_true"], self.global_data["y_pred"], average='macro', zero_division=0
            )
            g_sem_macro_f1 = float(g_sem_macro_f1)
        else:
            g_sem_acc, g_sem_macro_f1 = 0.0, 0.0

        g_comp_p, g_comp_r, g_comp_f1 = self._calculate_metrics(
            self.global_data["comp_tp"], self.global_data["comp_fp"], self.global_data["comp_fn"]
        )

        total_files = max(len(self.individual_results), len(self.compliance_individual_results))

        # 3. Global summary for the core experiments (geometry / topology / semantic)
        overall_results = {
            "Total_Files_Processed": total_files,
            "Geometry": {
                "Global_1to1_Match_Rate": round(g_1to1_rate, 4),
                "Global_mIoU": round(g_miou, 4)
            },
            "Topology": {
                "Global_Precision": round(g_topo_p, 4),
                "Global_Recall": round(g_topo_r, 4),
                "Global_F1": round(g_topo_f1, 4)
            },
            "Geometric_Computation": {
                "Global_MAE_Area": round(g_mae_area, 4),
                "Global_MAE_Width": round(g_mae_width, 4)
            },
            "Semantic_Reasoning": {
                "Global_Accuracy": round(g_sem_acc, 4),
                "Global_Macro_F1": round(g_sem_macro_f1, 4)
            }
        }

        # Save the core global summary results as JSON
        overall_json_path = os.path.join(self.output_dir, "overall_results.json")
        with open(overall_json_path, 'w', encoding='utf-8') as f:
            json.dump(overall_results, f, ensure_ascii=False, indent=4)
        print(f"[+] Dataset overall results saved to: {overall_json_path}")

        # 4. SHACL compliance summary (Exp 5) — saved separately
        compliance_results = {
            "Total_Files_Processed": total_files,
            "Compliance_Checking": {
                "Global_Precision": round(g_comp_p, 4),
                "Global_Recall": round(g_comp_r, 4),
                "Global_F1": round(g_comp_f1, 4)
            }
        }

        compliance_json_path = os.path.join(self.output_dir, "compliance_results.json")
        with open(compliance_json_path, 'w', encoding='utf-8') as f:
            json.dump(compliance_results, f, ensure_ascii=False, indent=4)
        print(f"[+] SHACL compliance results saved to: {compliance_json_path}")


if __name__ == "__main__":
    import sys

    # Optional: pass a subdirectory (or relative path) as the first CLI argument.
    FILE_DIR = sys.argv[1] if len(sys.argv) > 1 else ""

    # Configure the actual directory paths
    GT_DIR = os.path.join(str(settings.gt_dir), FILE_DIR) if settings.gt_dir else ""             # Ground Truth annotation directory
    SYS_OUT_DIR = os.path.join(str(settings.jsonld_dir), FILE_DIR) if settings.jsonld_dir else ""  # System-generated graph directory
    VIO_DIR = os.path.join(str(settings.violations_dir), FILE_DIR) if settings.violations_dir else None  # System violation reports
    OUTPUT_DIR = os.path.join(str(settings.html_dir), FILE_DIR) if settings.html_dir else ""       # Results output directory

    # Create the output directory to avoid errors when running directly
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    evaluator = BatchDatasetEvaluator(
        gt_dir=GT_DIR,
        sys_out_dir=SYS_OUT_DIR,
        violation_dir=VIO_DIR,
        output_dir=OUTPUT_DIR,
    )

    # Start the evaluation
    evaluator.run_evaluation()