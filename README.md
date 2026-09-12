# CAD Rule Checker

`CAD Rule Checker` is a Python toolkit for reviewing architectural CAD drawings / floor plans. It supports DXF-to-SVG conversion, spatial element extraction, topological graph construction, semantic enrichment, and generation of JSON-LD results with visualizations.

## Highlights

- ✅ DXF → SVG conversion
- ✅ Structured extraction of drawing elements and text labels
- ✅ Construction of geometric and topological knowledge graphs
- ✅ Pluggable spatial algorithms (contour extraction & space-type recognition)
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
│   ├── viz/                 # All visualization images (floor plan / SVG instance / experiment / GT)
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
│   ├── enricher/            # Graph enrichment and semantic extensions
│   ├── experiment/          # Experiment entries (parsing / compliance / GT / evaluation)
│   ├── io/                  # DXF/SVG reading, writing, and conversion
│   ├── spatial/             # Pluggable spatial layer: contour extraction, space typing, primitives, viz
│   ├── topology/            # Component aggregation, topology construction, graph analysis
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

### Environment Variables Configuration (Security Best Practice)

This project uses **environment variables** to manage sensitive information like API keys. This is a security best practice that prevents sensitive data from being committed to version control.

#### Setup Environment Variables

1. **Copy the example environment file:**

```bash
cp .env.example .env
```

2. **Edit the `.env` file and add your configuration:**

```bash
# Required: OpenAI-compatible API key for LLM services
CAD_RULE_CHECKER_LLM_API_KEY=your_actual_api_key_here

# Optional: Custom API base URL (overrides settings.yaml)
CAD_RULE_CHECKER_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/

# Optional: Custom model name (overrides settings.yaml)
CAD_RULE_CHECKER_LLM_MODEL=glm-4-flash
```

**Why manage all LLM configs together?**
- 🔒 **Security**: Prevents sensitive API keys from being committed to version control
- 🚀 **Flexibility**: Easy to switch between different environments (dev/staging/prod)
- 🎯 **Consistency**: All LLM-related configurations in one place
- 🧪 **Experimentation**: Easy to test different models and endpoints

**Loading is automatic** — no `export` required. [src/config/config.py](src/config/config.py) reads
the project-root `.env` the first time the config module is imported, so every entry point
([src/main.py](src/main.py), [src/web_ui_server.py](src/web_ui_server.py), the scripts under
[src/experiment/](src/experiment/)) picks it up. The parsing follows the usual dotenv rules:

- keys already present in the process environment are **never** overwritten, so a shell `export`
  or a CI variable wins over `.env`;
- `#` starts a comment on its own line, and an unquoted value is truncated at a trailing ` #`;
- `export KEY=value` lines and single/double-quoted values are accepted;
- a missing `.env` is silently ignored.

To bypass `.env` entirely — for instance to force the no-LLM rule-based path — set
`CAD_RULE_CHECKER_SKIP_DOTENV=1`. Use that flag rather than blanking the key: in PowerShell
`$env:X=""` *deletes* the variable instead of emptying it.

#### Alternative Configuration Methods

If you prefer not to use a `.env` file, you can also set environment variables directly:

**Windows PowerShell:**
```powershell
# Set all LLM configurations
$env:CAD_RULE_CHECKER_LLM_API_KEY="your_api_key_here"
$env:CAD_RULE_CHECKER_LLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4/"
$env:CAD_RULE_CHECKER_LLM_MODEL="glm-4-flash"
```

**Linux/macOS:**
```bash
# Set all LLM configurations
export CAD_RULE_CHECKER_LLM_API_KEY="your_api_key_here"
export CAD_RULE_CHECKER_LLM_BASE_URL="https://open.bigmodel.cn/api/paas/v4/"
export CAD_RULE_CHECKER_LLM_MODEL="glm-4-flash"
```

**Or modify the configuration file** (not recommended for production):
- Edit [src/config/settings.yaml](src/config/settings.yaml) and set values directly in the `llm` section
- ⚠️ This approach is less secure and not recommended for production environments

