"""
kg_browser.py — Knowledge Graph browser for enriched JSON-LD.

A single self-contained HTML per drawing with three views (tabs):
  [全图]      整个知识图谱：所有节点与全部关系，可按富化阶段切换、按边类型过滤
  [富化过程]  分步回放富化管线（raw/语义/几何/ACD/几何/拓扑），高亮每步增删
  [套型从属]  Suite->Space 从属关系专项：按套型着色平面图 + 成员表 + 异常标志
              （由原 suite_viz.py 迁移而来，本文件已取代它）

Usage (project venv, from project root):
    python -m src.utils.kg_browser --base "2suite (1)"
    python -m src.utils.kg_browser --input "output/jsonld/2suite (1).jsonld"
    python -m src.utils.kg_browser --base "2suite (1)" --no-llm      # 规则沙箱回放
    python -m src.utils.kg_browser --mode BATCH --out-dir output/viz

输出：output/viz/<base>_kg_browser.html（依赖 vis.js CDN，与项目 pyvis 用法一致）
"""
import argparse
import base64
import copy
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from shapely import wkt
from shapely.geometry import Polygon, MultiPolygon

from src.config.config import settings


GROUP_COLORS = {
    "Suite": "#FBAD50", "Space": "#97C2FC", "Door": "#FFD700",
    "Window": "#B0E57C", "Element": "#D3D3D3", "removed": "#FBE2E2",
}
EDGE_META = {
    "bot:adjacentZone": ("#9AA5B1", False, "邻接"),
    "bot:containsElement": ("#7FB3E0", False, "包含"),
    "bot:interfaceOf": ("#E67E22", False, "接口"),
    "bot:hasSpace": ("#8E44AD", True, "从属"),
    "bot:hasSubZone": ("#8E44AD", True, "子区"),
}
STAGE_LABELS = {
    "raw": "① Raw 白模", "semantic": "② 语义富化", "geometry": "③ 几何富化",
    "acd": "④ 凸分解 ACD", "geometry2": "⑤ 几何重算", "topology": "⑥ 拓扑+套型",
    "final": "最终图谱",
}
SUITE_COLORS = ["#E6194B", "#3CB44B", "#4363D8", "#F58231", "#911EB4", "#46F0F0",
                "#F032E6", "#BCF60C", "#008080", "#9A6324", "#800000", "#808000",
                "#000075", "#A9A9A9", "#FFD8B1", "#DCBEFF", "#AAFFC3", "#FFEE00",
                "#C0C0C0", "#800080"]
PUBLIC_COLOR = "#E5E7EB"
PUBLIC_HATCH = "///"


# --------------------------- shared helpers --------------------------- #
def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _refs(v):
    if v is None:
        return []
    if isinstance(v, dict):
        return [v.get("@id")]
    return [r.get("@id") if isinstance(r, dict) else r for r in v if r]


