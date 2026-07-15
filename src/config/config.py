import os
from pathlib import Path

import yaml

# ==========================================
# 1. 自动锚定项目根目录
# ==========================================
# 假设当前文件在 src/config/config.py
# .parent -> src/config
# .parent -> src
# .parent -> 项目根目录 (cad_rule_checker/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# ==========================================
# 2. 定义配置类
# ==========================================
class Settings:
    def __init__(self, config_file="src/config/settings.yaml"):
        self.config_path = PROJECT_ROOT / config_file if not Path(config_file).is_absolute() else Path(config_file)

        # 加载 YAML (需要 pip install PyYAML)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            self._cfg = yaml.safe_load(f) or {}

        if not isinstance(self._cfg, dict):
            self._cfg = {}

    def _get_section(self, section, default=None):
        section_cfg = self._cfg.get(section, default)
        return section_cfg if isinstance(section_cfg, dict) else {}

    def _get_value(self, section, key, default=None):
        return self._get_section(section).get(key, default)

    def _read_env(self, env_key, default=None):
        value = os.getenv(env_key)
        return value if value not in (None, "") else default

    def _resolve_path(self, value, base_dir=None):
        if value is None:
            return None
        path = Path(str(value))
        if path.is_absolute():
            return path
        base_root = Path(base_dir) if base_dir is not None else PROJECT_ROOT
        return (base_root / path).resolve()

    def resolve_project_path(self, value, base_dir=None):
        return self._resolve_path(value, base_dir=base_dir)

    # ==========================================
    # 3. 输入数据路径 (Input Data) — 仅原始/外部输入文件
    # ==========================================
    @property
    def dxf_dir(self):
        """原始 DXF 图纸目录"""
        path_str = self._get_value('input_data', 'dxf', 'input_data/dxf')
        return self._resolve_path(path_str)

    @property
    def svg_dir(self):
        """原始/转换 SVG 图纸目录"""
        path_str = self._get_value('input_data', 'svg', 'input_data/svg')
        return self._resolve_path(path_str)

    @property
    def dxf_gt_dir(self):
        """人工标注 Ground Truth DXF 目录"""
        path_str = self._get_value('input_data', 'dxf_gt', 'input_data/dxf_gt')
        return self._resolve_path(path_str)

    @property
    def pickle_dir(self):
        """外部实例分割 pickle 缓存目录"""
        path_str = self._get_value('input_data', 'pickle', 'input_data/pickle')
        return self._resolve_path(path_str)

    # ==========================================
    # 4. 输出路径 (Output) — 统一管理所有产出物
    # ==========================================
    @property
    def jsonld_dir(self):
        """系统生成的 JSON-LD 知识图谱目录"""
        path_str = self._get_value('output', 'jsonld', 'output/jsonld')
        return self._resolve_path(path_str)

    @property
    def violations_dir(self):
        """违规报告目录"""
        path_str = self._get_value('output', 'violations', 'output/violations')
        return self._resolve_path(path_str)

    @property
    def viz_dir(self):
        """可视化图片目录（CDT/SVG 实例/实验/GT 预览）"""
        path_str = self._get_value('output', 'viz', 'output/viz')
        return self._resolve_path(path_str)

    @property
    def gt_dir(self):
        """Ground Truth 人工标注目录"""
        path_str = self._get_value('output', 'gt', 'output/gt')
        return self._resolve_path(path_str)

    @property
    def html_dir(self):
        """HTML 评估报告目录"""
        path_str = self._get_value('output', 'html', 'output/html')
        return self._resolve_path(path_str)

    @property
    def processed_dir(self):
        """中间处理 SVG 目录"""
        path_str = self._get_value('output', 'processed', 'output/processed')
        return self._resolve_path(path_str)

    @property
    def rules_dir(self):
        """SHACL 规则目录"""
        path_str = self._cfg.get('rules', 'rules')
        return self._resolve_path(path_str)

    @property
    def prompt_config_dir(self):
        path_str = self._get_value('prompt', 'prompt_config_dir', 'prompt/prompt_config.txt')
        return self._resolve_path(path_str)

    @property
    def run_mode(self):
        return self._read_env('CAD_RULE_CHECKER_RUN_MODE', self._get_value('runtime', 'run_mode', 'SINGLE')).upper()

    @property
    def runtime_target_dir(self):
        return self._read_env('CAD_RULE_CHECKER_TARGET_DIR', self._get_value('runtime', 'target_dir', ''))

    @property
    def runtime_target_file(self):
        return self._read_env('CAD_RULE_CHECKER_TARGET_FILE', self._get_value('runtime', 'target_file', 'nanyangmingmen150.svg'))

    @property
    def runtime_output_dir(self):
        path_str = self._read_env('CAD_RULE_CHECKER_OUTPUT_DIR', self._get_value('runtime', 'jsonld_dir', 'output/jsonld'))
        return self._resolve_path(path_str)

    @property
    def sample_input_jsonld(self):
        return self._read_env('CAD_RULE_CHECKER_SAMPLE_INPUT_JSONLD', self._get_value('runtime', 'sample_input_jsonld', 'apartment_semantic_suites.jsonld'))

    @property
    def sample_output_jsonld(self):
        return self._read_env('CAD_RULE_CHECKER_SAMPLE_OUTPUT_JSONLD', self._get_value('runtime', 'sample_output_jsonld', 'apartment_semantic_suites_geo.json'))

    @property
    def sample_visualization_input(self):
        return self._read_env('CAD_RULE_CHECKER_SAMPLE_VIS_INPUT', self._get_value('runtime', 'sample_visualization_input', '北京保利140+135.jsonld'))

    @property
    def sample_visualization_output(self):
        return self._read_env('CAD_RULE_CHECKER_SAMPLE_VIS_OUTPUT', self._get_value('runtime', 'sample_visualization_output', '北京保利140+135.png'))

    @property
    def llm_api_key(self):
        return self._read_env('CAD_RULE_CHECKER_LLM_API_KEY', self._get_value('llm', 'api_key', ''))

    @property
    def llm_base_url(self):
        return self._read_env('CAD_RULE_CHECKER_LLM_BASE_URL', self._get_value('llm', 'base_url', 'https://open.bigmodel.cn/api/paas/v4/'))

    @property
    def llm_model(self):
        return self._read_env('CAD_RULE_CHECKER_LLM_MODEL', self._get_value('llm', 'model', 'glm-4-flash'))

    # ==========================================
    # 评估 (Evaluation) 配置
    # ==========================================
    @property
    def eval_gt_jsonld(self):
        """Ground Truth JSON-LD 文件路径（相对项目根目录）"""
        val = self._get_value('evaluation', 'gt_jsonld', '')
        return self._resolve_path(val) if val else None

    @property
    def eval_sys_jsonld(self):
        """系统输出 JSON-LD 文件路径（相对项目根目录）"""
        val = self._get_value('evaluation', 'sys_jsonld', '')
        return self._resolve_path(val) if val else None

    @property
    def eval_gt_svg(self):
        """Ground Truth SVG 文件路径（可选，相对项目根目录）"""
        val = self._get_value('evaluation', 'gt_svg', '')
        return self._resolve_path(val) if val else None

    @property
    def eval_sys_svg(self):
        """系统输入 SVG 文件路径（可选，相对项目根目录）"""
        val = self._get_value('evaluation', 'sys_svg', '')
        return self._resolve_path(val) if val else None

    @property
    def eval_violations_json(self):
        """系统违规报告 JSON 文件路径（可选，相对项目根目录）"""
        val = self._get_value('evaluation', 'violations_json', '')
        return self._resolve_path(val) if val else None

    def resolve_runtime_target_path(self, target_dir=None, target_file=None):
        target_dir_value = target_dir or self.runtime_target_dir
        target_file_value = target_file or self.runtime_target_file

        if isinstance(target_dir_value, str) and target_dir_value.startswith('input_data/svg/'):
            target_dir_value = target_dir_value[len('input_data/svg/'):]
        if isinstance(target_file_value, str) and target_file_value.startswith('input_data/svg/'):
            target_file_value = target_file_value[len('input_data/svg/'):]

        target_dir_path = Path(target_dir_value)
        if not target_dir_path.is_absolute():
            target_dir_path = self.svg_dir / target_dir_path

        target_file_path = Path(target_file_value)
        if target_file_path.is_absolute():
            return target_file_path
        return target_dir_path / target_file_path

    def resolve_runtime_input_dir(self, target_dir=None):
        target_dir_value = target_dir or self.runtime_target_dir
        if isinstance(target_dir_value, str) and target_dir_value.startswith('input_data/svg/'):
            target_dir_value = target_dir_value[len('input_data/svg/'):]
        target_dir_path = Path(target_dir_value)
        if target_dir_path.is_absolute():
            return target_dir_path
        return self.svg_dir / target_dir_path


# ==========================================
# 3. 实例化单例
# ==========================================
# 这样其他文件 import 时，直接用这个 settings 实例，不需要重复读取文件
settings = Settings()