#### Configuration Priority

The system reads LLM configurations in the following priority order:
1. **Environment variables** (highest priority) - overrides everything; the `.env` file is merged in at this level, filling only the keys that are not already set
2. **Configuration file** ([src/config/settings.yaml](src/config/settings.yaml)) - fallback defaults
3. **Hardcoded defaults** - if neither above is available

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

#### BATCH Mode

To process **all** SVG files in a directory at once, use `--mode BATCH` and
point `--target-dir` at the folder containing the SVG files:

```bash
python -m src.main --mode BATCH
```

Optionally, specify a custom output directory with `--output-dir`:

```bash
python -m src.main --mode BATCH --target-dir input_data/svg --output-dir output/jsonld
```

In BATCH mode `src/main.py` will:

- Scan the target directory and pick up every `*.svg` file (files are
  processed in directory order)
- Run the parsing pipeline on each drawing (the same Exp 1-4 steps as
  SINGLE mode)
- Print a summary report at the end with the total number of drawings,
  how many parsed successfully, and how many failed

Alternatively, modify the `runtime` section in the configuration file [src/config/settings.yaml](src/config/settings.yaml) (set `run_mode: BATCH` and the target directory) and then run:

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

Results are written to `output/html/` as two separate groups of files:

- **Core experiments** (geometry / topology / geometric computation / semantic),
  grouped together:
  - `output/html/overall_results.json` (global summary)
  - `output/html/individual_results.csv` (per-file metrics)
- **SHACL compliance** (Exp 5), saved and displayed on their own:
  - `output/html/compliance_results.json` (global summary)
  - `output/html/compliance_individual_results.csv` (per-file metrics)

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

### 7. Knowledge Graph Browser (multi-view)

`src/utils/kg_browser.py` renders **one self-contained interactive HTML per
drawing** with three tabs, so you can inspect both the whole knowledge graph and
how the enrichment pipeline changes it step by step (replaces the former
`suite_viz.py`):

- **全图 Knowledge Graph** — the whole `@graph` as a force-directed graph: all
  node types (Space / Suite / Door / Window / FunctionalElement) and all relations
  (`bot:adjacentZone` / `bot:containsElement` / `bot:interfaceOf` /
  `bot:hasSpace` / `bot:hasSubZone`), switchable by enrichment stage and filterable
  by edge type; click a node to see its id/group.
- **富化过程 Stages** — step through the enrichment pipeline (raw → semantic →
  geometry → ACD → geometry² → topology), highlighting nodes/edges **added
  (green) / removed (red)** versus the previous stage, plus per-stage stats.
- **套型从属 Suite** — the suite containment report: color-coded floor plan (one
  color per suite; public/unassigned hatched gray), membership table and
  auto-detected anomaly flags (suite count vs. the `<N>suite` expectation, a suite
  swallowing >75% of private spaces, 1-space suites, unassigned spaces).

The stage browser replays the pipeline from `<base>_raw.jsonld` + `<base>.svg`;
single-file mode uses the configured LLM client for a faithful replay
(`--no-llm` falls back to the rule-based sandbox).

```bash
# Single file (faithful LLM replay)
python -m src.utils.kg_browser --base "2suite (1)"

# Sandbox (rule-based) replay
python -m src.utils.kg_browser --base "2suite (1)" --no-llm

# Batch over all drawings
python -m src.utils.kg_browser --mode BATCH --out-dir output/viz
```

Output: `<base>_kg_browser.html` (plus `<base>_suites.png` for the Suite tab) in
`output/viz/`. Requires `vis.js` from CDN (consistent with the existing pyvis
usage).

## Web Graphical Interface

A lightweight web UI is provided for interactive, single-file workflows. Start the server from the project root:

```bash
python -m src.web_ui_server
```

Then open `http://localhost:8001` in a browser. The GUI is organized into two categories plus an evaluation overview:

### Spatial algorithm selection

