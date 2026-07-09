import os
import json
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

# 导入您提供的单文件评估器



from src.config.config import settings
from src.experiment.evaluator import PipelineEvaluator


class BatchDatasetEvaluator:
    def __init__(self, gt_dir, sys_out_dir, violation_dir, output_dir):
        """
        初始化批量数据集评估引擎
        :param gt_dir: 存放人工标注 Ground Truth JSON 的目录
        :param sys_out_dir: 存放系统输出 JSON-LD 的目录
        :param violation_dir: 存放系统输出违规报告 JSON 的目录 (可选)
        :param output_dir: 评估结果(CSV/JSON)的保存目录
        """
        self.gt_dir = gt_dir
        self.sys_out_dir = sys_out_dir
        self.violation_dir = violation_dir
        self.output_dir = output_dir

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # 存储每个文件的独立结果
        self.individual_results = []

        # 存储全局聚合数据
        self.global_data = {
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

    def _match_files(self):
        """扫描并配对目录下的文件"""
        matched_pairs = []
        if not os.path.exists(self.gt_dir):
            return matched_pairs

        for gt_filename in os.listdir(self.gt_dir):
            if not gt_filename.endswith(".json") and not gt_filename.endswith(".jsonld"):
                continue

            # 提取基础文件名，兼容多种后缀命名习惯
            base_name = gt_filename.replace("_gt.jsonld", "")

            # 寻找对应的系统输出文件
            sys_path = None
            for ext in [".jsonld", ".json"]:
                temp_path = os.path.join(self.sys_out_dir, f"{base_name}{ext}")
                if os.path.exists(temp_path):
                    sys_path = temp_path
                    break

            if sys_path:
                vio_path = None
                if self.violation_dir:
                    temp_vio = os.path.join(self.violation_dir, f"{base_name}_violations.json")
                    if os.path.exists(temp_vio):
                        vio_path = temp_vio

                matched_pairs.append({
                    "base_name": base_name,
                    "gt_path": os.path.join(self.gt_dir, gt_filename),
                    "sys_path": sys_path,
                    "vio_path": vio_path
                })

        return matched_pairs

    def _calculate_metrics(self, tp, fp, fn):
        """辅助函数：计算 P, R, F1"""
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        return precision, recall, f1

    def run_evaluation(self):
        """Run the batch evaluation core logic."""
        file_pairs = self._match_files()
        if not file_pairs:
            print(f"[-] No matched test data found in the specified directory.")
            return

        print(f"[+] Starting full evaluation, found {len(file_pairs)} valid samples...")

        for pair in file_pairs:
            base_name = pair["base_name"]
            print(f"\n>>> Evaluating: {base_name}")

            # 加载数据
            with open(pair["gt_path"], 'r', encoding='utf-8') as f:
                gt_data = json.load(f)
            with open(pair["sys_path"], 'r', encoding='utf-8') as f:
                sys_data = json.load(f)

            sys_violations = []
            if pair["vio_path"]:
                with open(pair["vio_path"], 'r', encoding='utf-8') as f:
                    sys_violations = json.load(f)

            # 实例化单文件评估器
            try:
                evaluator = PipelineEvaluator(gt_data, sys_data, sys_violations)
                # 执行提取（调用 getter 会自动触发评估）
                rate_1to1, mean_iou, iou_scores = evaluator.get_geometry_metrics()
                topo_tp, topo_fp, topo_fn = evaluator.get_topology_raw_counts()
                area_errors, width_errors = evaluator.get_computation_errors()
                y_true, y_pred = evaluator.get_semantic_labels()
                comp_tp, comp_fp, comp_fn = evaluator.get_compliance_raw_counts()
            except Exception as e:
                print(f"[-] Evaluation error for {base_name}: {e}")
                continue

            # --- 1. 记录单文件独立结果 ---
            topo_p, topo_r, topo_f1 = self._calculate_metrics(topo_tp, topo_fp, topo_fn)
            comp_p, comp_r, comp_f1 = self._calculate_metrics(comp_tp, comp_fp, comp_fn)

            sem_acc = accuracy_score(y_true, y_pred) if y_true else 0.0
            _, _, sem_macro_f1, _ = precision_recall_fscore_support(y_true, y_pred, average='macro',
                                                                    zero_division=0) if y_true else (0, 0, 0, None)

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
                "Sem_Macro_F1": round(sem_macro_f1, 4),
                "Comp_Precision": round(comp_p, 4),
                "Comp_Recall": round(comp_r, 4),
                "Comp_F1": round(comp_f1, 4)
            }
            self.individual_results.append(ind_result)

            # --- 2. 累加全局汇总数据 ---
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

    def _save_results(self):
        """计算最终的全局指标并保存结果"""
        if not self.individual_results:
            return

        # 1. 保存单文件独立结果为 CSV
        df = pd.DataFrame(self.individual_results)
        ind_csv_path = os.path.join(self.output_dir, "individual_results.csv")
        df.to_csv(ind_csv_path, index=False, encoding='utf-8-sig')
        print(f"\n[+] Individual evaluation results saved to: {ind_csv_path}")

        # 2. 计算全局指标
        g_1to1_rate = self.global_data["1to1_rooms"] / self.global_data["gt_rooms"] if self.global_data[
                                                                                           "gt_rooms"] > 0 else 0.0
        g_miou = np.mean(self.global_data["all_iou_scores"]) if self.global_data["all_iou_scores"] else 0.0

        g_topo_p, g_topo_r, g_topo_f1 = self._calculate_metrics(
            self.global_data["topo_tp"], self.global_data["topo_fp"], self.global_data["topo_fn"]
        )

        g_mae_area = np.mean(self.global_data["area_errors"]) if self.global_data["area_errors"] else 0.0
        g_mae_width = np.mean(self.global_data["width_errors"]) if self.global_data["width_errors"] else 0.0

        g_sem_acc = accuracy_score(self.global_data["y_true"], self.global_data["y_pred"]) if self.global_data[
            "y_true"] else 0.0
        _, _, g_sem_macro_f1, _ = precision_recall_fscore_support(
            self.global_data["y_true"], self.global_data["y_pred"], average='macro', zero_division=0
        ) if self.global_data["y_true"] else (0, 0, 0, None)

        g_comp_p, g_comp_r, g_comp_f1 = self._calculate_metrics(
            self.global_data["comp_tp"], self.global_data["comp_fp"], self.global_data["comp_fn"]
        )

        overall_results = {
            "Total_Files_Processed": len(self.individual_results),
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
            },
            "Compliance_Checking": {
                "Global_Precision": round(g_comp_p, 4),
                "Global_Recall": round(g_comp_r, 4),
                "Global_F1": round(g_comp_f1, 4)
            }
        }

        # 保存全局汇总结果为 JSON
        overall_json_path = os.path.join(self.output_dir, "overall_results.json")
        with open(overall_json_path, 'w', encoding='utf-8') as f:
            json.dump(overall_results, f, ensure_ascii=False, indent=4)
        print(f"[+] Dataset overall results saved to: {overall_json_path}")


if __name__ == "__main__":
    # 配置您的实际目录路径
    FILE_DIR = ""
    GT_DIR = os.path.join(settings.gt_jsonld_dir, FILE_DIR) # 人工标注目录
    SYS_OUT_DIR = os.path.join(settings.exp_jsonld_dir, FILE_DIR)  # 系统生成图谱目录
    VIO_DIR = None
    OUTPUT_DIR = os.path.join(settings.output_html_dir, FILE_DIR)  # 结果保存目录

    # 简单生成测试目录防止直接运行报错
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    evaluator = BatchDatasetEvaluator(
        gt_dir=GT_DIR,
        sys_out_dir=SYS_OUT_DIR,
        violation_dir=VIO_DIR,
        output_dir=OUTPUT_DIR
    )

    # 启动评估
    evaluator.run_evaluation()