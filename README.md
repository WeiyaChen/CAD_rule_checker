# CAD Rule Checker

`CAD Rule Checker` 是一个用于建筑 CAD / 平面图审查的 Python 工具箱。它支持从 DXF 转换为 SVG、提取空间元素、构建拓扑图谱、进行语义富化，并生成 JSON-LD 结果与可视化输出。

## 亮点

- ✅ 支持 DXF → SVG 转换
- ✅ 结构化提取图纸元素与文本标签
- ✅ 构建基础几何和拓扑知识图谱
- ✅ 语义富化与 LLM 推断（可选）
- ✅ 支持批量处理与单图处理模式
- ✅ 支持真值构建与模型评估

## 项目目录

```text
cad_rule_checker/
├── data/
│   ├── processed/
│   │   └── svg/             # 经过深度学习模型图元识别后的文件
│   └── raw/
│       ├── dxf/             # 原始 DXF 文件
│       ├── dxf_extend/      # 人工标注或扩展 DXF 文件
│       ├── pickle/          # 中间 pickle 数据
│       └── svg/             # DXF 转换后生成的 SVG 文件
├── output/
│   ├── cdt/
│   ├── exp_jsonld/          # 语义富化后的 JSON-LD
│   ├── exp_res/             # 规则审查结果
│   ├── exp_viz/             # 可视化输出
│   ├── gt_jsonld/           # 真值 JSON-LD
│   ├── gt_res/              # 真值评估结果
│   ├── gt_viz/
│   └── svg_ins/             # SVG 元素识别可视化
├── prompt/
│   └── prompt_config.txt    # LLM 提示词配置
├── rules/
│   ├── exp.ttl
│   ├── l1_semantic_check.ttl
│   ├── l2_geometric_check.ttl
│   └── l3_topological_check.ttl
├── src/
│   ├── compliance/          # SHACL 校验引擎
│   ├── config/              # 配置与目录常量
│   ├── core/                # 核心几何与空间对象
│   ├── enricher/            # 图谱富化与语义扩展
│   ├── experiment/          # 评估与真值构建脚本
│   ├── io/                  # DXF/SVG 读写与转换
│   ├── topology/            # 拓扑构建与图分析
│   ├── utils/               # 可视化与辅助工具
│   ├── main.py              # 主运行入口
│   └── processor.py         # 图纸处理流程
└── README.md
```

## 环境与依赖

推荐使用 Python 3.10+。

安装必要依赖：

```bash
pip install ezdxf openai pyyaml rdflib pyshacl matplotlib lxml numpy pandas svgpathtools opencv-python triangle networkx pyvis shapely scikit-learn
```

如果需要运行真值生成与评估脚本，还需安装：

```bash
pip install shapely
```

> 注意：当前仓库没有提供 `requirements.txt`，请根据项目需求手动安装依赖。

## 快速开始

### 1. 准备 DXF 输入

将待处理 DXF 文件放入：

```text
data/raw/dxf/test/
```

### 2. DXF 转 SVG

在 `src/io/dxf_to_svg.py` 中设置目录：

```python
file_dir = "test"
```

在项目根目录中，运行转换脚本：

```bash
python -m src.io.dxf_to_svg
```

转换结果会输出到：

```text
data/raw/svg/test/
```

### 3. 运行主审查流程

可直接通过配置文件或命令行参数控制输入路径与运行模式：

```bash
python -m src.main --mode SINGLE --target-dir test --target-file 南阳名门150.svg
```

也可以先修改配置文件 [src/config/settings.yaml](src/config/settings.yaml) 中的 `runtime` 段，然后直接执行：

```bash
python -m src.main
```

程序会执行：

- 图元抽取与元素可视化
- 拓扑图谱构建
- 语义富化与 JSON-LD 输出
- 可视化结果生成

### 4. 生成真值数据

将人工标注或扩展后的 DXF 放入：

```text
data/raw/dxf_extend/test/
```

运行真值构建脚本：

```bash
python -m src.experiment.ground_truth_creator
```

### 5. 评估模型与数据集

根据 `src/experiment/dataset_evaluator.py` 中的目录设置，运行：

```bash
python -m src.experiment.dataset_evaluator
```

## 核心配置文件

- [src/config/settings.yaml](src/config/settings.yaml)：输入、输出、规则和 prompt 路径配置
- [prompt/prompt_config.txt](prompt/prompt_config.txt)：LLM 提示词模板
- [rules/](rules/)：SHACL 规则文件

## 运行模式说明

主入口现在支持通过配置文件或命令行参数控制：

- `SINGLE`：处理单个 SVG 文件
- `BATCH`：处理指定目录中的所有 SVG 文件
- `DEFAULT`：处理 `settings.yaml` 中配置的默认目录

常用参数：

- `--mode`：运行模式
- `--target-dir`：指定 SVG 输入目录
- `--target-file`：单图处理时指定文件名
- `--output-dir`：指定结果输出目录
- 环境变量：`CAD_RULE_CHECKER_RUN_MODE`、`CAD_RULE_CHECKER_TARGET_DIR`、`CAD_RULE_CHECKER_TARGET_FILE`、`CAD_RULE_CHECKER_OUTPUT_DIR`

## 输出目录说明

- `output/exp_jsonld/`：实验输出的富化 JSON-LD 文件
- `output/exp_viz/`：知识图谱可视化图像
- `output/svg_ins/`：SVG 元素识别结果
- `output/gt_jsonld/`：真值 JSON-LD
- `output/gt_res/`：真值评估结果
- `output/exp_res/`：规则审查违规结果

## 注意事项

- `src/main.py` 内部包含 LLM 客户端初始化代码，请自行替换或改造为安全的 API Key 管理方式。
- 如果 `pyshacl` 或 `rdflib` 未安装，相关审查功能将无法正常运行。
- 项目当前主要面向实验性规则审查与结果可视化，具体流程可根据业务需求进一步扩展。

## 进一步改进建议

- 增加 `requirements.txt` 或 `pyproject.toml`
- 补齐 `rules/` 规则文件的使用说明与样例
- 添加示例数据和结果展示

## 版权与许可证

本项目未指定许可证。使用前请根据实际需要补充 LICENSE 文件。