All three single-DXF pages (Category 1 and both experiments) expose the same
**Spatial Algorithms** panel in the sidebar. It lists every registered contour
extraction and space-type classification algorithm (loaded from
`GET /api/spatial-algos`, i.e. from `src/spatial/registry.py`), pre-selects the
`settings.yaml` defaults, shows whether the LLM is available, and lets you tick
*忽略缓存，强制重新解析* to ignore cached results.

Each run reports which algorithms produced the displayed result, and the
contour visualization follows the selected algorithm (`<base>_cdt.png`,
`<base>_rgp.png`, …). Cached results are **only reused when the requested
algorithms and the LLM availability match the ones recorded in
`output/jsonld/<base>.run.json`** — otherwise the drawing is re-parsed, so the
page can never show a stale graph (for example one produced before an LLM key
was configured).

### Category 1 · Normal Use

- **`normal_use.html`** — End-to-End Drawing Analysis: input a single DXF file, the parsing pipeline runs automatically (DXF→SVG → extraction → topology → semantic enrichment → visualization), and the input drawing, topology image, instance image and enriched JSON-LD are displayed.

### Category 2 · Experiments

- **`exp_analysis.html`** — Drawing Analysis (Exp 2.1): input a single DXF file and view the **system result and Ground Truth side by side**. The system parses the drawing and automatically matches the corresponding GT annotation by name. It also displays the **space contour extraction image of the selected algorithm** and a **side-by-side interactive JSON-LD knowledge graph comparison** (System vs GT, each pane is the `kg_browser` view).
- **`exp_shacl.html`** — SHACL Review (Exp 2.2): input a single DXF file. The system automatically locates the processed enriched JSON-LD; for a new file it runs the parsing pipeline first, then executes the L1 / L2 / L3 compliance checks and shows the violations plus an interactive annotated report.
- **`kg_browser.html`** — Knowledge Graph Browser (**standalone tool**): pick a processed drawing and a source (`System` or `GT`) and load **one knowledge graph at a time** into the interactive browser produced by `src/utils/kg_browser.py` (whole graph / stages / suite tabs). Tick “包含富化过程” to replay the six enrichment stages for the system side (uses the LLM, slower). System vs GT comparison is intentionally left to `exp_analysis.html` (Exp 2.1).

### Evaluation Overview

- **`overall_report.html`** — Visualizes `output/html/overall_results.json` (global metrics and per-sample details). Read-only — it does not run batch evaluation.

All pages accept a **single file input**; none run batch processing. Images (SVG / PNG) support **zoom & pan**: scroll to zoom, drag to pan, and double-click or the `⟲` button to reset.

### Backend API

| Method & path | Purpose |
|---|---|
| `GET /api/available-dxfs` | List DXF files under `input_data/dxf` |
| `GET /api/spatial-algos` | List selectable spatial algorithms (contour extraction / space-type classification), their defaults and the LLM status |
| `POST /api/run-analysis` | Single DXF end-to-end analysis (Category 1) |
| `POST /api/experiment-draw` | System vs GT comparison (Exp 2.1) |
| `POST /api/experiment-shacl` | SHACL compliance review (Exp 2.2) |
| `POST /api/upload-dxf` | Upload DXF files |
| `GET /api/preview?path=` | Preview a file (SVG / PNG / HTML / JSON) |
| `GET /api/evaluation-data` | Read `overall_results.json` and `individual_results.csv` |
| `GET /api/kg-files` | List datasets for the KG browser (system JSON-LD + matching GT) |
| `GET /api/kg-browser?base=&src=&stages=&refresh=` | Generate/serve the KG browser HTML for a dataset (`src=system`\|`gt`, `stages=1` replays the enrichment pipeline) |

The three single-DXF endpoints accept optional `contourAlgo`, `classifierAlgo`
and `forceReparse` fields (the same names as the CLI `--contour-algo` /
`--classifier-algo` arguments); an unknown algorithm name is rejected with HTTP
400. Responses echo back `contourAlgo` / `classifierAlgo` / `llmEnabled` /
`llmModel` together with `reused`, which tells the UI whether the shown result
was re-parsed or reused from the cache.

