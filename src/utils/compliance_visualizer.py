import json
import re
import os
from urllib.parse import quote

from src.config.config import settings


class ComplianceVisualizer:
    def __init__(self, original_svg_path, jsonld_path):
        """
        初始化单栏高清原生 SVG 交互式合规标注引擎
        直接操作 DOM 树注入动态遮罩，告别 Matplotlib 像素渲染，实现无限缩放高清展示
        """
        self.svg_path = original_svg_path
        self.jsonld_path = jsonld_path

        with open(jsonld_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        self.nodes = {node.get("@id"): node for node in self.data.get("@graph", [])}

    def _get_geometry(self, node_id):
        """获取单个物理节点的绝对坐标点集"""
        node = self.nodes.get(node_id, {})
        geo_wkt = node.get("geo:asWKT")
        if geo_wkt:
            wkt_str = geo_wkt.get("@value", "") if isinstance(geo_wkt, dict) else geo_wkt
            if wkt_str.startswith("POLYGON"):
                match = re.search(r'\(\((.*?)\)\)', wkt_str)
                if not match: return None
                points = []
                for pt_str in match.group(1).split(','):
                    x, y = map(float, pt_str.strip().split())
                    points.append((x, y))
                return points
        return None

    def _get_node_polygons(self, node_id):
        """
        获取节点的多边形列表。
        支持实体节点自身的坐标，以及虚拟节点（如流线/套间）通过
        bot:hasSpace / bot:adjacentZone 关联的节点坐标聚合。
        """
        pts = self._get_geometry(node_id)
        if pts:
            return [pts]  # 如果自身有物理坐标，直接返回

        # 如果自身没有坐标：收集其包含空间 (bot:hasSpace，如套间) 及相邻节点 (bot:adjacentZone) 的坐标
        node = self.nodes.get(node_id, {})
        polys = []
        ref_ids = []

        for key in ("bot:hasSpace", "bot:adjacentZone"):
            refs = node.get(key, [])
            if not isinstance(refs, list):
                refs = [refs]
            for ref in refs:
                rid = ref.get("@id") if isinstance(ref, dict) else ref
                if rid:
                    ref_ids.append(rid)

        for rid in ref_ids:
            adj_pts = self._get_geometry(rid)
            if adj_pts:
                polys.append(adj_pts)

        return polys

    # ------------------------------------------------------------------
    # Coordinate mapping helpers (physical WKT 坐标 -> 各 PNG 像素坐标)
    # ------------------------------------------------------------------
    def _collect_all_wkt(self):
        """收集图谱中所有节点的物理 WKT 坐标点。"""
        all_pts = []
        for nid, node in self.nodes.items():
            geo_wkt = node.get("geo:asWKT")
            if not geo_wkt:
                continue
            wkt_str = geo_wkt.get("@value", "") if isinstance(geo_wkt, dict) else geo_wkt
            if not isinstance(wkt_str, str) or not wkt_str.startswith("POLYGON"):
                continue
            match = re.search(r'\(\((.*?)\)\)', wkt_str)
            if not match:
                continue
            for pt_str in match.group(1).split(','):
                try:
                    x, y = map(float, pt_str.strip().split())
                    all_pts.append((x, y))
                except ValueError:
                    continue
        return all_pts

    def _physical_bounds(self):
        """全部 WKT 几何的物理包围盒（含 matplotlib 默认 5% 边距）。"""
        pts = self._collect_all_wkt()
        if not pts:
            return (0.0, 0.0, 1.0, 1.0)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        lo_x, hi_x = min(xs), max(xs)
        lo_y, hi_y = min(ys), max(ys)
        dx, dy = hi_x - lo_x, hi_y - lo_y
        return (lo_x - 0.05 * dx, lo_y - 0.05 * dy, hi_x + 0.05 * dx, hi_y + 0.05 * dy)

    def _svg_physical_bounds(self):
        """原始 SVG 全部路径几何的物理包围盒（+5% 边距），用于实例 PNG 的数据范围。

        svg_parser._transform_points 使用 real_x = x/scale, real_y = (140-y)/scale，
        因此这里将 viewBox 坐标反算回物理坐标。
        """
        if not self.svg_path or not os.path.exists(self.svg_path):
            return self._physical_bounds()
        try:
            with open(self.svg_path, 'r', encoding='utf-8') as f:
                svg_text = f.read()
        except OSError:
            return self._physical_bounds()
        m = re.search(r'scale="([\d\.]+)"', svg_text)
        scale = float(m.group(1)) if m else 1.0
        minx = miny = 1e18
        maxx = maxy = -1e18
        for dm in re.finditer(r'd="([^"]*)"', svg_text):
            nums = re.findall(r'[-+]?[\d.]+', dm.group(1))
            for a, b in zip(nums[::2], nums[1::2]):
                try:
                    x, y = float(a), float(b)
                except ValueError:
                    continue
                minx = min(minx, x)
                miny = min(miny, y)
                maxx = max(maxx, x)
                maxy = max(maxy, y)
        if minx == 1e18:
            return self._physical_bounds()
        # viewBox -> 物理坐标
        px0 = minx / scale
        px1 = maxx / scale
        py0 = (140 - maxy) / scale
        py1 = (140 - miny) / scale
        dx, dy = px1 - px0, py1 - py0
        return (px0 - 0.05 * dx, py0 - 0.05 * dy, px1 + 0.05 * dx, py1 + 0.05 * dy)

    @staticmethod
    def _png_content_bbox(path):
        """PNG 中非白色像素（绘图内容）的包围盒，用于校准数据→像素映射。"""
        if not path or not os.path.exists(path):
            return None
        try:
            from PIL import Image
            import numpy as np
        except ImportError:
            return None
        try:
            img = np.asarray(Image.open(path).convert('RGB'))
            nw = (img[:, :, 0] < 245) | (img[:, :, 1] < 245) | (img[:, :, 2] < 245)
            ys, xs = np.where(nw)
            if len(xs) == 0:
                return None
            return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
        except Exception:
            return None

    @staticmethod
    def _make_affine(x0, y0, x1, y1, cbox):
        """由数据包围盒 (x0,y0,x1,y1) 与像素内容包围盒 (cbox) 推导物理→像素仿射系数。"""
        if not cbox:
            return None
        cx0, cy0, cx1, cy1 = cbox
        dx, dy = x1 - x0, y1 - y0
        if dx <= 0 or dy <= 0:
            return None
        ax = (cx1 - cx0) / dx
        bx = cx0 - ax * x0
        A = (cy1 - cy0) / dy
        ay = -A
        by = cy0 + y1 * A
        return {"ax": ax, "bx": bx, "ay": ay, "by": by}

    def draw_annotated_report(self, violations, output_path="compliance_report.html"):
        """
        生成单栏全屏、基于纯原生 SVG 交互的 HTML 报告
        """
        print(f"🎨 Generating full-height native-SVG interactive web review report...")

        # --- 1. 底图 A：原图 SVG ---
        base_name = os.path.splitext(os.path.basename(self.svg_path))[0] if self.svg_path else ""
        orig_svg_content = "<p style='color:red; text-align:center;'>⚠️ Original SVG not found, cannot render the base image.</p>"
        scale_factor = 1.0
        vb_w = 140.0
        vb_h = 140.0  # default viewport size

        def _clean_svg(svg_text, svg_id):
            """Rewrite the root <svg> tag cleanly: keep only xmlns/viewBox, drop
            existing style/id/class/width/height to avoid duplicate attributes
            that can break rendering, then inject id + 100% size + transform origin."""
            svg_text = re.sub(r'<\?xml.*?\?>', '', svg_text, flags=re.IGNORECASE).strip()
            svg_text = re.sub(r'<!DOCTYPE.*?>', '', svg_text, flags=re.IGNORECASE).strip()

            def _rewrite_root(m):
                tag = m.group(0)
                keep = []
                for attr in ('xmlns', 'viewBox'):
                    am = re.search(rf'\b{attr}=("[^"]*"|\'[^\']*\')', tag, flags=re.IGNORECASE)
                    if am:
                        keep.append(f'{attr}={am.group(1)}')
                return (f'<svg id="{svg_id}" width="100%" height="100%" '
                        f'preserveAspectRatio="xMidYMid meet" style="display: block; transform-origin: 0 0;" '
                        + ' '.join(keep) + '>')

            svg_text = re.sub(r'<svg[^>]*>', _rewrite_root, svg_text, count=1, flags=re.IGNORECASE)
            return svg_text

        if os.path.exists(self.svg_path):
            with open(self.svg_path, 'r', encoding='utf-8') as f:
                raw_svg = f.read()
            # 提取图纸真实的缩放系数和视口宽高，以便做坐标逆向映射
            scale_match = re.search(r'scale="([\d\.]+)"', raw_svg)
            if scale_match:
                scale_factor = float(scale_match.group(1))
            vb_match = re.search(r'viewBox="[\d\.]+\s+[\d\.]+\s+([\d\.]+)\s+([\d\.]+)"', raw_svg)
            if vb_match:
                vb_w = float(vb_match.group(1))
                vb_h = float(vb_match.group(2))
            # 注入高亮遮罩层，并清洗/规范化 SVG
            orig_svg_content = _clean_svg(raw_svg, "cad-svg")
            orig_svg_content = re.sub(r'</svg>', '<g id="highlight-overlay"></g></svg>', orig_svg_content, flags=re.IGNORECASE)

        # --- 1b. 底图 B：空间识别可视化 (instance PNG) ---
        instance_png_path = os.path.join(str(settings.viz_dir), f"{base_name}_instance.png")
        instance_available = os.path.exists(instance_png_path)
        # 报告经 /api/preview?path=... 服务，相对路径会解析到错误位置，必须使用绝对 API 路径
        instance_src = f"/api/preview?path=output/viz/{quote(base_name)}_instance.png" if instance_available else ""

        # --- 1c. 底图 C：拓扑图 (topology PNG，彩色房间语义预览) ---
        topo_png_path = os.path.join(str(settings.viz_dir), f"{base_name}_topology.png")
        topo_available = os.path.exists(topo_png_path)
        # 报告经 /api/preview?path=... 服务，相对路径会解析到 /viz/... 导致 404，
        # 因此必须使用可被 _serve_preview 处理的绝对 API 路径。
        topo_src = f"/api/preview?path=output/viz/{quote(base_name)}_topology.png" if topo_available else ""

        # --- 1d. 计算各光栅底图的物理坐标 -> 像素 仿射变换（用于 Space/Topology 模式的定位/高亮） ---
        # topology PNG: json_to_floorplan_viz 直接绘制 WKT 物理坐标
        topo_bounds = self._physical_bounds()
        topo_affine = self._make_affine(*topo_bounds, self._png_content_bbox(topo_png_path))
        # instance PNG: svg_ins_viz 绘制 SVG 全图元素（viewBox -> 物理），故用 SVG 路径物理范围
        inst_bounds = self._svg_physical_bounds()
        inst_affine = self._make_affine(*inst_bounds, self._png_content_bbox(instance_png_path))
        bg_transforms_json = json.dumps({"spaces": inst_affine, "topo": topo_affine}, ensure_ascii=False)

        # --- 2. 准备传入前端 JS 的结构化违规数据 ---
        violation_data_for_js = {}
        violation_items_html = ""

        for idx, v in enumerate(violations):
            node_id = v['node_id']
            msg = v['message']
            safe_id = re.sub(r'[^a-zA-Z0-9]', '_', node_id)

            polys = self._get_node_polygons(node_id)
            svg_polys = []
            phys_polys = []

            # 核心数学转换：将知识图谱中的绝对物理坐标 (WKT) 重新映射回 SVG viewBox 坐标系
            if polys:
                for pts in polys:
                    svg_pts = []
                    phys_pts = []
                    for x, y in pts:
                        phys_pts.append([x, y])
                        sx = x * scale_factor
                        sy = vb_h - (y * scale_factor)
                        svg_pts.append([sx, sy])
                    svg_polys.append(svg_pts)
                    phys_polys.append(phys_pts)

            violation_data_for_js[safe_id] = {
                "polygons": svg_polys,
                "phys_polygons": phys_polys,
                "message": msg,
                "node_id": node_id
            }

            # 拼接前端侧边栏代码
            violation_items_html += f"""
            <div class="violation-item" id="item-{safe_id}" onclick="highlightViolation('{safe_id}')">
                <div class="node-id">📍 {node_id}</div>
                <div class="msg">{msg}</div>
            </div>
            """

        images_json = json.dumps(violation_data_for_js, ensure_ascii=False)

        # --- 3. 组装终极单栏 HTML 报告 ---
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>BIM Automated Compliance Review Report</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; display: flex; height: 100vh; margin: 0; background-color: #f3f4f6; overflow: hidden; }}

        /* 收窄侧边栏，为图纸留出更大空间 */
        #sidebar {{ width: 320px; background: white; border-right: 1px solid #e5e7eb; display: flex; flex-direction: column; box-shadow: 2px 0 8px rgba(0,0,0,0.05); z-index: 10; flex-shrink: 0; }}
        .header {{ padding: 15px 20px; border-bottom: 1px solid #e5e7eb; background: #ffffff; }}
        .header h2 {{ margin: 0; color: #111827; font-size: 1.15rem; display: flex; align-items: center; gap: 8px; }}
        .header p {{ margin: 5px 0 0 0; color: #6b7280; font-size: 0.8rem; }}
        #violation-list {{ flex: 1; overflow-y: auto; padding: 12px; background: #fafafa; }}

        .violation-item {{ padding: 12px; margin-bottom: 10px; background: #ffffff; border: 1px solid #fee2e2; border-left: 4px solid #fca5a5; border-radius: 6px; cursor: pointer; transition: all 0.2s ease; box-shadow: 0 1px 3px rgba(220,38,38,0.05); }}
        .violation-item:hover {{ border-left-color: #ef4444; background: #fef2f2; transform: translateY(-1px); box-shadow: 0 4px 6px rgba(220,38,38,0.1); }}
        .violation-item.active {{ background: #fef2f2; border-left: 6px solid #dc2626; border-color: #fca5a5; }}
        .node-id {{ font-size: 0.75em; color: #4b5563; margin-bottom: 6px; font-family: 'Courier New', Courier, monospace; font-weight: 600; background: #f3f4f6; padding: 3px 6px; border-radius: 4px; display: inline-block; }}
        .msg {{ color: #1f2937; font-size: 0.9rem; line-height: 1.4; font-weight: 500; }}

        #main-content {{ flex: 1; display: flex; flex-direction: column; position: relative; overflow: hidden; background-color: #ffffff; }}

        /* 动态信息通知横幅 */
        #detail-header {{ height: 50px; background: #f9fafb; border-bottom: 1px solid #e5e7eb; display: flex; align-items: center; padding: 0 20px; font-size: 0.95rem; color: #4b5563; cursor: pointer; transition: all 0.3s ease; z-index: 5; flex-shrink: 0; user-select: none; }}
        #detail-header:hover {{ opacity: 0.9; }}

        /* SVG 画布容器最大化，移除所有不必要的内边距 */
        #bg-switch {{ display: flex; align-items: center; gap: 6px; padding: 0 20px; height: 44px; background: #f3f4f6; border-bottom: 1px solid #e5e7eb; flex-shrink: 0; }}
        #bg-switch span {{ font-size: 0.8rem; color: #6b7280; margin-right: 4px; }}
        .bg-btn {{ border: 1px solid #d1d5db; background: #fff; color: #374151; padding: 5px 14px; border-radius: 6px; cursor: pointer; font-size: 0.82rem; transition: all 0.15s; }}
        .bg-btn:hover {{ background: #f3f4f6; }}
        .bg-btn.active {{ background: #1f2937; color: #fff; border-color: #1f2937; }}

        .svg-container {{ flex: 1; display: flex; justify-content: center; align-items: center; padding: 0; overflow: hidden; position: relative; background-image: radial-gradient(#e5e7eb 1px, transparent 0); background-size: 20px 20px; }}
        .svg-wrapper {{ width: 100%; height: 100%; position: relative; overflow: hidden; cursor: grab; }}
        .svg-wrapper:active {{ cursor: grabbing; }}
        .bg-layer {{ position: absolute; inset: 0; display: flex; justify-content: center; align-items: center; }}
        .raster-content {{ position: absolute; inset: 0; transform-origin: 0 0; }}
        .raster-content img {{ width: 100%; height: 100%; object-fit: contain; display: block; }}
        .raster-overlay {{ position: absolute; pointer-events: none; }}
    </style>
</head>
<body>
    <div id="sidebar">
        <div class="header">
            <h2>🚨 Compliance Review Report</h2>
            <p><b>{len(violations)}</b> violation(s) found</p>
        </div>
        <div id="violation-list">
            {violation_items_html}
        </div>
    </div>

    <div id="main-content">
        <div id="detail-header" onclick="resetView()">
            👉 Interactive mode enabled. Click a violation on the left to highlight it. (💡 Scroll to zoom, drag to pan)
        </div>

        <!-- background switcher toolbar -->
        <div id="bg-switch">
            <span>Background:</span>
            <button class="bg-btn active" data-bg="orig" onclick="switchBg('orig')">Original</button>
            <button class="bg-btn" data-bg="spaces" onclick="switchBg('spaces')">Space-Recognized</button>
            <button class="bg-btn" data-bg="topo" onclick="switchBg('topo')">Topology</button>
        </div>

        <div class="svg-container">
            <div class="svg-wrapper">
                <div class="bg-layer" id="bg-orig" style="display:flex;">
                    {orig_svg_content}
                </div>
                <div class="bg-layer" id="bg-spaces" style="display:none;">
                    {('<div class="raster-content" id="rc-spaces"><img id="spaces-img" src="' + instance_src + '" alt="space-recognized"><svg id="spaces-overlay" class="raster-overlay"></svg></div>') if instance_available else "<p style='color:#7a8aa0; text-align:center;'>Space-recognized image not found (output/viz/*_instance.png)</p>"}
                </div>
                <div class="bg-layer" id="bg-topo" style="display:none;">
                    {('<div class="raster-content" id="rc-topo"><img id="topo-img" src="' + topo_src + '" alt="topology"><svg id="topo-overlay" class="raster-overlay"></svg></div>') if topo_available else "<p style='color:#7a8aa0; text-align:center;'>Topology image not found (output/viz/*_topology.png)</p>"}
                </div>
            </div>
        </div>
    </div>

    <script>
        // 前端接收由 Python 注入的违规多边形坐标数据
        const violationData = {images_json};
        // 光栅底图（Space/Topology）的物理坐标 -> 像素 仿射系数
        const bgTransforms = {bg_transforms_json};
        let activeBg = 'orig';

        // ===== 光栅底图布局：让高亮遮罩 SVG 与 object-fit:contain 的图片内容精确对齐 =====
        function layoutRaster(imgId, overlayId) {{
            const img = document.getElementById(imgId);
            const overlay = document.getElementById(overlayId);
            if (!img || !overlay) return;
            const nw = img.naturalWidth, nh = img.naturalHeight;
            const elW = img.clientWidth, elH = img.clientHeight;
            if (!nw || !nh || !elW || !elH) return;
            const k = Math.min(elW / nw, elH / nh);
            const w = nw * k, h = nh * k;
            const ox = (elW - w) / 2, oy = (elH - h) / 2;
            overlay.style.left = ox + 'px';
            overlay.style.top = oy + 'px';
            overlay.style.width = w + 'px';
            overlay.style.height = h + 'px';
            overlay.setAttribute('viewBox', '0 0 ' + nw + ' ' + nh);
        }}

        function layoutRasters() {{
            layoutRaster('spaces-img', 'spaces-overlay');
            layoutRaster('topo-img', 'topo-overlay');
        }}

        // Background switching: Original / Space-Recognized / Topology
        function switchBg(bg) {{
            activeBg = bg;
            document.querySelectorAll('.bg-btn').forEach(b => b.classList.toggle('active', b.dataset.bg === bg));
            ['orig','spaces','topo'].forEach(k => {{
                const layer = document.getElementById('bg-' + k);
                if (layer) layer.style.display = (k === bg) ? 'flex' : 'none';
            }});
            layoutRasters();
            resetView();
        }}

        // Returns the element that receives the zoom/pan CSS transform
        function getActiveEl() {{
            if (activeBg === 'spaces') return document.getElementById('rc-spaces');
            if (activeBg === 'topo') return document.getElementById('rc-topo');
            return document.getElementById('cad-svg');
        }}

        // ===== 多边形绘制辅助 =====
        function appendPolygons(overlay, polys, strokeW) {{
            if (!overlay) return;
            overlay.innerHTML = '';
            if (!polys || polys.length === 0) return;
            polys.forEach(polyPts => {{
                const pointsStr = polyPts.map(p => p[0] + ',' + p[1]).join(' ');
                const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                polygon.setAttribute('points', pointsStr);
                polygon.setAttribute('fill', 'rgba(220, 38, 38, 0.45)');
                polygon.setAttribute('stroke', '#dc2626');
                polygon.setAttribute('stroke-width', strokeW);
                polygon.style.transition = "all 0.3s ease";
                overlay.appendChild(polygon);
            }});
            // Virtual flow line (exactly 2 distinct regions): draw a warning link between them
            if (polys.length === 2) {{
                const p1 = polys[0], p2 = polys[1];
                const cx1 = p1.reduce((s, p) => s + p[0], 0) / p1.length;
                const cy1 = p1.reduce((s, p) => s + p[1], 0) / p1.length;
                const cx2 = p2.reduce((s, p) => s + p[0], 0) / p2.length;
                const cy2 = p2.reduce((s, p) => s + p[1], 0) / p2.length;
                const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                line.setAttribute('x1', cx1); line.setAttribute('y1', cy1);
                line.setAttribute('x2', cx2); line.setAttribute('y2', cy2);
                line.setAttribute('stroke', '#dc2626'); line.setAttribute('stroke-width', strokeW * 1.3);
                line.setAttribute('stroke-dasharray', '2,2');
                overlay.appendChild(line);
            }}
        }}

        // 物理坐标 -> 光栅图自然像素坐标（通过注入的仿射系数）
        function physToPixel(physPolys, t) {{
            if (!t || !physPolys) return [];
            return physPolys.map(poly => poly.map(p => [t.ax * p[0] + t.bx, t.ay * p[1] + t.by]));
        }}

        // 1. Handle sidebar click: render polygon highlights on all aligned overlays
        function highlightViolation(safeId) {{
            document.querySelectorAll('.violation-item').forEach(el => el.classList.remove('active'));
            document.getElementById('item-' + safeId).classList.add('active');

            const data = violationData[safeId];
            const header = document.getElementById('detail-header');
            header.innerHTML = `<strong>🚨 Violation detail:</strong> [${{data.node_id}}] ${{data.message}} (click here to clear highlight & reset view)`;
            header.style.backgroundColor = '#fef2f2';
            header.style.color = '#991b1b';
            header.style.borderColor = '#fca5a5';

            drawOverlays(data);
            focusOnViolation(safeId);
        }}

        function drawOverlays(data) {{
            if (!data) return;
            // Original SVG: 使用 SVG viewBox 坐标
            appendPolygons(document.getElementById('highlight-overlay'), data.polygons, 0.6);
            // Space/Topology: 使用物理坐标 -> 像素，绘制到各自的对齐遮罩
            appendPolygons(document.getElementById('spaces-overlay'), physToPixel(data.phys_polygons, bgTransforms['spaces']), 1.5);
            appendPolygons(document.getElementById('topo-overlay'), physToPixel(data.phys_polygons, bgTransforms['topo']), 1.5);
        }}

        // 自然像素坐标 -> 视口(wrapper)坐标（考虑 object-fit 的黑边偏移）
        function rasterToWrapper(px, py, img) {{
            const nw = img.naturalWidth || 1, nh = img.naturalHeight || 1;
            const elW = img.clientWidth, elH = img.clientHeight;
            const k = Math.min(elW / nw, elH / nh);
            const ox = (elW - nw * k) / 2, oy = (elH - nh * k) / 2;
            return [ox + px * k, oy + py * k];
        }}

        // 1.5 自动聚焦到违规区域（平移+缩放），确保高亮区域在视口中居中可见
        function focusOnViolation(safeId) {{
            const data = violationData[safeId];
            if (!data || !data.polygons || data.polygons.length === 0) return;

            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
            data.polygons.forEach(function(pts) {{ pts.forEach(function(p) {{
                if (p[0] < minX) minX = p[0]; if (p[1] < minY) minY = p[1];
                if (p[0] > maxX) maxX = p[0]; if (p[1] > maxY) maxY = p[1];
            }}); }});
            if (minX > maxX || minY > maxY) return;

            let focus;
            if (activeBg === 'spaces' || activeBg === 'topo') {{
                const img = (activeBg === 'spaces') ? document.getElementById('spaces-img') : document.getElementById('topo-img');
                const t = bgTransforms[activeBg];
                if (!img || !t || !data.phys_polygons) return;
                // 1) 物理坐标 -> 自然像素坐标
                let minPx = Infinity, minPy = Infinity, maxPx = -Infinity, maxPy = -Infinity;
                data.phys_polygons.forEach(function(pts) {{ pts.forEach(function(p) {{
                    const px = t.ax * p[0] + t.bx, py = t.ay * p[1] + t.by;
                    if (px < minPx) minPx = px; if (py < minPy) minPy = py;
                    if (px > maxPx) maxPx = px; if (py > maxPy) maxPy = py;
                }}); }});
                // 2) 自然像素 -> 视口坐标
                const a = rasterToWrapper(minPx, minPy, img);
                const b = rasterToWrapper(maxPx, maxPy, img);
                focus = {{ minX: a[0], minY: a[1], maxX: b[0], maxY: b[1] }};
            }} else {{
                // SVG background: map viewBox coords to element-local coords (no CSS transform applied)
                const cad = getActiveEl();
                if (!cad) return;
                const vw = cad.viewBox.baseVal.width, vh = cad.viewBox.baseVal.height;
                const elW = cad.clientWidth, elH = cad.clientHeight;
                if (vw === 0 || vh === 0 || elW === 0 || elH === 0) return;
                const k = Math.min(elW / vw, elH / vh);
                const ox = (elW - vw * k) / 2, oy = (elH - vh * k) / 2;
                focus = {{ minX: ox + minX * k, minY: oy + minY * k, maxX: ox + maxX * k, maxY: oy + maxY * k }};
            }}

            const cw = svgWrapper.clientWidth, ch = svgWrapper.clientHeight;
            const bw = focus.maxX - focus.minX, bh = focus.maxY - focus.minY;
            const pad = 0.2; // 20% 外边距
            const targetScale = Math.min(cw / (bw * (1 + pad * 2)), ch / (bh * (1 + pad * 2)));
            scale = Math.max(0.5, Math.min(30, targetScale));
            translateX = cw / 2 - ((focus.minX + focus.maxX) / 2) * scale;
            translateY = ch / 2 - ((focus.minY + focus.maxY) / 2) * scale;
            updateTransform();
        }}

        // 2. 恢复初始状态
        function resetView() {{
            document.querySelectorAll('.violation-item').forEach(el => el.classList.remove('active'));

            const header = document.getElementById('detail-header');
            header.innerHTML = `👉 Interactive mode enabled. Click a violation on the left to highlight it. (💡 Scroll to zoom, drag to pan)`;
            header.style.backgroundColor = '#f9fafb';
            header.style.color = '#4b5563';
            header.style.borderColor = '#e5e7eb';

            ['highlight-overlay', 'spaces-overlay', 'topo-overlay'].forEach(id => {{
                const o = document.getElementById(id);
                if (o) o.innerHTML = '';
            }});

            // 重置视口缩放和平移
            scale = 1.0;
            translateX = 0;
            translateY = 0;
            updateTransform();
        }}

        // 3. 核心功能：添加鼠标滚轮缩放与拖拽平移支持
        const svgWrapper = document.querySelector('.svg-wrapper');
        let scale = 1.0;
        let isDragging = false;
        let startX, startY, translateX = 0, translateY = 0;

        // Apply the CSS transform to the currently active background
        function updateTransform() {{
            const el = getActiveEl();
            if (el) el.style.transform = `translate(${{translateX}}px, ${{translateY}}px) scale(${{scale}})`;
        }}

        // 滚轮缩放逻辑
        svgWrapper.addEventListener('wheel', function(e) {{
            e.preventDefault();
            const rect = svgWrapper.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;

            const zoomFactor = 1.15;
            const direction = e.deltaY > 0 ? -1 : 1;
            const newScale = direction > 0 ? scale * zoomFactor : scale / zoomFactor;

            // 限制缩放级别 (0.5x 到 30x)
            if (newScale >= 0.5 && newScale <= 30) {{
                // 以鼠标当前悬停位置为中心进行平滑缩放
                translateX = mouseX - (mouseX - translateX) * (newScale / scale);
                translateY = mouseY - (mouseY - translateY) * (newScale / scale);
                scale = newScale;
                updateTransform();
            }}
        }}, {{ passive: false }});

        // 鼠标按住拖拽逻辑
        svgWrapper.addEventListener('mousedown', function(e) {{
            if(e.button !== 0) return;
            isDragging = true;
            startX = e.clientX - translateX;
            startY = e.clientY - translateY;
        }});

        window.addEventListener('mouseup', function() {{
            isDragging = false;
        }});

        window.addEventListener('mousemove', function(e) {{
            if (!isDragging) return;
            e.preventDefault();
            translateX = e.clientX - startX;
            translateY = e.clientY - startY;
            updateTransform();
        }});

        // 图片加载完成后校准遮罩布局
        ['spaces-img', 'topo-img'].forEach(id => {{
            const img = document.getElementById(id);
            if (img) {{
                if (img.complete) layoutRasters();
                img.addEventListener('load', layoutRasters);
            }}
        }});
        window.addEventListener('resize', layoutRasters);
    </script>
</body>
</html>"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"✅ Full-height native-SVG interactive report generated (with zoom & pan): {output_path}")