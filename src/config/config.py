import yaml
from pathlib import Path

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
        self.config_path = PROJECT_ROOT / config_file

        # 加载 YAML (需要 pip install PyYAML)
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件未找到: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            self._cfg = yaml.safe_load(f)

    @property
    def data_path(self):
        """
        自动返回 data 目录的绝对路径
        """
        # 核心魔法：根目录 + 配置文件里的相对路径
        path_str = self._cfg.get('data', {}).get('root_dir', 'data')
        return PROJECT_ROOT / path_str

    @property
    def dxf_data_path(self):
        path_str = self._cfg.get('data', {}).get('dxf_dir', 'data/raw/dxf')
        return PROJECT_ROOT / path_str

    @property
    def dxf_extend_data_path(self):
        path_str = self._cfg.get('data', {}).get('dxf_extend_dir', 'data/raw/dxf_extend')
        return PROJECT_ROOT / path_str

    @property
    def raw_pickle_data_path(self):
        """返回 raw pickle 的绝对路径"""
        path_str = self._cfg.get('data', {}).get('raw_pickle_dir', 'data/raw/pickle')
        return PROJECT_ROOT / path_str

    @property
    def raw_svg_data_path(self):
        """返回 raw svg 的绝对路径"""
        path_str = self._cfg.get('data', {}).get('raw_svg_dir', 'data/raw/svg')
        return PROJECT_ROOT / path_str

    @property
    def processed_svg_data_path(self):
        """返回 processed svg 的绝对路径"""
        path_str = self._cfg.get('data', {}).get('processed_svg_dir', 'data/processed/svg')
        return PROJECT_ROOT / path_str

    @property
    def output_html_dir(self):
        path_str = self._cfg.get('output', {}).get('html_dir', "output/html")
        return PROJECT_ROOT / path_str

    @property
    def rules_dir(self):
        path_str = self._cfg.get('rules',{})
        return PROJECT_ROOT / path_str

    @property
    def svg_ins_dir(self):
        path_str = self._cfg.get('output',{}).get('svg_ins_dir','output/svg_ins')
        return PROJECT_ROOT / path_str

    @property
    def cdt_dir(self):
        path_str = self._cfg.get('output', {}).get('cdt_dir', 'output/cdt')
        return PROJECT_ROOT / path_str

    @property
    def exp_viz_dir(self):
        path_str = self._cfg.get('output', {}).get('exp_viz_dir', 'output/exp_viz')
        return PROJECT_ROOT / path_str

    @property
    def gt_viz_dir(self):
        path_str = self._cfg.get('output', {}).get('gt_viz_dir', 'output/gt_viz')
        return PROJECT_ROOT / path_str

    @property
    def exp_jsonld_dir(self):
        path_str = self._cfg.get('output', {}).get('exp_jsonld_dir', 'output/exp_jsonld')
        return PROJECT_ROOT / path_str

    @property
    def gt_jsonld_dir(self):
        path_str = self._cfg.get('output', {}).get('gt_jsonld_dir', 'output/gt_jsonld')
        return PROJECT_ROOT / path_str

    @property
    def exp_res_dir(self):
        path_str = self._cfg.get('output', {}).get('exp_res_dir', 'output/exp_res')
        return PROJECT_ROOT / path_str

    @property
    def gt_res_dir(self):
        path_str = self._cfg.get('output', {}).get('gt_res_dir', 'output/gt_res')
        return PROJECT_ROOT / path_str

    @property
    def prompt_config_dir(self):
        path_str = self._cfg.get('prompt',{}).get('prompt_config_dir', "prompt/prompt_config.txt")
        return PROJECT_ROOT / path_str

# ==========================================
# 3. 实例化单例
# ==========================================
# 这样其他文件 import 时，直接用这个 settings 实例，不需要重复读取文件
settings = Settings()