> Note: `manual.html` is a legacy pure-frontend prototype (canvas graph editor) and retains its built-in zh/en toggle.

## Key Configuration Files

- [src/config/settings.yaml](src/config/settings.yaml) — Input, output, rule, prompt, and `spatial` algorithm settings
- [prompt/prompt_config.txt](prompt/prompt_config.txt) — LLM prompt template
- [rules/](rules/) — SHACL rule files

## Pluggable Spatial Algorithms

Two pipeline tasks are isolated behind abstract interfaces so that new algorithms of
the same kind can be added without touching the pipeline:

| Task | Interface | Registry | Default |
| --- | --- | --- | --- |
| Spatial contour extraction | `ISpatialContourExtractor` | `CONTOUR_EXTRACTORS` | `CDT` |
| Space type recognition | `ISpaceTypeClassifier` | `SPACE_TYPE_CLASSIFIERS` | `LLMMultiStage` |
| Text label normalization | `ITextLabelNormalizer` | `TEXT_LABEL_NORMALIZERS` | `LLM` |

All of them live in [src/spatial/](src/spatial/); the pipeline only talks to the
factory in [src/spatial/factory.py](src/spatial/factory.py) and to the algorithm-neutral
domain objects in [src/spatial/domain.py](src/spatial/domain.py). JSON-LD details are
confined to the two adapters, [src/topology/builder.py](src/topology/builder.py) and
[src/enricher/semantic_enricher.py](src/enricher/semantic_enricher.py).

Everything the spatial pipeline needs sits in that package, so the algorithm-adjacent
code is no longer scattered over `topology/` and `utils/`:

| Module | Responsibility |
| --- | --- |
| [contracts.py](src/spatial/contracts.py) / [domain.py](src/spatial/domain.py) | Interfaces and the plain objects algorithms exchange |
| [registry.py](src/spatial/registry.py) / [factory.py](src/spatial/factory.py) / [config.py](src/spatial/config.py) | Name resolution, construction, `settings.yaml` parsing |
| [primitives.py](src/spatial/primitives.py) | Boundary-primitive preparation (`clean_lines`) — the shared input of every contour algorithm |
| [contours/](src/spatial/contours/) | Contour extraction algorithms (`cdt.py`, `rgp.py`) plus the shared `filters.py` |
| [classifiers/](src/spatial/classifiers/) | Space type recognition algorithms |
| [visualization.py](src/spatial/visualization.py) | Algorithm-neutral plot of an extraction result (`plot_floor_plan`) |

[src/topology/builder.py](src/topology/builder.py) is now pure orchestration
(boundary primitives → extractor → BOT graph), and component aggregation moved out of it
into [src/topology/components.py](src/topology/components.py).

The old module paths below were removed rather than forwarded, so any historical script
using them must be pointed at the new location:

| Removed path | Where the code lives now |
| --- | --- |
| `src.topology.preprocessing.clean_lines` | [src/spatial/primitives.py](src/spatial/primitives.py) |
| `src.topology.generate_virtual_wall.FloorPlanMeshBuilderCDT` | dropped — use `CDTContourExtractor` in [src/spatial/contours/cdt.py](src/spatial/contours/cdt.py), or `create_contour_extractor("CDT")` |
| `src.utils.cdt_viz.plot_floor_plan` | [src/spatial/visualization.py](src/spatial/visualization.py) |

Select an algorithm from the command line (any registered name or alias):

```bash
# list everything that is registered
python -m src.experiment.parsing_pipeline --list-algos

# use the LLM-driven classifier (default) or the geometry-only dictionary matcher
python -m src.main --mode SINGLE --target-file sample.svg --classifier-algo LLMMultiStage
python -m src.main --mode SINGLE --target-file sample.svg --classifier-algo TextMatching

# use the CDT triangulation extractor (default) or rule-based geometric polygonization
python -m src.main --mode SINGLE --target-file sample.svg --contour-algo CDT
python -m src.main --mode SINGLE --target-file sample.svg --contour-algo RGP
```

Or configure it in the `spatial` section of [src/config/settings.yaml](src/config/settings.yaml):