def load_jsonld(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def classify_node(types):
    types = _as_list(types)
    if "bldg:Suite" in types or "bot:Zone" in types:
        return "Suite"
    if "bot:Space" in types:
        return "Space"
    if "beo:Door" in types:
        return "Door"
    if "beo:Window" in types:
        return "Window"
    return "Element"


def space_semantic(types):
    for t in _as_list(types):
        if t.startswith("bldg:") and t != "bldg:Suite" and "Door" not in t:
            return t.replace("bldg:", "")
    return ""


# --------------------------- whole-KG extraction --------------------------- #
def extract_graph(graph):
    nodes, edges = [], []
    for item in graph.get("@graph", []):
        nid = item.get("@id")
        if not nid:
            continue
        types = item.get("@type", [])
        group = classify_node(types)
        label = nid.split(":")[-1]
        if group == "Space" and space_semantic(types):
            label = f"{label}\n{space_semantic(types)}"
        nodes.append({"id": nid, "label": label, "group": group})

    for item in graph.get("@graph", []):
        nid = item.get("@id")
        for rel in EDGE_META:
            for tgt in _refs(item.get(rel)):
                if tgt:
                    edges.append({"from": nid, "to": tgt, "type": rel})

    seen, uniq = set(), []
    for e in edges:
        k = (e["from"], e["to"], e["type"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return nodes, uniq


def graph_stats(graph):
    nodes, edges = extract_graph(graph)
    gl = graph.get("@graph", [])
    return {
        "nodes_by_group": dict(Counter(n["group"] for n in nodes)),
        "edges_by_type": dict(Counter(e["type"] for e in edges)),
        "suites": sum(1 for n in gl if "bldg:Suite" in _as_list(n.get("@type"))),
        "spaces": sum(1 for n in gl if "bot:Space" in _as_list(n.get("@type"))),
        "doors": sum(1 for n in gl if "beo:Door" in _as_list(n.get("@type"))),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }


def diff_between(pn, pe, cn, ce):
    pn_s, cn_s = {n["id"] for n in pn}, {n["id"] for n in cn}
    pe_s = {(e["from"], e["to"], e["type"]) for e in pe}
    ce_s = {(e["from"], e["to"], e["type"]) for e in ce}
    return {
        "added_nodes": sorted(cn_s - pn_s),
        "removed_nodes": sorted(pn_s - cn_s),
        "added_edges": sorted(ce_s - pe_s),
        "removed_edges": sorted(pe_s - ce_s),
    }


# --------------------------- stage capture --------------------------- #
def extract_room_texts(svg_path):
    from src.io.extractor import ElementExtractor
    texts = []
    for elem in ElementExtractor().process(str(svg_path)):
        if elem.get("type") == "text" or "text" in elem:
            coords = elem.get("coords", [0, 0])
            texts.append({"text": elem.get("text", elem.get("label", "")),
                          "point": (coords[0], coords[1])})
    return texts


def run_pipeline_stages(raw_graph, svg_path, use_llm):
    room_texts = extract_room_texts(svg_path) if svg_path and os.path.exists(svg_path) else []
    llm_client = None
    if use_llm and settings.llm_api_key:
        import openai
        try:
            llm_client = openai.Client(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
        except Exception as e:
            print(f"  ⚠️ LLM client init failed: {e}, using sandbox.")
    from src.enricher.enricher_pipeline import GraphEnrichmentPipeline
    pipeline = GraphEnrichmentPipeline(raw_graph, room_texts, llm_client)
    pipeline.run_all(collect_snapshots=True)
    stages = [{"stage": "raw", "graph": copy.deepcopy(raw_graph)}] + pipeline.snapshots
    return stages, llm_client is not None


def build_stage_data(stages):
    out, pn, pe = [], [], []
    for st in stages:
        nodes, edges = extract_graph(st["graph"])
        diff = diff_between(pn, pe, nodes, edges) if out else None
        out.append({"name": st["stage"],
                    "label": STAGE_LABELS.get(st["stage"], st["stage"]),
                    "nodes": nodes, "edges": edges,
                    "stats": graph_stats(st["graph"]), "diff": diff})
        pn, pe = nodes, edges
    return out


# --------------------------- suite containment view --------------------------- #
def extract_membership(graph):
    gl = graph.get("@graph", [])
    suites = [n for n in gl if "bldg:Suite" in _as_list(n.get("@type"))]
    space_map = {n["@id"]: n for n in gl if "bot:Space" in _as_list(n.get("@type"))}
    assigned = {}
    for s in suites:
        for ref in _as_list(s.get("bot:hasSpace")):
            sid = ref.get("@id") if isinstance(ref, dict) else ref
            if sid:
                assigned.setdefault(sid, []).append(s["@id"])
    return {"suites": suites, "space_map": space_map, "assigned": assigned,
            "unassigned": [sid for sid in space_map if sid not in assigned],
            "multi": {sid: ids for sid, ids in assigned.items() if len(ids) > 1}}


def infer_expected_suites(name):
    m = re.match(r"^\s*(\d+)\s*suite", name, flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def _space_label(node):
    for t in _as_list(node.get("@type")):
        if t.startswith("bldg:") and t != "bldg:Suite" and "Door" not in t:
            return t.replace("bldg:", "")
    return "Space"


def _space_area(node):
    a = node.get("props:hasArea")
    return a if isinstance(a, (int, float)) else None


def _wkt_geom(node):
    raw = node.get("geo:asWKT")
    if isinstance(raw, dict):
        raw = raw.get("@value", "")
    if not raw:
        return None
    try:
        g = wkt.loads(str(raw))
    except Exception:
        return None
    return g if isinstance(g, (Polygon, MultiPolygon)) else None


def _as_polys(geom):
    """Normalize a Polygon / MultiPolygon into a list of Polygon parts."""
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    return [geom]


def detect_anomalies(ms, expected, base=""):
    issues, n = [], len(ms["suites"])
    if expected is not None and n != expected:
        issues.append(f"套房数量异常：检测到 {n} 个 Suite，而根据文件名预期 {expected} 个")
    sizes = [len(s.get("bot:hasSpace", [])) for s in ms["suites"]]
    total = sum(sizes)
    if n and total and max(sizes) / total > 0.75:
        issues.append(f"疑似套型合并：单个 Suite 包含了 {max(sizes) / total:.0%} 的私有空间")
    small = [s["@id"] for s in ms["suites"] if len(s.get("bot:hasSpace", [])) == 1]
    if small:
        issues.append(f"单空间 Suite（可能为外部/花园误分）：{', '.join(small)}")
    if ms["unassigned"]:
        issues.append(f"{len(ms['unassigned'])} 个空间未归属任何 Suite：{', '.join(ms['unassigned'][:8])}"
                      + (" ..." if len(ms["unassigned"]) > 8 else ""))
    if ms["multi"]:
        issues.append(f"{len(ms['multi'])} 个空间被多个 Suite 同时归属：{', '.join(ms['multi'])}")
    return issues


def _plot_polygon(ax, geom, facecolor, edgecolor="black", alpha=0.6, lw=1.0, zorder=1, hatch=None):
    for p in (geom.geoms if geom.geom_type == "MultiPolygon" else [geom]):
        x, y = p.exterior.xy
        ax.fill(x, y, fc=facecolor, ec=edgecolor, alpha=alpha, lw=lw, zorder=zorder, hatch=hatch)
        for interior in p.interiors:
            ix, iy = interior.xy
            ax.plot(ix, iy, color=edgecolor, lw=lw, zorder=zorder + 1, alpha=alpha)


def draw_suite_png(ms, output_path, base_name="", expected=None):
    plt.rcParams["font.sans-serif"] = ["SimHei", "Songti SC", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    suite_ids = [s["@id"] for s in ms["suites"]]
    color_of = {sid: SUITE_COLORS[i % len(SUITE_COLORS)] for i, sid in enumerate(suite_ids)}
    fig, ax = plt.subplots(figsize=(11, 8), dpi=300)
    fig.patch.set_facecolor("#FFFFFF")
    for n in ms["space_map"].values():
        geom = _wkt_geom(n)
        if geom is None:
            continue
        owners = ms["assigned"].get(n["@id"], [])
        _plot_polygon(ax, geom,
                      facecolor=color_of[owners[0]] if owners else PUBLIC_COLOR,
                      hatch=None if owners else PUBLIC_HATCH)
    for s in ms["suites"]:
        gs = [_wkt_geom(ms["space_map"].get(r["@id"])) for r in _as_list(s.get("bot:hasSpace"))]
        gs = [g for g in gs if g]
        if not gs:
            continue
        u = gs[0]
        for g in gs[1:]:
            u = u.union(g)
        c = u.centroid
        ax.text(c.x, c.y, f"{s['@id'].split(':')[-1]} ({len(gs)})", ha="center", va="center",
                fontsize=11, fontweight="bold", color="#222", zorder=12,
                bbox=dict(facecolor="white", alpha=0.75, edgecolor=color_of[s["@id"]], lw=1.5))
    ax.set_aspect("equal")
    title = f"Suite Membership (Space -> Suite) — {base_name or 'System Output'}"
    if expected is not None:
        title += f"   [expected {expected} suites, found {len(ms['suites'])}]"
    ax.set_title(title, pad=15, fontsize=13)
    ax.axis("off")
    handles = [mpatches.Patch(facecolor=PUBLIC_COLOR, hatch=PUBLIC_HATCH, edgecolor="gray",
                              label=f"Public / unassigned ({len(ms['unassigned'])})")]
    handles += [mpatches.Patch(facecolor=color_of[s["@id"]], edgecolor="black",
                               label=f"{s['@id'].split(':')[-1]} — {len(s.get('bot:hasSpace', []))} spaces")
                for s in ms["suites"]]
    ax.legend(handles=handles, loc="upper left", fontsize=8, framealpha=0.9)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out, bbox_inches="tight")
    plt.close("all")


def suite_svg_plan(ms):
    geoms = {sid: g for sid, node in ms["space_map"].items()
             if (g := _wkt_geom(node)) is not None}
    if not geoms:
        return ""
    all_b = [g.bounds for g in geoms.values()]
    minx, miny = min(b[0] for b in all_b), min(b[1] for b in all_b)
    maxx, maxy = max(b[2] for b in all_b), max(b[3] for b in all_b)
    pad = max(maxx - minx, maxy - miny) * 0.03 + 1e-6
    minx, maxx, miny, maxy = minx - pad, maxx + pad, miny - pad, maxy + pad
    tx = lambda x: x - minx
    ty = lambda y: maxy - y
    suite_ids = [s["@id"] for s in ms["suites"]]
    color_of = {sid: SUITE_COLORS[i % len(SUITE_COLORS)] for i, sid in enumerate(suite_ids)}
    parts = []
    for sid, geom in geoms.items():
        owners = ms["assigned"].get(sid, [])
        fill = color_of[owners[0]] if owners else "#e5e7eb"
        dash = "none" if owners else "4 3"
        node = ms["space_map"][sid]
        area = _space_area(node)
        area_s = f"{area:.1f}m²" if area is not None else "n/a"
        for p in _as_polys(geom):
            pts = " ".join(f"{tx(x):.1f},{ty(y):.1f}" for x, y in p.exterior.coords)
            parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="#333" stroke-width="1.2" '
                         f'stroke-dasharray="{dash}" data-space="{sid.split(":")[-1]}" '
                         f'data-suite="{owners[0].split(":")[-1] if owners else "None"}" '
                         f'data-type="{_space_label(node)}" data-area="{area_s}"/>')
        c = geom.centroid
        parts.append(f'<circle cx="{tx(c.x):.1f}" cy="{ty(c.y):.1f}" r="2.2" fill="none" stroke="#111"/>')
    for s in ms["suites"]:
        gs = [_wkt_geom(ms["space_map"].get(r["@id"])) for r in _as_list(s.get("bot:hasSpace"))]
        gs = [g for g in gs if g]
        if not gs:
            continue
        u = gs[0]
        for g in gs[1:]:
            u = u.union(g)
        c = u.centroid
        parts.append(f'<text x="{tx(c.x):.1f}" y="{ty(c.y):.1f}" text-anchor="middle" font-size="16" '
                     f'font-weight="bold" fill="#222" paint-order="stroke" stroke="#fff" stroke-width="3">'
                     f'{s["@id"].split(":")[-1]} · {len(gs)}</text>')
    return (f'<svg id="suite-plan" viewBox="0 0 {maxx - minx:.1f} {maxy - miny:.1f}" '
            f'preserveAspectRatio="xMidYMid meet">' + "".join(parts) + "</svg>")


def suite_context(graph, base_name, expected, png_path=None):
    ms = extract_membership(graph)
    suite_ids = [s["@id"] for s in ms["suites"]]
    color_of = {sid: SUITE_COLORS[i % len(SUITE_COLORS)] for i, sid in enumerate(suite_ids)}
    legend = "".join(
        f'<span class="sw"><span class="chip" style="background:{color_of[s["@id"]]}"></span>'
        f'{s["@id"].split(":")[-1]} <b>{len(s.get("bot:hasSpace", []))}</b></span>'
        for s in ms["suites"])
    legend += (f'<span class="sw"><span class="chip public"></span>公共/未归属 '
               f'<b>{len(ms["unassigned"])}</b></span>')
    rows = ""
    for s in ms["suites"]:
        cells = []
        for ref in _as_list(s.get("bot:hasSpace")):
            sp_id = ref.get("@id") if isinstance(ref, dict) else ref
            if not sp_id:
                continue
            node = ms["space_map"].get(sp_id)
            if node is None:
                cells.append(f'<span class="m">{sp_id.split(":")[-1]} <i>missing</i></span>')
                continue
            area = _space_area(node)
            cells.append(f'<span class="m" title="{sp_id}">{sp_id.split(":")[-1]} '
                         f'<i>{_space_label(node)}</i> '
                         f'<em>{f"{area:.1f}m²" if area is not None else ""}</em></span>')
        rows += (f'<tr><td><span class="chip" style="background:{color_of[s["@id"]]}"></span>'
                 f'<b>{s["@id"].split(":")[-1]}</b></td>'
                 f'<td class="cnt">{len(_as_list(s.get("bot:hasSpace")))}</td>'
                 f'<td class="members">{" ".join(cells) if cells else "—"}</td></tr>')
    if ms["unassigned"]:
        uc = [f'<span class="m">{sid.split(":")[-1]} <i>{_space_label(ms["space_map"][sid])}</i></span>'
              for sid in ms["unassigned"] if sid in ms["space_map"]]
        rows += (f'<tr class="un"><td><span class="chip public"></span><b>未归属</b></td>'
                 f'<td class="cnt">{len(ms["unassigned"])}</td>'
                 f'<td class="members">{" ".join(uc)}</td></tr>')
    issues = detect_anomalies(ms, expected, base_name)
    badges = "".join(f'<div class="badge">⚠️ {i}</div>' for i in issues) or \
             '<div class="badge ok">✅ 未检测到明显异常（请仍以 GT 为准核对）</div>'
    png_b64 = ""
    if png_path and os.path.exists(png_path):
        with open(png_path, "rb") as fh:
            png_b64 = base64.b64encode(fh.read()).decode("ascii")
    return {
        "base": base_name, "legend": legend, "rows": rows, "badges": badges,
        "svg": suite_svg_plan(ms), "png_b64": png_b64,
        "found": len(ms["suites"]), "expected": expected,
        "total_spaces": len(ms["space_map"]),
    }


# --------------------------- HTML assembly --------------------------- #
def build_html(base_name, stage_data, sctx, llm_used, out_path):
    html = (HTML_TEMPLATE
            .replace("__TITLE__", base_name)
            .replace("__LLM_NOTE__", "LLM 富化回放" if llm_used else "规则沙箱回放")
            .replace("__STEPS_JSON__", json.dumps(stage_data, ensure_ascii=False))
            .replace("__GROUP_COLORS__", json.dumps(GROUP_COLORS, ensure_ascii=False))
            .replace("__SUITE_JSON__", json.dumps(sctx, ensure_ascii=False, default=str)))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"✅ KG browser saved: {out}")


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>知识图谱浏览器 — __TITLE__</title>
<link href="https://unpkg.com/vis-network@9.1.9/styles/vis-network.min.css" rel="stylesheet">
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  body{font-family:"Segoe UI","Microsoft YaHei",sans-serif;margin:16px;background:#f7f8fa;color:#222;}
  h1{font-size:18px;margin:0 0 4px;}
  .meta{color:#555;font-size:12px;margin-bottom:10px;}
  .tabs{display:flex;gap:6px;margin:10px 0;}
  .tabs button{padding:7px 16px;border:1px solid #bbb;border-radius:6px;background:#fff;cursor:pointer;font-size:13px;}
  .tabs button.active{background:#2f6fed;color:#fff;border-color:#2f6fed;}
  .view{display:none;}
  .view.active{display:block;}
  .bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:8px 0;}
  .bar button{padding:5px 11px;border:1px solid #bbb;border-radius:6px;background:#fff;cursor:pointer;font-size:12px;}
  .bar button.active{background:#2f6fed;color:#fff;border-color:#2f6fed;}
  #net,#net2{width:100%;height:600px;border:1px solid #ddd;border-radius:8px;background:#fff;}
  .panel{display:flex;gap:14px;flex-wrap:wrap;margin-top:12px;}
  .card{background:#fff;border:1px solid #ddd;border-radius:8px;padding:10px 14px;min-width:170px;font-size:13px;}
  .card h3{margin:0 0 6px;font-size:13px;}
  table{border-collapse:collapse;width:100%;font-size:12px;}
  th,td{border:1px solid #e3e6ea;padding:3px 6px;text-align:left;}
  th{background:#f0f2f5;}
  .badge{display:inline-block;padding:2px 8px;border-radius:10px;margin:2px;font-size:12px;}
  .b-add{background:#e7f6ec;color:#1e7e34;border:1px solid #8fd9a6;}
  .b-del{background:#fdecec;color:#b3261e;border:1px solid #f0b3ae;}
  .swatch{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:4px;vertical-align:middle;}
  #detail{font-size:12px;line-height:1.6;}
  .badge{background:#fff3cd;border:1px solid #e0b400;border-radius:6px;padding:8px 12px;margin:6px 0;font-size:13px;}
  .badge.ok{background:#e6f7e6;border-color:#2e9e44;}
  .plan-box{background:#fff;border:1px solid #ddd;border-radius:8px;padding:10px;}
  #suite-plan{width:100%;height:auto;display:block;}
  #suite-plan polygon{cursor:pointer;}
  #suite-plan polygon:hover{stroke:#000;stroke-width:2.5;filter:brightness(1.05);}
  .legend{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;font-size:13px;}
  .sw{display:inline-flex;align-items:center;gap:5px;background:#fff;border:1px solid #ddd;border-radius:6px;padding:4px 8px;}
  .chip{display:inline-block;width:14px;height:14px;border-radius:3px;border:1px solid #333;}
  .chip.public{background:repeating-linear-gradient(45deg,#e5e7eb,#e5e7eb 4px,#d4d6d8 4px,#d4d6d8 8px);}
  .members .m{display:inline-block;background:#f2f4f7;border-radius:10px;padding:1px 8px;margin:2px 3px;font-size:12px;}
  .members .m i{color:#667;font-style:normal;}
  .members .m em{color:#888;font-style:normal;font-size:11px;}
  tr.un td{background:#fafafa;}
  #tooltip{position:fixed;display:none;background:rgba(30,30,30,.92);color:#fff;border-radius:6px;padding:8px 10px;font-size:12px;pointer-events:none;z-index:99;line-height:1.5;}
  .png{max-width:100%;border:1px solid #ddd;border-radius:8px;}
</style>
</head>
<body>
  <h1>知识图谱浏览器 — __TITLE__</h1>
  <div class="meta">富化方式：__LLM_NOTE__ ｜ 三个视图：全图 / 富化过程 / 套型从属。</div>

  <div class="tabs">
    <button data-v="v-graph" class="active">全图 Knowledge Graph</button>
    <button data-v="v-stage">富化过程 Stages</button>
    <button data-v="v-suite">套型从属 Suite</button>
  </div>

  <div class="view active" id="v-graph">
    <div class="bar">
      阶段：<select id="stage-sel"></select>
      <button class="nav" data-g="0">上一步</button>
      <button class="nav" data-g="1">下一步</button>
    </div>
    <div id="net"></div>
    <div class="panel">
      <div class="card"><h3>节点统计</h3><table id="node-stats"></table></div>
      <div class="card"><h3>边统计</h3><table id="edge-stats"></table></div>
      <div class="card"><h3>节点详情</h3><div id="detail">点击图中节点查看。</div></div>
    </div>
    <div class="meta" style="margin-top:10px">边类型过滤：
      <label><input type="checkbox" data-et="bot:adjacentZone" checked> 邻接</label>
      <label><input type="checkbox" data-et="bot:containsElement" checked> 包含</label>
      <label><input type="checkbox" data-et="bot:interfaceOf" checked> 接口</label>
      <label><input type="checkbox" data-et="bot:hasSpace" checked> 从属</label>
      <label><input type="checkbox" data-et="bot:hasSubZone" checked> 子区</label>
    </div>
  </div>

  <div class="view" id="v-stage">
    <div class="bar" id="stepbar"></div>
    <div id="net2"></div>
    <div class="panel">
      <div class="card"><h3>节点统计</h3><table id="node-stats2"></table></div>
      <div class="card"><h3>边统计</h3><table id="edge-stats2"></table></div>
      <div class="card"><h3>本步 vs 上一步</h3><div id="diff"></div></div>
    </div>
  </div>

  <div class="view" id="v-suite">
    <div id="suite-root"></div>
  </div>

  <div id="tooltip"></div>
<script>
  const STEPS = __STEPS_JSON__;
  const GROUP_COLORS = __GROUP_COLORS__;
  const SUITE = __SUITE_JSON__;
  const EDGE_META = {
    'bot:adjacentZone':{color:'#9AA5B1',dashes:false},'bot:containsElement':{color:'#7FB3E0',dashes:false},
    'bot:interfaceOf':{color:'#E67E22',dashes:false},'bot:hasSpace':{color:'#8E44AD',dashes:true},
    'bot:hasSubZone':{color:'#8E44AD',dashes:true}
  };
  let network=null, cur=0;

  function mkNodes(i, withDiff){
    const st=STEPS[i], prev=i>0?STEPS[i-1]:null;
    const prevMap=prev?new Map(prev.nodes.map(n=>[n.id,n])):new Map();
    const nodes=st.nodes.map(n=>({...n,borderWidth:0}));
    if(withDiff&&st.diff){st.diff.removed_nodes.forEach(id=>{
      const m=prevMap.get(id);
      nodes.push({id,label:(id.split(':')[1]),group:'removed',
        color:{background:'#FBE2E2',border:'#C0392B'},shape:'box'});});}
    const edges=st.edges.filter(e=>{
      const cb=document.querySelector('#v-graph input[data-et="'+e.type+'"]');
      return !cb||cb.checked;
    }).map(e=>{
      const m=EDGE_META[e.type]||{color:'#888',dashes:false};
      const added=withDiff&&st.diff&&st.diff.added_edges.some(x=>x[0]===e.from&&x[1]===e.to);
      return {from:e.from,to:e.to,color:added?'#2e9e44':m.color,dashes:m.dashes,
              arrows:{to:{enabled:false}},width:added?2.5:1};
    });
    return {data:{nodes:new vis.DataSet(nodes),edges:new vis.DataSet(edges)},stats:st.stats,diff:st.diff};
  }

  function render(containerId, i, withDiff){
    const st=STEPS[i], r=mkNodes(i,withDiff);
    if(network)network.destroy();
    const opts={
      groups:Object.assign(Object.fromEntries(Object.entries(GROUP_COLORS).map(([g,c])=>[g,{color:{background:c,border:'#555'}}])),
        {removed:{color:{background:'#FBE2E2',border:'#C0392B'},shape:'box',font:{color:'#B3261E'}}}),
      physics:{barnesHut:{gravitationalConstant:-8000,springLength:140,springConstant:0.04}},
      nodes:{font:{size:12},shape:'dot',size:14,borderWidth:1},
      edges:{smooth:false},interaction:{hover:true,tooltipDelay:120}
    };
    network=new vis.Network(document.getElementById(containerId),r.data,opts);
    const suff=containerId==='net2'?'2':'';
    fillStats('node-stats'+suff,r.stats.nodes_by_group,GROUP_COLORS);
    fillStats('edge-stats'+suff,r.stats.edges_by_type,Object.fromEntries(Object.entries(EDGE_META).map(([k,v])=>[k,v.color])));
    const dEl=document.getElementById('diff');
    if(dEl)dEl.innerHTML=diffHtml(r.diff);
    const det=document.getElementById('detail');
    network.on('click',p=>{if(p.nodes.length){
      const id=p.nodes[0];const node=st.nodes.find(n=>n.id===id);
      if(det)det.textContent=node?(node.id+'  [组:'+node.group+']'):('(已移除节点) '+id);}});
  }

  function fillStats(tid,obj,colors){
    const t=document.getElementById(tid);const ks=Object.keys(obj).sort();
    t.innerHTML=ks.length?ks.map(k=>'<tr><td><span class="swatch" style="background:'+(colors[k]||'#ccc')+'"></span>'+k+'</td><td>'+obj[k]+'</td></tr>').join(''):'<tr><td colspan="2">—</td></tr>';
  }
  function diffHtml(d){
    if(!d)return '<div class="meta">（起始阶段）</div>';
    let p='<span class="badge b-add">+'+d.added_nodes.length+' 节点</span>'
       + '<span class="badge b-del">-'+d.removed_nodes.length+' 节点</span>'
       + '<span class="badge b-add">+'+d.added_edges.length+' 边</span>'
       + '<span class="badge b-del">-'+d.removed_edges.length+' 边</span>';
    if(d.added_nodes.length)p+='<div style="margin-top:6px;color:#1e7e34">新增：'+d.added_nodes.slice(0,12).join('、')+(d.added_nodes.length>12?' …':'')+'</div>';
    if(d.removed_nodes.length)p+='<div style="color:#b3261e">移除：'+d.removed_nodes.slice(0,12).join('、')+(d.removed_nodes.length>12?' …':'')+'</div>';
    return p;
  }

  // 全图视图
  const sel=document.getElementById('stage-sel');
  STEPS.forEach((s,i)=>{const o=document.createElement('option');o.value=i;o.textContent=s.label+' ('+s.stats.total_nodes+'n/'+s.stats.total_edges+'e)';sel.appendChild(o);});
  sel.onchange=()=>{cur=+sel.value;render('net',cur,false);};
  document.querySelectorAll('#v-graph .nav').forEach(b=>b.onclick=()=>{cur=Math.max(0,Math.min(STEPS.length-1,cur+(+b.dataset.g*2-1)));sel.value=cur;render('net',cur,false);});
  document.querySelectorAll('#v-graph input[data-et]').forEach(cb=>cb.onchange=()=>render('net',cur,false));

  // 富化过程视图
  const bar=document.getElementById('stepbar');
  STEPS.forEach((s,i)=>{const b=document.createElement('button');b.textContent=s.label+' ('+s.stats.total_nodes+'n/'+s.stats.total_edges+'e)';b.onclick=()=>{cur=i;render('net2',i,true);[...bar.children].forEach((x,k)=>x.classList.toggle('active',k===i));};bar.appendChild(b);});
  const pB=document.createElement('button');pB.className='nav';pB.textContent='← 上一步';
  pB.onclick=()=>{cur=Math.max(0,cur-1);bar.children[cur].click();};
  const nB=document.createElement('button');nB.className='nav';nB.textContent='下一步 →';
  nB.onclick=()=>{cur=Math.min(STEPS.length-1,cur+1);bar.children[cur].click();};
  bar.appendChild(pB);bar.appendChild(nB);

  // 套型视图
  (function(){
    const root=document.getElementById('suite-root');
    const meta='文件：<code>'+SUITE.base+'</code> ｜ Suite：<b>'+SUITE.found+'</b>'
      +(SUITE.expected!=null?' ｜ 预期：<b>'+SUITE.expected+'</b>':'')+' ｜ 空间：'+SUITE.total_spaces;
    let h='<div class="meta">'+meta+'</div>'+SUITE.badges;
    h+='<div class="plan-box">'+SUITE.svg+'</div><div class="legend">'+SUITE.legend+'</div>';
    if(SUITE.png_b64)h+='<h2>平面图（按套型着色）</h2><img class="png" src="data:image/png;base64,'+SUITE.png_b64+'"/>';
    h+='<h2>从属关系明细（Suite → Spaces）</h2><table><thead><tr><th>Suite</th><th>数量</th><th>成员空间（ID · 类型 · 面积）</th></tr></thead><tbody>'+SUITE.rows+'</tbody></table>';
    root.innerHTML=h;
    const tip=document.getElementById('tooltip'),plan=document.getElementById('suite-plan');
    if(plan){const map={};plan.querySelectorAll('polygon').forEach(p=>{(map[p.dataset.space]=map[p.dataset.space]||[]).push(p);});
      plan.querySelectorAll('polygon').forEach(p=>{
        p.addEventListener('mousemove',e=>{tip.style.display='block';tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';
          tip.innerHTML='<b>'+p.dataset.space+'</b><br>类型：'+p.dataset.type+'<br>面积：'+p.dataset.area+'<br>所属：<b>'+p.dataset.suite+'</b>';
          (map[p.dataset.space]||[]).forEach(q=>q.setAttribute('stroke-width',3));});
        p.addEventListener('mouseleave',()=>{tip.style.display='none';plan.querySelectorAll('polygon').forEach(q=>q.setAttribute('stroke-width',1.2));});
      });}
  })();

  // tabs
  document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('.tabs button').forEach(x=>x.classList.remove('active'));
    document.querySelectorAll('.view').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');document.getElementById(b.dataset.v).classList.add('active');
    if(b.dataset.v==='v-graph')render('net',cur,false);
    if(b.dataset.v==='v-stage'){bar.children[Math.min(cur,STEPS.length-1)].click();}
  });

  render('net',0,false);
  bar.children[0]&&bar.children[0].click();
</script>
</body>
</html>"""


# --------------------------- CLI --------------------------- #
def process_one(base, raw_path, svg_path, out_dir, use_llm,
                final_path=None, suffix="", replay=True):
    """
    Generate one ``<base><suffix>_kg_browser.html`` (and suite PNG).

    Args:
        raw_path:  raw JSON-LD (used for the 富化过程 stage replay). None to skip.
        svg_path:  SVG used to extract room texts during replay.
        final_path: explicit final JSON-LD to render (e.g. a GT file). When
            replay is disabled this is the source of the 全图/套型 views.
        suffix:    extra filename suffix, e.g. ``_gt`` or ``_stages``.
        replay:    if False, skip the pipeline replay and render only the stored
            final graph (fast; 富化过程 tab shows a single 最终图谱 stage).
    """
    if replay and raw_path and os.path.exists(raw_path):
        raw_graph = load_jsonld(raw_path)
        stages, llm_used = run_pipeline_stages(raw_graph, svg_path, use_llm)
    else:
        fp = Path(final_path) if final_path else (settings.jsonld_dir / f"{base}.jsonld")
        if not fp.exists():
            print(f"⚠️ final jsonld not found: {fp}")
            return False
        stages = [{"stage": "final", "graph": load_jsonld(fp)}]
        llm_used = False

    stage_data = build_stage_data(stages)
    final_graph = stages[-1]["graph"]

    png = Path(out_dir) / f"{base}{suffix}_suites.png"
    ms = extract_membership(final_graph)
    expected = infer_expected_suites(base)
    if ms["suites"]:
        draw_suite_png(ms, png, base_name=base, expected=expected)
    sctx = suite_context(final_graph, base, expected, png_path=str(png))

    build_html(base, stage_data, sctx, llm_used,
               Path(out_dir) / f"{base}{suffix}_kg_browser.html")
    print(f"📊 {base}: {len(ms['suites'])} suites / {len(ms['space_map'])} spaces "
          f"/ {len(stage_data)} stages")
    return True


def main():
    p = argparse.ArgumentParser(description="Knowledge graph browser (multi-view) for JSON-LD")
    p.add_argument("--input", help="raw or final JSON-LD path")
    p.add_argument("--base", help="base name, e.g. '2suite (1)'")
    p.add_argument("--svg", help="SVG path for room texts (auto from --base)")
    p.add_argument("--mode", choices=["SINGLE", "BATCH"], default="SINGLE")
    p.add_argument("--out-dir", default=str(settings.viz_dir))
    p.add_argument("--llm", dest="use_llm", action="store_true", default=None)
    p.add_argument("--no-llm", dest="use_llm", action="store_false")
    p.add_argument("--final-only", action="store_true",
                   help="Skip pipeline replay; render only the stored final JSON-LD (fast)")
    p.add_argument("--final", default=None, help="Explicit final JSON-LD path (e.g. a GT file)")
    p.add_argument("--suffix", default="", help="Extra filename suffix, e.g. _gt or _stages")
    p.set_defaults(use_llm=None)
    args = p.parse_args()

    if args.use_llm is None:
        args.use_llm = args.mode == "SINGLE" and bool(settings.llm_api_key)
    replay = not args.final_only

    if args.mode == "BATCH" or (not args.input and not args.base):
        finals = sorted(q for q in settings.jsonld_dir.glob("*.jsonld") if "_raw" not in q.name)
        if not finals:
            print("🛑 No enriched JSON-LD files found under output/jsonld")
            sys.exit(1)
        ok = 0
        for f in finals:
            base = f.name[:-len(".jsonld")]
            raw = settings.jsonld_dir / f"{base}_raw.jsonld"
            svg = settings.svg_dir / f"{base}.svg"
            if process_one(base, raw, str(svg) if svg.exists() else None, args.out_dir,
                           args.use_llm, final_path=args.final, suffix=args.suffix, replay=replay):
                ok += 1
        print(f"★ Done: {ok}/{len(finals)} browsers → {args.out_dir}")
    else:
        base, raw_path, svg_path = args.base, None, args.svg
        if args.input:
            raw_input = Path(args.input)
            raw_path = raw_input if raw_input.is_absolute() else settings.resolve_project_path(str(raw_input))
            if not base:
                base = raw_input.stem.replace("_raw", "")
        elif base:
            raw_path = settings.jsonld_dir / f"{base}_raw.jsonld"
        if not svg_path and base:
            cand = settings.svg_dir / f"{base}.svg"
            if cand.exists():
                svg_path = str(cand)
        if not raw_path:
            print("🛑 Need --base or --input")
            sys.exit(1)
        process_one(base, raw_path, svg_path, args.out_dir, args.use_llm,
                    final_path=args.final, suffix=args.suffix, replay=replay)


if __name__ == "__main__":
    main()
