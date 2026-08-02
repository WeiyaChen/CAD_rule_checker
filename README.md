# CAD Rule Checker

`CAD Rule Checker` is a Python toolkit for reviewing architectural CAD drawings / floor plans. It supports DXF-to-SVG conversion, spatial element extraction, topological graph construction, semantic enrichment, and generation of JSON-LD results with visualizations.

## Highlights

- ✅ DXF → SVG conversion
- ✅ Structured extraction of drawing elements and text labels
- ✅ Construction of geometric and topological knowledge graphs
- ✅ Semantic enrichment with optional LLM inference
- ✅ Batch and single-file processing modes
- ✅ Ground truth generation and model evaluation
- ✅ Independent SHACL compliance review (parsing and compliance are decoupled)
- ✅ Web graphical interface for single-file workflows (analysis / comparison / SHACL review / evaluation overview)

## Project Structure

```text
cad_rule_checker/
├── input_data/
│   ├── dxf/                 # Raw DXF files
│   ├── dxf_gt/              # Manually annotated Ground Truth DXF files
│   ├── pickle/              # External instance segmentation pickle cache
│   └── svg/                 # SVG files converted from DXF
├── output/
│   ├── jsonld/              # Semantic-enriched JSON-LD output
│   ├── violations/          # Rule checking violation reports
│   ├── viz/                 # All visualization images (CDT / SVG instance / experiment / GT)
│   ├── gt/                  # Ground truth JSON-LD annotations
│   ├── html/                # HTML evaluation reports
│   └── processed/           # Intermediate SVGs after modification
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
│   ├── experiment/          # Experiment entries (parsing / compliance / GT / evaluation)
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
input_data/dxf/
```

### 2. Convert DXF to SVG

The conversion script reads DXF files from `input_data/dxf/` and outputs SVG to `input_data/svg/`.

From the project root, run the conversion script:

```bash
python -m src.io.dxf_to_svg
```

The converted SVG files will be output to:

```text
input_data/svg/
```

### 3. Run the Drawing Parsing Pipeline (Exp 1-4)

Parsing a drawing and checking it for compliance are two independent stages.
`src/main.py` performs **parsing only** — it extracts elements, builds the
topological knowledge graph, enriches semantics and generates visualizations.
This corresponds to the first four evaluation experiments (Exp 1-4). SHACL
compliance review is handled separately by `compliance_reviewer.py` (Exp 5).

You can control the input path and run mode via command-line arguments:

```bash
python -m src.main --mode SINGLE --target-file sample.svg
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
input_data/dxf_gt/
```

Run the ground truth creation script (single interactive mode, or batch over all
DXF files in the directory):

```bash
python -m src.experiment.ground_truth_creator
python -m src.experiment.ground_truth_creator --mode BATCH
```

### 5. Evaluate Models and Datasets

The evaluation compares the system output against the Ground Truth across five
experiments (geometry / topology / geometric computation / semantic reasoning /
compliance). The two stages of the system pipeline map to two independent
experiment entry points:

```bash
# Parsing (Exp 1-4): end-to-end drawing parsing -> enriched JSON-LD
python -m src.experiment.parsing_pipeline --mode BATCH

# Compliance (Exp 5): SHACL L1/L2/L3 review on the enriched JSON-LD
python -m src.experiment.compliance_reviewer --mode BATCH
```

Then run the batch evaluation:

```bash
python -m src.experiment.dataset_evaluator
```

Results are written to `output/html/overall_results.json` (global summary) and
`output/html/individual_results.csv` (per-file metrics).

### 6. Experiment Entry Points

The `src/experiment/` directory provides decoupled, runnable entry points that
map onto the five evaluation experiments:

- `parsing_pipeline.py` — Drawing parsing (**Exp 1-4**): element extraction,
  topology construction, semantic enrichment, and visualization. Produces
  enriched JSON-LD in `output/jsonld/`.
- `compliance_reviewer.py` — Standalone SHACL compliance review (**Exp 5**):
  reads the enriched JSON-LD and runs L1 semantic / L2 geometric / L3
  topological checks, producing system violation reports and interactive HTML
  reports.
- `ground_truth_creator.py` — Generates human-annotated Ground Truth JSON-LD
  from annotated DXF files (single interactive or batch mode).
- `dataset_evaluator.py` — Batch evaluation comparing system output vs. GT
  across all five experiments.