```yaml
spatial:
  contour:
    algorithm: "CDT"
    params:                     # parameters shared by every contour algorithm
      min_area_mm2: 2000000.0
      # …
    algorithm_params:           # per-algorithm block, only merged when that algorithm is selected
      RGP:
        snap_tol_mm: 10.0
        max_gap_mm: 3000.0
  classification:
    algorithm: "LLMMultiStage"
    params:
      match_tolerance_mm: 0.0
      min_confidence: 0.5
```

`params` keys must be accepted by the constructor of the *selected* algorithm, otherwise
creation fails fast with a `TypeError`. Algorithm-specific knobs therefore belong in
`algorithm_params.<NAME>` (matched case-insensitively, aliases included) — that way you can
switch between algorithms freely without having to comment parameters in and out.

### Available Contour Extractors

| Name | Aliases | How it works |
| --- | --- | --- |
| `CDT` | `CDT_MESH`, `TRIANGLE_CDT` | Constrained Delaunay triangulation of the wall/door-constrained mesh; rooms are grown over the triangle graph and door/window openings are sealed with virtual blocker edges. |
| `RGP` | `RULE_BASED`, `POLYGONIZE`, `GEOMETRIC_POLYGONIZATION` | Rule-based geometric polygonization — purely combinatorial, no CDT mesh. |

`RGP` ([src/spatial/contours/rgp.py](src/spatial/contours/rgp.py)) consumes the same predicted
boundary primitives (wall segments + door/window patches) and runs:

1. **Coordinate normalization** — quantize to `coord_precision_mm`.
2. **Duplicate removal** — drop zero-length/degenerate segments (`dup_tol_mm`).
3. **Endpoint snapping** — weld endpoints that are within `snap_tol_mm` (with cluster arithmetic means).
4. **Collinear segment merging** — unify touching/overlapping intervals on one line (`collinear_angle_tol_deg`, `collinear_offset_tol_mm`).
5. **Short-gap completion** — two routes: bridge a gap between two collinear wall lines whose endpoints keep going away in the bridge direction, and seal door/window openings with an edge parallel to the opening edge (`max_gap_mm`, `gap_angle_tol_deg`).
6. **Segment intersection and splitting** — insert every crossing point so segments only meet at endpoints.
7. **Planar graph construction** — build a rotation system (sorted neighbours per node).
8. **Polygonization** — trace every inner face of the planar embedding.
9. **Small/slender-region filtering** — drop implausible rooms via the shared `SpaceShapeFilter` (`min_area_mm2`, `erode_mm`, `min_width_mm`, `min_compactness`, `min_solidity`).
10. **Exterior-face removal** — discard unbounded faces so only real rooms remain.

Both contour algorithms share the room-plausibility defences in
[src/spatial/contours/filters.py](src/spatial/contours/filters.py), so the same
`params` block applies to either one.

Trade-off to be aware of: on the drawings tested, RGP's room set is a strict refinement of
CDT's (it never invents a room outside a CDT room), and it correctly splits several rooms
that CDT merges through unsealed openings. Because step 9 *filters* rather than *absorbs*,
the sub-`min_area_mm2` leftovers (wall cavities, stair/duct cells) are reported as no room
instead of being folded into a neighbour, so the total extracted area is a few percent
smaller than CDT's.

### Adding a New Algorithm

1. Implement the interface in `src/spatial/contours/` (for contour extraction) or
   `src/spatial/classifiers/` (for space typing), and decorate the class with the
   matching registry, e.g. `@CONTOUR_EXTRACTORS.register("MyAlgo", aliases=("MY",))`.
   Constructor parameters must be keyword arguments; unknown keyword arguments raise
   `TypeError` at creation time, so typos in `settings.yaml` fail fast. Set a class-level
   `name` and, for contour extractors, a `visualization_suffix` (e.g. `"myalgo"`) — the
   pipeline uses it to name its floor-plan plot `output/viz/<drawing>_myalgo.png`.
