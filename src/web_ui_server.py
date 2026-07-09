"""UI server for the CAD rule checker pipeline."""
import os
os.environ.setdefault('MPLBACKEND', 'Agg')  # force non-interactive backend BEFORE any matplotlib import

import csv
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import cgi
import shutil
from io import BytesIO

from src.config.config import settings
from src.io.dxf_to_svg import convert_dxf_to_svg

ROOT = Path(__file__).resolve().parent.parent


def _repo_rel(path: Path | str) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _safe_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (ROOT / candidate).resolve()

    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return resolved


class UIHandler(BaseHTTPRequestHandler):
    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/available-inputs':
            self._send_json(self._available_inputs())
            return
        if parsed.path == '/api/list-files':
            self._send_json(self._list_files(parse_qs(parsed.query).get('path', [''])[0]))
            return
        if parsed.path == '/api/preview':
            self._serve_preview(parse_qs(parsed.query).get('path', [''])[0])
            return
        if parsed.path == '/api/evaluation-data':
            self._send_json(self._evaluation_data())
            return

        file_path = parsed.path.lstrip('/')
        if not file_path:
            file_path = 'index.html'

        target = (ROOT / file_path).resolve()
        try:
            target.relative_to(ROOT.resolve())
        except ValueError:
            self.send_error(403)
            return

        if not target.exists() or not target.is_file():
            self.send_error(404)
            return

        content_type = 'application/octet-stream'
        if target.suffix.lower() == '.html':
            content_type = 'text/html; charset=utf-8'
        elif target.suffix.lower() == '.js':
            content_type = 'application/javascript; charset=utf-8'
        elif target.suffix.lower() == '.css':
            content_type = 'text/css; charset=utf-8'
        elif target.suffix.lower() == '.json':
            content_type = 'application/json; charset=utf-8'
        elif target.suffix.lower() == '.svg':
            content_type = 'image/svg+xml'
        elif target.suffix.lower() in {'.png', '.jpg', '.jpeg'}:
            content_type = 'image/' + target.suffix.lower().lstrip('.')

        body = target.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        print('Incoming POST path:', parsed.path)
        if parsed.path == '/api/run-pipeline':
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length).decode('utf-8') if length else '{}'
            try:
                data = json.loads(body or '{}')
            except json.JSONDecodeError:
                self._send_json({'ok': False, 'error': 'invalid_json'}, 400)
                return

            mode = str(data.get('mode', 'SINGLE')).upper()
            target_dir = data.get('targetDir') or ''
            target_file = data.get('targetFile') or ''
            output_dir = data.get('outputDir') or 'output/exp_jsonld'

            cmd = [sys.executable, '-m', 'src.main', '--mode', mode]
            if target_dir:
                cmd += ['--target-dir', str(target_dir)]
            if target_file:
                cmd += ['--target-file', str(target_file)]
            if output_dir:
                cmd += ['--output-dir', str(output_dir)]

            try:
                env = os.environ.copy()
                env['PYTHONUTF8'] = '1'
                proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=1800)
                stdout = proc.stdout or ''
                stderr = proc.stderr or ''
                self._send_json({
                    'ok': proc.returncode == 0,
                    'returnCode': proc.returncode,
                    'stdout': stdout,
                    'stderr': stderr,
                    'outputDir': output_dir,
                    'files': self._list_files(output_dir)
                })
            except subprocess.TimeoutExpired as exc:
                self._send_json({'ok': False, 'error': 'timeout', 'stdout': (exc.stdout or ''), 'stderr': (exc.stderr or '')}, 504)
            return

        if parsed.path == '/api/run-evaluation':
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length).decode('utf-8') if length else '{}'
            try:
                data = json.loads(body or '{}')
            except json.JSONDecodeError:
                self._send_json({'ok': False, 'error': 'invalid_json'}, 400)
                return

            sys_out_dir = data.get('sysOutDir') or 'output/exp_jsonld'
            gt_dir = data.get('gtDir') or 'output/gt_jsonld'
            violation_dir = data.get('violationDir') or ''
            eval_output_dir = data.get('evalOutputDir') or 'output/html'

            sys_out_path = (ROOT / sys_out_dir).resolve()
            gt_path = (ROOT / gt_dir).resolve()
            violation_path = (ROOT / violation_dir).resolve() if violation_dir else None
            eval_out_path = (ROOT / eval_output_dir).resolve()
            eval_out_path.mkdir(parents=True, exist_ok=True)

            try:
                from src.experiment.dataset_evaluator import BatchDatasetEvaluator

                evaluator = BatchDatasetEvaluator(
                    gt_dir=str(gt_path),
                    sys_out_dir=str(sys_out_path),
                    violation_dir=str(violation_path) if violation_path else None,
                    output_dir=str(eval_out_path)
                )
                evaluator.run_evaluation()

                # Load and return the overall results
                overall_file = eval_out_path / 'overall_results.json'
                msg = ''
                if overall_file.exists():
                    msg = f'Results saved to {_repo_rel(eval_out_path)}'
                self._send_json({'ok': True, 'message': msg})
            except Exception as ex:
                self._send_json({'ok': False, 'error': str(ex)}, 500)
            return

        # Upload DXF files via multipart/form-data
        if parsed.path == '/api/upload-dxf':
            # parse multipart
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD': 'POST'})
            target_dir = form.getvalue('targetDir') or 'uploads'
            save_dir = settings.dxf_data_path / target_dir
            save_dir.mkdir(parents=True, exist_ok=True)
            saved = []
            for field in form.list or []:
                if field.filename:
                    filename = Path(field.filename).name
                    out_path = save_dir / filename
                    with open(out_path, 'wb') as out_f:
                        shutil.copyfileobj(field.file, out_f)
                    saved.append(_repo_rel(out_path))
            self._send_json({'ok': True, 'saved': saved, 'targetDir': _repo_rel(save_dir)})
            return

        # Run a specific pipeline step (dxf2svg, extract-elements, build-topology, enrich-graph, visualize-graph)
        if parsed.path == '/api/run-step':
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length).decode('utf-8') if length else '{}'
            try:
                data = json.loads(body or '{}')
            except json.JSONDecodeError:
                self._send_json({'ok': False, 'error': 'invalid_json'}, 400)
                return

            step = str(data.get('step') or '').strip()
            mode = str(data.get('mode') or 'SINGLE').upper()
            target_dir = data.get('targetDir') or ''
            target_file = data.get('targetFile') or ''
            output_dir = data.get('outputDir') or 'output/exp_jsonld'
            supported_steps = {'dxf2svg', 'extract-elements', 'build-topology', 'enrich-graph', 'visualize-graph'}
            if step not in supported_steps:
                self._send_json({'ok': False, 'error': 'unknown_step', 'step': step, 'supportedSteps': sorted(supported_steps)}, 400)
                return

            messages = []
            results = []
            files = []

            def _find_svg_files():
                """Return all SVG files under data/raw/svg/<target_dir>/"""
                svg_dir = settings.raw_svg_data_path / target_dir
                if not svg_dir.exists():
                    return []
                return sorted(svg_dir.glob('*.svg'))

            def resolve_svg_path():
                if not target_file:
                    return None
                candidate = Path(str(target_file).replace('\\', '/'))
                if candidate.is_absolute():
                    return candidate
                if str(candidate).startswith('data/raw/svg/'):
                    return (ROOT / candidate).resolve()
                if candidate.parent != Path('.'):
                    return (settings.raw_svg_data_path / candidate).resolve()
                if target_dir:
                    return (settings.raw_svg_data_path / target_dir / candidate).resolve()
                return (settings.raw_svg_data_path / candidate).resolve()

            def build_step_paths(svg_path):
                base_name = svg_path.stem
                output_dir_path = Path(output_dir)
                if not output_dir_path.is_absolute():
                    output_dir_path = (ROOT / output_dir_path).resolve()
                return {
                    'raw_jsonld_path': output_dir_path / f"{base_name}_raw.jsonld",
                    'enriched_jsonld_path': output_dir_path / f"{base_name}.jsonld",
                    'exp_viz_path': settings.exp_viz_dir / f"{base_name}_exp.png",
                    'svg_ins_path': settings.svg_ins_dir / f"{base_name}.png"
                }

            def _run_single_step(step, svg_path, msg_list, res_list):
                step_paths = build_step_paths(svg_path)
                if step == 'extract-elements':
                    from src.io.extractor import ElementExtractor
                    from src.utils.svg_ins_viz import visualize_elements
                    from src.config.labels import get_color

                    extractor = ElementExtractor()
                    elements = extractor.process(str(svg_path))
                    step_paths['svg_ins_path'].parent.mkdir(parents=True, exist_ok=True)
                    visualize_elements(elements, get_color(), str(step_paths['svg_ins_path'].parent), step_paths['svg_ins_path'].name)
                    res_list.append(_repo_rel(step_paths['svg_ins_path']))
                elif step == 'build-topology':
                    from src.io.extractor import ElementExtractor
                    from src.topology.builder import TopologyBuilder

                    extractor = ElementExtractor()
                    elements = extractor.process(str(svg_path))
                    step_paths['raw_jsonld_path'].parent.mkdir(parents=True, exist_ok=True)
                    builder = TopologyBuilder()
                    builder.build(elements, str(step_paths['raw_jsonld_path']))
                    res_list.append(_repo_rel(step_paths['raw_jsonld_path']))
                elif step == 'enrich-graph':
                    from src.io.extractor import ElementExtractor
                    from src.enricher.enricher_pipeline import GraphEnrichmentPipeline

                    if not step_paths['raw_jsonld_path'].exists():
                        raise FileNotFoundError(f"Raw JSON-LD not found: {step_paths['raw_jsonld_path']}")
                    with open(step_paths['raw_jsonld_path'], 'r', encoding='utf-8') as f:
                        raw_graph_data = json.load(f)
                    extractor = ElementExtractor()
                    elements = extractor.process(str(svg_path))
                    room_texts = []
                    for elem in elements:
                        if elem.get('type') == 'text' or 'text' in elem:
                            coords = elem.get('coords', [0, 0])
                            room_texts.append({'text': elem.get('text', elem.get('label', '')), 'point': (coords[0], coords[1])})
                    pipeline = GraphEnrichmentPipeline(raw_graph_data, room_texts, llm_client=None)
                    enriched_graph_data = pipeline.run_all()
                    step_paths['enriched_jsonld_path'].parent.mkdir(parents=True, exist_ok=True)
                    with open(step_paths['enriched_jsonld_path'], 'w', encoding='utf-8') as f:
                        json.dump(enriched_graph_data, f, ensure_ascii=False, indent=2)
                    res_list.append(_repo_rel(step_paths['enriched_jsonld_path']))
                elif step == 'visualize-graph':
                    from src.utils.json_to_floorplan_viz import JSONLDVisualizer

                    if not step_paths['enriched_jsonld_path'].exists():
                        raise FileNotFoundError(f"Enriched JSON-LD not found: {step_paths['enriched_jsonld_path']}")
                    step_paths['exp_viz_path'].parent.mkdir(parents=True, exist_ok=True)
                    visualizer = JSONLDVisualizer(str(step_paths['enriched_jsonld_path']))
                    visualizer.parse_graph()
                    visualizer.draw(str(step_paths['exp_viz_path']))
                    res_list.append(_repo_rel(step_paths['exp_viz_path']))
                else:
                    raise ValueError(f"Unsupported step: {step}")

            try:
                if step == 'dxf2svg':
                    dxf_root = settings.dxf_data_path / target_dir
                    svg_root = settings.raw_svg_data_path / target_dir
                    svg_root.mkdir(parents=True, exist_ok=True)
                    if not dxf_root.exists():
                        raise FileNotFoundError(f"DXF source dir not found: {dxf_root}")
                    for p in sorted(dxf_root.glob('*.dxf')):
                        out_svg = svg_root / (p.stem + '.svg')
                        messages.append(f"Converting {p} -> {out_svg}")
                        try:
                            convert_dxf_to_svg(str(p), str(out_svg))
                            results.append(_repo_rel(out_svg))
                            messages.append(f"OK: {out_svg}")
                        except Exception as e:
                            messages.append(f"ERROR converting {p}: {e}")
                else:
                    if mode == 'BATCH':
                        svg_files = _find_svg_files()
                        if not svg_files:
                            raise FileNotFoundError(f"No SVG files found in data/raw/svg/{target_dir}")
                        for svg_path in svg_files:
                            messages.append(f"Processing: {svg_path.name}")
                            _run_single_step(step, svg_path, messages, results)
                    else:
                        svg_path = resolve_svg_path()
                        if not svg_path or not svg_path.exists():
                            raise FileNotFoundError(f"SVG file not found: {target_file}")
                        _run_single_step(step, svg_path, messages, results)
                files = results
                response = {'ok': True, 'messages': messages, 'files': files, 'results': results}
                if results:
                    response['preview'] = results[-1]
                self._send_json(response)
            except Exception as e:
                self._send_json({'ok': False, 'error': str(e), 'messages': messages, 'results': results}, 500)
            return

    def _available_inputs(self):
        svg_root = ROOT / 'data' / 'raw' / 'svg'
        svg_files = []
        if svg_root.exists():
            for path in sorted(svg_root.rglob('*.svg')):
                if path.is_file():
                    svg_files.append(_repo_rel(path))

        result_dirs = []
        output_root = ROOT / 'output' / 'exp_jsonld'
        if output_root.exists():
            for path in sorted(output_root.rglob('*')):
                if path.is_dir():
                    result_dirs.append(_repo_rel(path))

        return {
            'svgFiles': svg_files,
            'resultDirs': result_dirs,
            'defaultOutputDir': 'output/exp_jsonld'
        }

    def _list_files(self, path_value):
        path = _safe_path(path_value)
        if not path or not path.exists():
            return []
        if not path.is_dir():
            return [path.name]
        return [p.name for p in sorted(path.iterdir()) if p.exists()]

    def _serve_preview(self, path_value):
        path = _safe_path(path_value)
        if not path or not path.exists() or not path.is_file():
            self.send_error(404)
            return
        body = path.read_bytes()
        suffix = path.suffix.lower()
        mime = 'image/svg+xml' if suffix == '.svg' else 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _evaluation_data(self):
        overall_files = list((ROOT / 'output' / 'html').rglob('overall_results.json'))
        rows = []
        metrics = []
        for overall_file in overall_files:
            try:
                with open(overall_file, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
            except Exception:
                continue
            row = {'source': _repo_rel(overall_file)}
            flat_metrics = {}
            for group, values in data.items():
                if isinstance(values, dict):
                    for key, value in values.items():
                        flat_metrics[key] = value
                        metrics.append((key, value))
                else:
                    flat_metrics[group] = values
            row.update(flat_metrics)
            rows.append(row)

        if not rows:
            rows = [{
                'source': 'output/html/overall_results.json',
                'Global_1to1_Match_Rate': 0,
                'Global_mIoU': 0,
                'Global_Precision': 0,
                'Global_Recall': 0,
                'Global_F1': 0,
                'Global_MAE_Area': 0,
                'Global_MAE_Width': 0,
                'Global_Accuracy': 0,
                'Global_Macro_F1': 0,
            }]

        individual_files = list((ROOT / 'output' / 'html').rglob('individual_results.csv'))
        individual_rows = []
        if individual_files:
            with open(individual_files[0], 'r', encoding='utf-8') as fh:
                reader = csv.DictReader(fh)
                individual_rows = list(reader)

        return {
            'overall': rows[0],
            'individual': individual_rows,
            'chart': [
                {'label': 'Geometry 1to1', 'value': rows[0].get('Global_1to1_Match_Rate', 0)},
                {'label': 'Geometry mIoU', 'value': rows[0].get('Global_mIoU', 0)},
                {'label': 'Topology F1', 'value': rows[0].get('Global_F1', 0)},
                {'label': 'Area MAE', 'value': rows[0].get('Global_MAE_Area', 0)},
                {'label': 'Semantic Accuracy', 'value': rows[0].get('Global_Accuracy', 0)},
            ]
        }


def run_server(host='0.0.0.0', port=8000):
    server = ThreadingHTTPServer((host, port), UIHandler)
    print(f'UI server running at http://{host}:{port}')
    server.serve_forever()


if __name__ == '__main__':
    run_server()