```bash
# Parsing (Exp 1-4)
python -m src.experiment.parsing_pipeline --mode BATCH

# Compliance review (Exp 5)
python -m src.experiment.compliance_reviewer --mode BATCH

# Ground truth generation (interactive / batch)
python -m src.experiment.ground_truth_creator
python -m src.experiment.ground_truth_creator --mode BATCH

# Evaluation (Exp 1-5)
python -m src.experiment.dataset_evaluator
```

## Web Graphical Interface

A lightweight web UI is provided for interactive, single-file workflows. Start the server from the project root:

```bash
python -m src.web_ui_server
```

Then open `http://localhost:8000` in a browser. The GUI is organized into two categories plus an evaluation overview:

### Category 1 · Normal Use

- **`normal_use.html`** — End-to-End Drawing Analysis: input a single DXF file, the parsing pipeline runs automatically (DXF→SVG → extraction → topology → semantic enrichment → visualization), and the input drawing, topology image, instance image and enriched JSON-LD are displayed.

### Category 2 · Experiments

- **`exp_analysis.html`** — Drawing Analysis (Exp 2.1): input a single DXF file and view the **system result and Ground Truth side by side**. The system parses the drawing and automatically matches the corresponding GT annotation by name.
- **`exp_shacl.html`** — SHACL Review (Exp 2.2): input a single DXF file. The system automatically locates the processed enriched JSON-LD; for a new file it runs the parsing pipeline first, then executes the L1 / L2 / L3 compliance checks and shows the violations plus an interactive annotated report.

### Evaluation Overview

- **`overall_report.html`** — Visualizes `output/html/overall_results.json` (global metrics and per-sample details). Read-only — it does not run batch evaluation.

All pages accept a **single file input**; none run batch processing. Images (SVG / PNG) support **zoom & pan**: scroll to zoom, drag to pan, and double-click or the `⟲` button to reset.

### Backend API

| Method & path | Purpose |
|---|---|
| `GET /api/available-dxfs` | List DXF files under `input_data/dxf` |
| `POST /api/run-analysis` | Single DXF end-to-end analysis (Category 1) |
| `POST /api/experiment-draw` | System vs GT comparison (Exp 2.1) |
| `POST /api/experiment-shacl` | SHACL compliance review (Exp 2.2) |
| `POST /api/upload-dxf` | Upload DXF files |
| `GET /api/preview?path=` | Preview a file (SVG / PNG / HTML / JSON) |
| `GET /api/evaluation-data` | Read `overall_results.json` and `individual_results.csv` |

> Note: `manual.html` is a legacy pure-frontend prototype (canvas graph editor) and retains its built-in zh/en toggle.

## Key Configuration Files

- [src/config/settings.yaml](src/config/settings.yaml) — Input, output, rule, and prompt path settings
- [prompt/prompt_config.txt](prompt/prompt_config.txt) — LLM prompt template
- [rules/](rules/) — SHACL rule files

## Run Modes

The main entry point supports the following modes, configurable via the settings file or command-line arguments:

- `SINGLE` — Process a single SVG file
- `BATCH` — Process all SVG files in a specified directory

### Common Arguments

- `--mode` — Run mode
- `--target-dir` — SVG input directory name
- `--target-file` — File name for single-file mode
- `--output-dir` — Output directory name
- Environment variables: `CAD_RULE_CHECKER_RUN_MODE`, `CAD_RULE_CHECKER_TARGET_DIR`, `CAD_RULE_CHECKER_TARGET_FILE`, `CAD_RULE_CHECKER_OUTPUT_DIR`

## Output Directory Overview

- `output/jsonld/` — Semantic-enriched JSON-LD output
- `output/violations/` — SHACL rule checking violation reports
- `output/viz/` — All visualization images (CDT, SVG instance, experiment, GT previews)
- `output/gt/` — Ground truth JSON-LD annotations
- `output/html/` — HTML evaluation reports and compliance review reports
- `output/processed/` — Intermediate SVGs after svg_modifier processing

## Notes

- `src/main.py` contains LLM client initialization code. Replace or refactor it to use a secure API key management approach before deployment.
- The SHACL-based rule checking will not work without `pyshacl` and `rdflib` installed.
- This project is currently designed for **experimental** rule checking and result visualization. The pipeline can be extended for production use cases as needed.

## Suggested Improvements

- Add usage documentation and examples for the `rules/` SHACL files
- Add sample data and result demonstrations

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