2. Import the module from the package `__init__.py` so the registration runs.
3. Point `spatial.contour.algorithm` / `spatial.classification.algorithm` (or the
   `--contour-algo` / `--classifier-algo` arguments) at the new name, and put any
   algorithm-specific parameters under `spatial.contour.algorithm_params.<NAME>`.

Algorithm instances can also be injected directly — `TopologyBuilder(contour_extractor=…)`,
`GraphEnrichmentPipeline(…, classifier=…)` and `process_single_drawing(…, classifier=…)`
all accept a pre-built object for callers that manage the lifecycle themselves. The
historical `FloorPlanMeshBuilderCDT` class and its module (`src/topology/generate_virtual_wall.py`)
were both removed; use `CDTContourExtractor` itself.

## Run Modes

The main entry point supports the following modes, configurable via the settings file or command-line arguments:

- `SINGLE` — Process a single SVG file
- `BATCH` — Process all SVG files in a specified directory

### Common Arguments

- `--mode` — Run mode
- `--target-dir` — SVG input directory name
- `--target-file` — File name for single-file mode
- `--output-dir` — Output directory name
- `--contour-algo` — Spatial contour extraction algorithm (default from `settings.yaml`)
- `--classifier-algo` — Space type recognition algorithm (default from `settings.yaml`)
- `--list-algos` — Print the registered spatial algorithms and exit (`parsing_pipeline` only)
- Environment variables: `CAD_RULE_CHECKER_RUN_MODE`, `CAD_RULE_CHECKER_TARGET_DIR`, `CAD_RULE_CHECKER_TARGET_FILE`, `CAD_RULE_CHECKER_OUTPUT_DIR`, `CAD_RULE_CHECKER_CONTOUR_ALGO`, `CAD_RULE_CHECKER_CLASSIFIER_ALGO`

## Output Directory Overview

- `output/jsonld/` — Semantic-enriched JSON-LD output
- `output/violations/` — SHACL rule checking violation reports
- `output/viz/` — All visualization images (floor-plan contours `<drawing>_<algorithm>.png` — e.g. `_cdt.png` / `_rgp.png` — plus SVG instance, experiment, and GT previews)
- `output/gt/` — Ground truth JSON-LD annotations
- `output/html/` — HTML evaluation reports and compliance review reports
- `output/processed/` — Intermediate SVGs after svg_modifier processing

## Notes

- `src/main.py` contains LLM client initialization code. Replace or refactor it to use a secure API key management approach before deployment.
- The SHACL-based rule checking will not work without `pyshacl` and `rdflib` installed.
- This project is currently designed for **experimental** rule checking and result visualization. The pipeline can be extended for production use cases as needed.
- Without an LLM API key the semantic stage falls back to a built-in sandbox mapping
  (`次卧`/`主卫`/`餐客厅` plus a fixed stage-3 inference table), which is why the default
  `LLMMultiStage` classifier recognises very few space types on real drawings.
- The BOT topology relations (`bot:adjacentZone`, `bot:interfaceOf`, `bot:containsElement`)
  are built from unordered sets, so their order — and therefore `*_topology.png` — is
  **not reproducible between runs**. Compare JSON-LD by node content, not by byte.
- In `LLMMultiStage`, the three `[Stage n]` headers are printed while the classifier runs,
  so all `[+] …` result lines appear after the last header rather than interleaved.

## Utility Scripts

- `scripts/clean_generated.py` — delete all code-generated files under `output/`
  in one shot (JSON-LD, visualizations, reports, violations, GT JSON-LD,
  intermediate SVGs) while keeping the directory structure. `input_data/` is
  never touched (raw DXF, annotated GT DXF, converted SVGs, pickle cache all
  preserved).

  ```bash
  python scripts/clean_generated.py --dry-run   # preview only
  python scripts/clean_generated.py --yes       # delete immediately
  ```

- `scripts/check_ui_endpoints.py` — check the web UI backend endpoints.
- `scripts/run_step_test.py` — run a single pipeline step.

## Suggested Improvements

- Add usage documentation and examples for the `rules/` SHACL files
- Add sample data and result demonstrations

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
