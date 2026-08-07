"""UI server for the CAD rule checker pipeline."""
import os
os.environ.setdefault('MPLBACKEND', 'Agg')  # force non-interactive backend BEFORE any matplotlib import

import csv
import json
import re
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
        if parsed.path == '/api/available-dxfs':
            self._send_json(self._available_dxfs())
            return
        if parsed.path == '/api/kg-files':
            self._send_json(self._kg_files())
            return
        if parsed.path == '/api/kg-browser':
            self._serve_kg_browser(parse_qs(parsed.query))
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
            output_dir = data.get('outputDir') or 'output/jsonld'

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
                proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
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

            sys_out_dir = data.get('sysOutDir') or 'output/jsonld'
            gt_dir = data.get('gtDir') or 'output/gt'
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

        # ==========================================
        # 类别一：正常使用 —— 输入单个 DXF，端到端分析并可视化
        # ==========================================
        if parsed.path == '/api/run-analysis':
            data = self._read_json_body()
            if data is None:
                self._send_json({'ok': False, 'error': 'invalid_json'}, 400)
                return

            dxf_path = self._resolve_dxf_path(data.get('dxfFile') or '')
            output_dir = data.get('outputDir') or 'output/jsonld'
            if not dxf_path:
                self._send_json({'ok': False, 'error': f'DXF file not found: {data.get("dxfFile")}'}, 404)
                return

            base_name = dxf_path.stem
            svg_path = Path(settings.svg_dir) / f"{base_name}.svg"
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            if not svg_path.exists():
                try:
                    convert_dxf_to_svg(str(dxf_path), str(svg_path))
                except Exception as e:
                    self._send_json({'ok': False, 'error': f'dxf2svg failed: {e}'}, 500)
                    return

            run = self._run_parsing_single(base_name + '.svg', output_dir)
            output_dir_path = Path(output_dir)
            if not output_dir_path.is_absolute():
                output_dir_path = (ROOT / output_dir_path).resolve()
            viz_dir = Path(settings.viz_dir)

            payload = {
                'ok': run['returnCode'] == 0,
                'returnCode': run['returnCode'],
                'stdout': run['stdout'],
                'stderr': run['stderr'],
                'base': base_name,
                'svg': self._rel_or_none(svg_path),
                'jsonld': self._rel_or_none(output_dir_path / f'{base_name}.jsonld'),
                'rawJsonld': self._rel_or_none(output_dir_path / f'{base_name}_raw.jsonld'),
                'topologyPng': self._rel_or_none(viz_dir / f'{base_name}_topology.png'),
                'instancePng': self._rel_or_none(viz_dir / f'{base_name}_instance.png'),
                'cdtPng': self._rel_or_none(viz_dir / f'{base_name}_cdt.png'),
            }
            self._send_json(payload)
            return

        # ==========================================
        # 类别二 2.1：图纸分析 —— 单个 DXF，左右同屏对比系统结果与 GT 结果
        # ==========================================
        if parsed.path == '/api/experiment-draw':
            data = self._read_json_body()
            if data is None:
                self._send_json({'ok': False, 'error': 'invalid_json'}, 400)
                return

            dxf_path = self._resolve_dxf_path(data.get('dxfFile') or '')
            output_dir = data.get('outputDir') or 'output/jsonld'
            if not dxf_path:
                self._send_json({'ok': False, 'error': f'DXF file not found: {data.get("dxfFile")}'}, 404)
                return

            base_name = dxf_path.stem
            svg_path = Path(settings.svg_dir) / f"{base_name}.svg"
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            if not svg_path.exists():
                try:
                    convert_dxf_to_svg(str(dxf_path), str(svg_path))
                except Exception as e:
                    self._send_json({'ok': False, 'error': f'dxf2svg failed: {e}'}, 500)
                    return

            output_dir_path = Path(output_dir)
            if not output_dir_path.is_absolute():
                output_dir_path = (ROOT / output_dir_path).resolve()
            jsonld_path = output_dir_path / f'{base_name}.jsonld'

            # 复用已有富化结果（对比视图）；仅当不存在时才重新解析
            run = {'returnCode': 0, 'stdout': '', 'stderr': ''}
            if not jsonld_path.exists():
                run = self._run_parsing_single(base_name + '.svg', output_dir)

            viz_dir = Path(settings.viz_dir)

            gt_path = self._find_gt_for_base(base_name)
            gt_stem = gt_path.stem if gt_path else None

            payload = {
                'ok': run['returnCode'] == 0,
                'returnCode': run['returnCode'],
                'stdout': run['stdout'],
                'stderr': run['stderr'],
                'base': base_name,
                'hasGt': gt_path is not None,
                'sysTopology': self._rel_or_none(viz_dir / f'{base_name}_topology.png'),
                'sysInstance': self._rel_or_none(viz_dir / f'{base_name}_instance.png'),
                'sysCdt': self._rel_or_none(viz_dir / f'{base_name}_cdt.png'),
                'sysJsonld': self._rel_or_none(output_dir_path / f'{base_name}.jsonld'),
                'gtJsonld': self._rel_or_none(gt_path) if gt_path else None,
                'gtTopology': self._rel_or_none(viz_dir / f'{gt_stem}_topology.png') if gt_stem else None,
                'gtInstance': self._rel_or_none(viz_dir / f'{gt_stem}_gt_topology.png') if gt_stem else None,
            }
            self._send_json(payload)
            return

        # ==========================================
        # 类别二 2.2：SHACL 审查 —— 输入 DXF，自动定位/处理对应文件后再审查
        # ==========================================
        if parsed.path == '/api/experiment-shacl':
            data = self._read_json_body()
            if data is None:
                self._send_json({'ok': False, 'error': 'invalid_json'}, 400)
                return

            dxf_path = self._resolve_dxf_path(data.get('dxfFile') or '')
            output_dir = data.get('outputDir') or 'output/jsonld'
            if not dxf_path:
                self._send_json({'ok': False, 'error': f'DXF file not found: {data.get("dxfFile")}'}, 404)
                return

            base_name = dxf_path.stem
            svg_path = Path(settings.svg_dir) / f"{base_name}.svg"
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            if not svg_path.exists():
                try:
                    convert_dxf_to_svg(str(dxf_path), str(svg_path))
                except Exception as e:
                    self._send_json({'ok': False, 'error': f'dxf2svg failed: {e}'}, 500)
                    return

            output_dir_path = Path(output_dir)
            if not output_dir_path.is_absolute():
                output_dir_path = (ROOT / output_dir_path).resolve()
            jsonld_path = output_dir_path / f'{base_name}.jsonld'

            # 自动定位已处理文件；若为新文件则先解析再审查
            run = {'returnCode': 0, 'stdout': '', 'stderr': ''}
            if not jsonld_path.exists():
                run = self._run_parsing_single(base_name + '.svg', output_dir)
                if run['returnCode'] != 0:
                    self._send_json({'ok': False, 'error': 'parsing failed', 'stdout': run['stdout'], 'stderr': run['stderr']}, 500)
                    return

            try:
                from src.experiment.compliance_reviewer import review_single
                status, violations = review_single(str(jsonld_path), save_html=True)
            except Exception as e:
                self._send_json({'ok': False, 'error': f'compliance review failed: {e}'}, 500)
                return

            violations_json = Path(settings.violations_dir) / f'{base_name}_violations.json'
            html_path = Path(settings.html_dir) / f'{base_name}_compliance_report.html'
            payload = {
                'ok': True,
                'base': base_name,
                'status': status,
                'violationCount': len(violations),
                'violationsJson': self._rel_or_none(violations_json),
                'reportHtml': self._rel_or_none(html_path),
                'stdout': run['stdout'],
                'stderr': run['stderr'],
            }
            self._send_json(payload)
            return

        # Upload DXF files via multipart/form-data
        if parsed.path == '/api/upload-dxf':
            # parse multipart
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD': 'POST'})
            target_dir = str(form.getvalue('targetDir') or 'uploads')
            save_dir = settings.dxf_dir / target_dir
            save_dir.mkdir(parents=True, exist_ok=True)
            saved = []
            for field in form.list or []:
                if field.filename:
                    filename = Path(field.filename).name
                    out_path = save_dir / filename
                    with open(out_path, 'wb') as out_f:
                        if field.file:
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
            output_dir = data.get('outputDir') or 'output/jsonld'
            supported_steps = {'dxf2svg', 'extract-elements', 'build-topology', 'enrich-graph', 'visualize-graph'}
            if step not in supported_steps:
                self._send_json({'ok': False, 'error': 'unknown_step', 'step': step, 'supportedSteps': sorted(supported_steps)}, 400)
                return

            messages = []
            results = []
            files = []

            def _find_svg_files():
                """Return all SVG files under input_data/svg/<target_dir>/"""
                svg_dir = settings.svg_dir / target_dir
                if not svg_dir.exists():
                    return []
                return sorted(svg_dir.glob('*.svg'))

            def resolve_svg_path():
                if not target_file:
                    return None
                candidate = Path(str(target_file).replace('\\', '/'))
                if candidate.is_absolute():
                    return candidate
                if str(candidate).startswith('input_data/svg/'):
                    return (ROOT / candidate).resolve()
                if candidate.parent != Path('.'):
                    return (settings.svg_dir / candidate).resolve()
                if target_dir:
                    return (settings.svg_dir / target_dir / candidate).resolve()
                return (settings.svg_dir / candidate).resolve()

            def build_step_paths(svg_path):
                base_name = svg_path.stem
                output_dir_path = Path(output_dir)
                if not output_dir_path.is_absolute():
                    output_dir_path = (ROOT / output_dir_path).resolve()
                return {
                    'raw_jsonld_path': output_dir_path / f"{base_name}_raw.jsonld",
                    'enriched_jsonld_path': output_dir_path / f"{base_name}.jsonld",
                    'exp_viz_path': settings.viz_dir / f"{base_name}_topology.png",
                    'svg_ins_path': settings.viz_dir / f"{base_name}_instance.png"
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
                    dxf_root = settings.dxf_dir / target_dir
                    svg_root = settings.svg_dir / target_dir
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
                            raise FileNotFoundError(f"No SVG files found in input_data/svg/{target_dir}")
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
        svg_root = ROOT / 'input_data' / 'svg'
        svg_files = []
        if svg_root.exists():
            for path in sorted(svg_root.rglob('*.svg')):
                if path.is_file():
                    svg_files.append(_repo_rel(path))

        result_dirs = []
        output_root = ROOT / 'output' / 'jsonld'
        if output_root.exists():
            for path in sorted(output_root.rglob('*')):
                if path.is_dir():
                    result_dirs.append(_repo_rel(path))

        return {
            'svgFiles': svg_files,
            'resultDirs': result_dirs,
            'defaultOutputDir': 'output/jsonld'
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
        mime = {
            '.svg': 'image/svg+xml',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.json': 'application/json; charset=utf-8',
            '.jsonld': 'application/json; charset=utf-8',
            '.html': 'text/html; charset=utf-8',
            '.ttl': 'text/turtle; charset=utf-8',
        }.get(suffix, 'application/octet-stream')
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        """Read and parse a JSON POST body. Returns None on parse failure."""
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length).decode('utf-8') if length else '{}'
        try:
            return json.loads(body or '{}')
        except json.JSONDecodeError:
            return None

    def _rel_or_none(self, path):
        """Return the repo-relative path, or None if the file does not exist."""
        p = Path(path)
        return _repo_rel(p) if p.exists() else None

    def _available_dxfs(self):
        """List DXF files available under input_data/dxf."""
        dxf_root = Path(settings.dxf_dir)
        files = []
        if dxf_root.is_dir():
            files = sorted(p.name for p in dxf_root.glob('*.dxf'))
        return {'dxfFiles': files}

    def _resolve_dxf_path(self, raw):
        """Resolve a DXF reference to an absolute path (default under input_data/dxf)."""
        if not raw:
            return None
        p = Path(str(raw).replace('\\', '/'))
        if p.is_absolute():
            return p if p.exists() else None
        candidate = Path(settings.dxf_dir) / p
        if candidate.exists():
            return candidate
        candidate2 = ROOT / p
        return candidate2 if candidate2.exists() else None

    def _find_gt_for_base(self, base_name):
        """Locate the Ground Truth JSON-LD for a system base name.

        Tries direct names first, then scans output/gt for a file whose stem
        (after removing ``_gt`` / ``_annotated`` markers) matches the base name.
        """
        gt_dir = Path(settings.gt_dir)
        for name in (f"{base_name}_gt.jsonld", f"{base_name}_annotated_gt.jsonld", f"{base_name}_Annotated_gt.jsonld"):
            p = gt_dir / name
            if p.exists():
                return p
        for p in sorted(gt_dir.glob('*_gt.jsonld')):
            stem = p.stem
            if stem.endswith('_gt'):
                stem = stem[:-3]
            stem = re.sub(r'_annotated', '', stem, flags=re.IGNORECASE)
            if stem == base_name:
                return p
        return None

    def _kg_files(self):
        """List JSON-LD datasets available for the KG browser (system + GT)."""
        files = []
        jsonld_dir = Path(settings.jsonld_dir)
        for p in sorted(jsonld_dir.glob('*.jsonld')):
            if '_raw' in p.stem:
                continue
            base = p.stem
            raw = jsonld_dir / f'{base}_raw.jsonld'
            gt = self._find_gt_for_base(base)
            files.append({
                'base': base,
                'systemJsonld': _repo_rel(p),
                'rawJsonld': _repo_rel(raw) if raw.exists() else None,
                'hasRawSvg': raw.exists() and (Path(settings.svg_dir) / f'{base}.svg').exists(),
                'gtJsonld': _repo_rel(gt) if gt else None,
                'hasGt': gt is not None,
            })
        return {'files': files}

    def _serve_kg_browser(self, q):
        """Generate (if needed) and return the KG browser HTML for a dataset.

        Query params:
            base    -- drawing base name, e.g. "2suite (1)"
            src     -- 'system' (default) or 'gt'
            stages  -- '1' to include the 富化过程 stage replay (system, needs raw+svg)
            refresh -- '1' to force regeneration instead of reusing the cache
        """
        base = (q.get('base') or [''])[0]
        src = (q.get('src') or ['system'])[0]
        want_stages = (q.get('stages') or ['0'])[0] == '1'
        refresh = (q.get('refresh') or ['0'])[0] == '1'
        if not base:
            self._send_json({'ok': False, 'error': 'missing base'}, 400)
            return

        viz_dir = Path(settings.viz_dir)
        if src == 'gt':
            final_path = self._find_gt_for_base(base)
            suffix = '_gt'
            want_stages = False
        else:
            final_path = Path(settings.jsonld_dir) / f'{base}.jsonld'
            suffix = '_stages' if want_stages else ''

        if not final_path or not final_path.exists():
            self._send_json({'ok': False, 'error': f'{src} jsonld not found for "{base}"'}, 404)
            return

        out_html = viz_dir / f'{base}{suffix}_kg_browser.html'
        if refresh and out_html.exists():
            out_html.unlink()

        replay = False
        raw = svg = None
        if src == 'system' and want_stages:
            raw = Path(settings.jsonld_dir) / f'{base}_raw.jsonld'
            svg = Path(settings.svg_dir) / f'{base}.svg'
            if raw.exists() and svg.exists():
                replay = True
            # 缺少 raw/svg 时回退到最终图谱（final-only）

        if not out_html.exists():
            try:
                from src.utils import kg_browser
                if replay:
                    kg_browser.process_one(base, raw, str(svg), str(viz_dir), use_llm=True,
                                           suffix=suffix)
                else:
                    kg_browser.process_one(base, None, None, str(viz_dir), use_llm=False,
                                           final_path=str(final_path), suffix=suffix, replay=False)
            except Exception as e:
                self._send_json({'ok': False, 'error': f'kg-browser generation failed: {e}'}, 500)
                return

        self._send_json({'ok': True, 'base': base, 'src': src, 'stages': replay,
                         'suffix': suffix, 'html': _repo_rel(out_html),
                         'jsonld': _repo_rel(final_path)})

    def _run_parsing_single(self, svg_name, output_dir):
        """Run the parsing pipeline (main.py SINGLE mode) as a subprocess."""
        cmd = [sys.executable, '-m', 'src.main', '--mode', 'SINGLE', '--target-file', svg_name, '--output-dir', output_dir]
        env = os.environ.copy()
        env['PYTHONUTF8'] = '1'
        try:
            proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=1800)
            return {'returnCode': proc.returncode, 'stdout': proc.stdout or '', 'stderr': proc.stderr or ''}
        except subprocess.TimeoutExpired as exc:
            return {'returnCode': -1, 'stdout': exc.stdout or '', 'stderr': f"{exc.stderr or ''}\n[timeout]"}

    def _evaluation_data(self):
        """Serve the batch evaluation results.

        SHACL compliance results (Exp 5) are kept separate from the core
        geometry / topology / geometric computation / semantic results:
        the former come from ``compliance_results.json`` and
        ``compliance_individual_results.csv``, the latter from
        ``overall_results.json`` and ``individual_results.csv``.
        """
        def _flatten(path_pattern):
            """Read the first matching JSON file and flatten nested groups."""
            files = list((ROOT / 'output' / 'html').rglob(path_pattern))
            for f in files:
                try:
                    with open(f, 'r', encoding='utf-8') as fh:
                        data = json.load(fh)
                except Exception:
                    continue
                flat = {'source': _repo_rel(f)}
                for group, values in data.items():
                    if isinstance(values, dict):
                        for key, value in values.items():
                            flat[key] = value
                    else:
                        flat[group] = values
                return data, flat
            return None, None

        # Core experiments (geometry / topology / geometric computation / semantic)
        raw_overall, core_row = _flatten('overall_results.json')
        if core_row is None:
            core_row = {
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
            }

        # SHACL compliance summary (Exp 5) — separate file / column
        raw_compliance, comp_row = _flatten('compliance_results.json')
        if comp_row is None:
            comp_row = {
                'source': 'output/html/compliance_results.json',
                'Global_Precision': 0,
                'Global_Recall': 0,
                'Global_F1': 0,
            }

        individual_files = list((ROOT / 'output' / 'html').rglob('individual_results.csv'))
        individual_rows = []
        if individual_files:
            with open(individual_files[0], 'r', encoding='utf-8-sig') as fh:
                reader = csv.DictReader(fh)
                individual_rows = list(reader)

        compliance_individual_files = list((ROOT / 'output' / 'html').rglob('compliance_individual_results.csv'))
        compliance_individual_rows = []
        if compliance_individual_files:
            with open(compliance_individual_files[0], 'r', encoding='utf-8-sig') as fh:
                reader = csv.DictReader(fh)
                compliance_individual_rows = list(reader)

        return {
            'overall': core_row,
            'raw': raw_overall,
            'individual': individual_rows,
            'compliance': comp_row,
            'complianceRaw': raw_compliance,
            'complianceIndividual': compliance_individual_rows,
            'chart': [
                {'label': 'Geometry 1to1', 'value': core_row.get('Global_1to1_Match_Rate', 0)},
                {'label': 'Geometry mIoU', 'value': core_row.get('Global_mIoU', 0)},
                {'label': 'Topology F1', 'value': core_row.get('Global_F1', 0)},
                {'label': 'Area MAE', 'value': core_row.get('Global_MAE_Area', 0)},
                {'label': 'Semantic Accuracy', 'value': core_row.get('Global_Accuracy', 0)},
            ]
        }


def run_server(host='0.0.0.0', port=8001):
    server = ThreadingHTTPServer((host, port), UIHandler)
    print(f'UI server running at http://{host}:{port}')
    server.serve_forever()


if __name__ == '__main__':
    run_server()