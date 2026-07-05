import json
import re
import os


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
        支持实体节点自身的坐标，以及虚拟节点（如流线）的拓扑级联关联坐标提取。
        """
        pts = self._get_geometry(node_id)
        if pts:
            return [pts]  # 如果自身有物理坐标，直接返回

        # 如果自身没有坐标（如虚拟流线），提取其相邻节点的坐标作为展示范围
        node = self.nodes.get(node_id, {})
        polys = []
        adjacents = node.get("bot:adjacentZone", [])
        if not isinstance(adjacents, list): adjacents = [adjacents]

        for adj in adjacents:
            adj_id = adj.get("@id") if isinstance(adj, dict) else adj
            adj_pts = self._get_geometry(adj_id)
            if adj_pts:
                polys.append(adj_pts)

        return polys

    def draw_annotated_report(self, violations, output_path="compliance_report.html"):
        """
        生成单栏全屏、基于纯原生 SVG 交互的 HTML 报告
        """
        print(f"🎨 正在生成单栏高清原生 SVG 交互式 Web 审查报告...")

        # --- 1. 处理原始 SVG 图纸 ---
        svg_content = "<p style='color:red; text-align:center;'>⚠️ 找不到原始 SVG 图纸，无法渲染底图。</p>"
        scale_factor = 1.0
        vb_h = 140.0  # 默认视口高度

        if os.path.exists(self.svg_path):
            with open(self.svg_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()

            # 暴力清洗 XML 头，防止破坏 HTML DOM
            svg_content = re.sub(r'<\?xml.*?\?>', '', svg_content, flags=re.IGNORECASE).strip()
            svg_content = re.sub(r'<!DOCTYPE.*?>', '', svg_content, flags=re.IGNORECASE).strip()

            # 提取图纸真实的缩放系数和视口高度，以便做坐标逆向映射
            scale_match = re.search(r'scale="([\d\.]+)"', svg_content)
            if scale_match:
                scale_factor = float(scale_match.group(1))

            vb_match = re.search(r'viewBox="[\d\.]+\s+[\d\.]+\s+([\d\.]+)\s+([\d\.]+)"', svg_content)
            if vb_match:
                vb_h = float(vb_match.group(2))

            # 在 </svg> 标签前注入一个空的 <g> 组，专门用于前端 JS 动态绘制高亮遮罩
            overlay_group = '<g id="highlight-overlay"></g>'
            svg_content = re.sub(r'</svg>', f'{overlay_group}</svg>', svg_content, flags=re.IGNORECASE)

            # 强制替换 svg 的宽高为 100%，并添加 id 以供后续实现 JS 缩放/平移
            svg_content = re.sub(r'(<svg[^>]*)(width="[^"]*")', r'\1', svg_content, count=1, flags=re.IGNORECASE)
            svg_content = re.sub(r'(<svg[^>]*)(height="[^"]*")', r'\1', svg_content, count=1, flags=re.IGNORECASE)
            svg_content = re.sub(r'<svg',
                                 '<svg width="100%" height="100%" preserveAspectRatio="xMidYMid meet" style="display: block; transform-origin: 0 0;" id="cad-svg"',
                                 svg_content, count=1, flags=re.IGNORECASE)

        # --- 2. 准备传入前端 JS 的结构化违规数据 ---
        violation_data_for_js = {}
        violation_items_html = ""

        for idx, v in enumerate(violations):
            node_id = v['node_id']
            msg = v['message']
            safe_id = re.sub(r'[^a-zA-Z0-9]', '_', node_id)

            polys = self._get_node_polygons(node_id)
            svg_polys = []

            # 核心数学转换：将知识图谱中的绝对物理坐标 (WKT) 重新映射回 SVG viewBox 坐标系
            if polys:
                for pts in polys:
                    svg_pts = []
                    for x, y in pts:
                        sx = x * scale_factor
                        sy = vb_h - (y * scale_factor)
                        svg_pts.append([sx, sy])
                    svg_polys.append(svg_pts)

            violation_data_for_js[safe_id] = {
                "polygons": svg_polys,
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
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>BIM 自动化合规审查交互报告</title>
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
        .svg-container {{ flex: 1; display: flex; justify-content: center; align-items: center; padding: 0; overflow: hidden; position: relative; background-image: radial-gradient(#e5e7eb 1px, transparent 0); background-size: 20px 20px; }}
        .svg-wrapper {{ width: 100%; height: 100%; background: transparent; overflow: hidden; display: flex; justify-content: center; align-items: center; cursor: grab; }}
        .svg-wrapper:active {{ cursor: grabbing; }}
    </style>
</head>
<body>
    <div id="sidebar">
        <div class="header">
            <h2>🚨 合规审查报告</h2>
            <p>共发现 <b>{len(violations)}</b> 处规范违背情况</p>
        </div>
        <div id="violation-list">
            {violation_items_html}
        </div>
    </div>

    <div id="main-content">
        <!-- 顶部动态状态栏 -->
        <div id="detail-header" onclick="resetView()">
            👉 交互模式已开启。点击左侧违规项可查看高亮遮罩。（💡支持鼠标滚轮缩放与左键拖拽平移图纸）
        </div>

        <!-- 占据整个主界面的高清 SVG 视图 -->
        <div class="svg-container">
            <div class="svg-wrapper">
                {svg_content}
            </div>
        </div>
    </div>

    <script>
        // 前端接收由 Python 注入的违规多边形坐标数据
        const violationData = {images_json};

        // 1. 响应点击左侧面板，渲染多边形高亮
        function highlightViolation(safeId) {{
            // 更新左侧列表 UI 状态
            document.querySelectorAll('.violation-item').forEach(el => el.classList.remove('active'));
            document.getElementById('item-' + safeId).classList.add('active');

            const data = violationData[safeId];

            // 更新顶部警示横幅
            const header = document.getElementById('detail-header');
            header.innerHTML = `<strong>🚨 违规详情:</strong> [${{data.node_id}}] ${{data.message}} (点击此处可清除高亮与复位视图)`;
            header.style.backgroundColor = '#fef2f2';
            header.style.color = '#991b1b';
            header.style.borderColor = '#fca5a5';

            // 在原生 SVG 底层直接注入动态遮罩
            const overlay = document.getElementById('highlight-overlay');
            if (overlay) {{
                overlay.innerHTML = ''; // 清除之前的遮罩

                if (data.polygons && data.polygons.length > 0) {{
                    data.polygons.forEach(polyPts => {{
                        const pointsStr = polyPts.map(p => p[0] + ',' + p[1]).join(' ');
                        const polygon = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
                        polygon.setAttribute('points', pointsStr);
                        polygon.setAttribute('fill', 'rgba(220, 38, 38, 0.45)'); 
                        polygon.setAttribute('stroke', '#dc2626');               
                        polygon.setAttribute('stroke-width', '0.6');             
                        polygon.style.transition = "all 0.3s ease";
                        overlay.appendChild(polygon);
                    }});

                    // 如果是虚拟流线（正好关联了2个独立区域），在它们中间拉一条警示连线！
                    if (data.polygons.length === 2) {{
                        const p1 = data.polygons[0];
                        const p2 = data.polygons[1];

                        const cx1 = p1.reduce((sum, p) => sum + p[0], 0) / p1.length;
                        const cy1 = p1.reduce((sum, p) => sum + p[1], 0) / p1.length;
                        const cx2 = p2.reduce((sum, p) => sum + p[0], 0) / p2.length;
                        const cy2 = p2.reduce((sum, p) => sum + p[1], 0) / p2.length;

                        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
                        line.setAttribute('x1', cx1);
                        line.setAttribute('y1', cy1);
                        line.setAttribute('x2', cx2);
                        line.setAttribute('y2', cy2);
                        line.setAttribute('stroke', '#dc2626');
                        line.setAttribute('stroke-width', '0.8');
                        line.setAttribute('stroke-dasharray', '2,2');
                        overlay.appendChild(line);
                    }}
                }} else {{
                    console.warn("未找到该节点的几何坐标数据。");
                }}
            }}
        }}

        // 2. 恢复初始状态
        function resetView() {{
            document.querySelectorAll('.violation-item').forEach(el => el.classList.remove('active'));

            const header = document.getElementById('detail-header');
            header.innerHTML = `👉 交互模式已开启。点击左侧违规项可查看高亮遮罩。（💡支持鼠标滚轮缩放与左键拖拽平移图纸）`;
            header.style.backgroundColor = '#f9fafb';
            header.style.color = '#4b5563';
            header.style.borderColor = '#e5e7eb';

            const overlay = document.getElementById('highlight-overlay');
            if (overlay) {{
                overlay.innerHTML = '';
            }}

            // 重置视口缩放和平移
            scale = 1.0;
            translateX = 0;
            translateY = 0;
            updateTransform();
        }}

        // 3. 核心功能：添加鼠标滚轮缩放与拖拽平移支持
        const svgWrapper = document.querySelector('.svg-wrapper');
        const cadSvg = document.getElementById('cad-svg');
        let scale = 1.0;
        let isDragging = false;
        let startX, startY, translateX = 0, translateY = 0;

        if (cadSvg) {{
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
                // 仅响应鼠标左键拖拽
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

            // 更新应用至 CSS 变换
            function updateTransform() {{
                cadSvg.style.transform = `translate(${{translateX}}px, ${{translateY}}px) scale(${{scale}})`;
            }}
        }}
    </script>
</body>
</html>"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"✅ 单栏原生 SVG 高清交互式报告已生成 (已集成缩放与平移功能): {output_path}")