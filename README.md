# CAD Rule Checker

`CAD Rule Checker` is a Python toolkit for reviewing architectural CAD drawings / floor plans. It supports DXF-to-SVG conversion, spatial element extraction, topological graph construction, semantic enrichment, and generation of JSON-LD results with visualizations.

## Highlights

- ✅ DXF → SVG conversion
- ✅ Structured extraction of drawing elements and text labels
- ✅ Construction of geometric and topological knowledge graphs
- ✅ Semantic enrichment with optional LLM inference
- ✅ Batch and single-file processing modes
- ✅ Ground truth generation and model evaluation

## Project Structure

```text
cad_rule_checker/
├── data/
│   ├── processed/
│   │   └── svg/             # Files after primitive recognition by deep learning models
│   └── raw/
│       ├── dxf/             # Raw DXF files
│       ├── dxf_extend/      # Manually annotated or extended DXF files
│       ├── pickle/          # Intermediate pickle data
│       └── svg/             # SVG files converted from DXF
├── output/
│   ├── cdt/
│   ├── exp_jsonld/          # Semantic-enriched JSON-LD output
│   ├── exp_res/             # Rule checking results
│   ├── exp_viz/             # Visualization output
│   ├── gt_jsonld/           # Ground truth JSON-LD
│   ├── gt_res/              # Ground truth evaluation results
│   ├── gt_viz/
│   └── svg_ins/             # Instance recognition visualization
├── prompt/
│   └── prompt_config.txt    # LLM prompt configuration
├── rules/
│   ├── exp.ttl
│   ├── l1_semantic_check.ttl
│   ├── l2_geometric_check.ttl
│   └── l3_topological_check.ttl
├── src/
│   ├── compliance/          # SHACL validation engine
│   ├── config/              # Configuration and directory constants
│   ├── core/                # Core geometry and spatial objects
│   ├── enricher/            # Graph enrichment and semantic extensions
│   ├── experiment/          # Evaluation and ground truth scripts
│   ├── io/                  # DXF/SVG reading, writing, and conversion
│   ├── topology/            # Topology construction and graph analysis
│   ├── utils/               # Visualization and utility tools
│   ├── main.py              # Main entry point
│   └── processor.py         # Drawing processing pipeline
└── README.md
```

## Environment and Dependencies

### Setting Up a Virtual Environment

It is **highly recommended** to use a virtual environment to isolate project dependencies. Create and activate one as follows:

```bash
# Create a virtual environment (e.g., named myvenv or cadruler)
python -m venv myvenv

# Activate it
# On Windows:
venv\Scripts\activate
# On macOS / Linux:
source venv/bin/activate
```

After activation, install the required packages (see below). To deactivate the virtual environment later, simply run `deactivate`.

### Python Version

Python **3.10+** is recommended. The project has been tested with **Python 3.13**.

### Important: Python 3.13 Removed the `cgi` Module

Starting from **Python 3.13**, the standard library modules `cgi` and `cgitb` have been **removed** (as per [PEP 594](https://peps.python.org/pep-0594/)). This project's `src/web_ui_server.py` imports `cgi`, so **if you are using Python 3.13 or later**, you must install the `legacy-cgi` compatibility package:

```bash
pip install legacy-cgi
```

The existing `cadruler/` virtual environment in this repository already has `legacy-cgi` installed.

### Installing Dependencies

Install the necessary packages:

```bash
pip install ezdxf openai pyyaml rdflib pyshacl matplotlib lxml numpy pandas svgpathtools opencv-python triangle networkx pyvis shapely scikit-learn
```

If you plan to run ground truth generation and evaluation scripts, you may also need:

```bash
pip install shapely
```

> **Note**: A [`requirements.txt`](requirements.txt) is provided at the project root. You can install all dependencies at once with:
>
> ```bash
> pip install -r requirements.txt
> ```

## Quick Start

### 1. Prepare DXF Input

Place the DXF files to be processed in:

```text
data/raw/dxf/
```

### 2. Convert DXF to SVG

The conversion script reads DXF files from `data/raw/dxf/` and outputs SVG to `data/raw/svg/`.

From the project root, run the conversion script:

```bash
python -m src.io.dxf_to_svg
```

The converted SVG files will be output to:

```text
data/raw/svg/
```

### 3. Run the Main Checking Pipeline

You can control the input path and run mode via command-line arguments:

```bash
python -m src.main --mode SINGLE --target-file nanyangmingmen150.svg
```

Alternatively, modify the `runtime` section in the configuration file [src/config/settings.yaml](src/config/settings.yaml) and then run:

```bash
python -m src.main
```

The program will execute:

- Primitive extraction and element visualization
- Topological graph construction
- Semantic enrichment and JSON-LD output
- Visualization generation

### 4. Generate Ground Truth Data

Place manually annotated or extended DXF files in:

```text
data/raw/dxf_extend/
```

Run the ground truth creation script:

```bash
python -m src.experiment.ground_truth_creator
```

### 5. Evaluate Models and Datasets

Configure the directory settings in `src/experiment/dataset_evaluator.py` and run:

```bash
python -m src.experiment.dataset_evaluator
```

## Key Configuration Files

- [src/config/settings.yaml](src/config/settings.yaml) — Input, output, rule, and prompt path settings
- [prompt/prompt_config.txt](prompt/prompt_config.txt) — LLM prompt template
- [rules/](rules/) — SHACL rule files

## Run Modes

The main entry point supports the following modes, configurable via the settings file or command-line arguments:

- `SINGLE` — Process a single SVG file
- `BATCH` — Process all SVG files in a specified directory
- `DEFAULT` — Process the default directory configured in `settings.yaml`

### Common Arguments

- `--mode` — Run mode
- `--target-dir` — SVG input directory name
- `--target-file` — File name for single-file mode
- `--output-dir` — Output directory name
- Environment variables: `CAD_RULE_CHECKER_RUN_MODE`, `CAD_RULE_CHECKER_TARGET_DIR`, `CAD_RULE_CHECKER_TARGET_FILE`, `CAD_RULE_CHECKER_OUTPUT_DIR`

## Output Directory Overview

- `output/exp_jsonld/` — Enriched JSON-LD files from experiments
- `output/exp_viz/` — Knowledge graph visualization images
- `output/svg_ins/` — Instance recognition results
- `output/gt_jsonld/` — Ground truth JSON-LD files
- `output/gt_res/` — Ground truth evaluation results
- `output/exp_res/` — Rule checking violation results

## Notes

- `src/main.py` contains LLM client initialization code. Replace or refactor it to use a secure API key management approach before deployment.
- The SHACL-based rule checking will not work without `pyshacl` and `rdflib` installed.
- This project is currently designed for **experimental** rule checking and result visualization. The pipeline can be extended for production use cases as needed.

## Suggested Improvements

- Add usage documentation and examples for the `rules/` SHACL files
- Add sample data and result demonstrations

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
