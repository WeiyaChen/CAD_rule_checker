/* ============================================================
 * ui_common.js — Shared UI helpers for CAD Rule Checker pages
 *
 * Provides:
 *   - enableImageZoom(img)  : wheel zoom + drag pan + control bar
 *   - Auto-enables zoom for every <img class="zoomable">
 *
 * Usage:
 *   <img class="zoomable hidden" ...>   (zoom container auto-wraps)
 *   <script src="ui_common.js"></script>
 * Hide/show images via the `.hidden` class (see page CSS):
 *   .hidden { display: none !important; }
 * ============================================================ */
(function () {
  'use strict';

  function buildBar() {
    const bar = document.createElement('div');
    bar.className = 'zoom-bar';
    Object.assign(bar.style, {
      position: 'absolute', top: '8px', right: '8px', zIndex: 20,
      display: 'flex', alignItems: 'center', gap: '2px',
      background: 'rgba(15,60,100,.85)', color: '#fff', borderRadius: '8px',
      padding: '2px', fontFamily: 'inherit', userSelect: 'none'
    });
    const mk = (text, act, title) => {
      const b = document.createElement('button');
      b.textContent = text; b.title = title; b.dataset.act = act;
      Object.assign(b.style, {
        background: 'transparent', border: '0', color: '#fff', fontSize: '15px',
        cursor: 'pointer', padding: '2px 8px', lineHeight: '1', borderRadius: '6px'
      });
      return b;
    };
    const pct = document.createElement('span');
    pct.className = 'zoom-pct';
    Object.assign(pct.style, { fontSize: '11px', minWidth: '42px', textAlign: 'center' });
    bar.append(mk('+', 'in', 'Zoom in'), mk('−', 'out', 'Zoom out'), mk('⟲', 'reset', 'Reset zoom'), pct);
    return { bar, pct };
  }

  window.enableImageZoom = function (img) {
    if (!img || img.dataset.zoomReady) return;
    img.dataset.zoomReady = '1';

    // wrap the image in a dedicated zoom container (keeps the image in flow)
    const box = document.createElement('div');
    box.className = 'zoom-box';
    Object.assign(box.style, {
      position: 'relative', overflow: 'hidden', borderRadius: '8px',
      border: '1px solid #dde3ec', background: '#fff', touchAction: 'none'
    });
    img.parentElement.insertBefore(box, img);
    box.appendChild(img);
    Object.assign(img.style, {
      display: 'block', width: '100%', height: 'auto', margin: '0',
      cursor: 'grab', transformOrigin: '0 0'
    });

    const { bar, pct } = buildBar();
    box.appendChild(bar);

    let scale = 1, tx = 0, ty = 0;
    let dragging = false, sx = 0, sy = 0, stx = 0, sty = 0;

    function render() {
      img.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
      pct.textContent = Math.round(scale * 100) + '%';
    }
    function reset() { scale = 1; tx = 0; ty = 0; render(); }
    function zoomAt(cx, cy, factor) {
      const ns = Math.min(20, Math.max(0.5, scale * factor));
      const bx = (cx - tx) / scale, by = (cy - ty) / scale;
      scale = ns; tx = cx - bx * scale; ty = cy - by * scale;
      render();
    }

    box.addEventListener('wheel', function (e) {
      e.preventDefault();
      const r = box.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.15 : 1 / 1.15);
    }, { passive: false });

    box.addEventListener('mousedown', function (e) {
      if (e.target.closest('.zoom-bar')) return;
      dragging = true; sx = e.clientX; sy = e.clientY; stx = tx; sty = ty;
      box.style.cursor = 'grabbing'; e.preventDefault();
    });
    window.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      tx = stx + (e.clientX - sx); ty = sty + (e.clientY - sy); render();
    });
    window.addEventListener('mouseup', function () {
      if (dragging) { dragging = false; box.style.cursor = 'grab'; }
    });
    box.addEventListener('dblclick', reset);

    bar.querySelector('[data-act=in]').onclick = function () { zoomAt(box.clientWidth / 2, box.clientHeight / 2, 1.25); };
    bar.querySelector('[data-act=out]').onclick = function () { zoomAt(box.clientWidth / 2, box.clientHeight / 2, 1 / 1.25); };
    bar.querySelector('[data-act=reset]').onclick = reset;
    render();
  };

  function scan() {
    document.querySelectorAll('img.zoomable').forEach(function (img) {
      if (!img.dataset.zoomReady) enableImageZoom(img);
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', scan);
  } else {
    scan();
  }
  // re-scan periodically so images added after results arrive get zoom too
  setInterval(scan, 1200);
})();

/* ============================================================
 * Spatial algorithm selector (空间轮廓提取 / 空间类型识别)
 *
 * Usage:
 *   <div id="algoSlot"></div>
 *   <script src="ui_common.js"></script>
 *   <script>
 *     mountSpatialAlgos('algoSlot');                       // 运行前选择算法
 *     fetch(url, {body: JSON.stringify({...getSpatialAlgoSelection()})})
 *       .then(r => r.json()).then(d => setSpatialAlgoStatus(d));
 *   </script>
 * ============================================================ */
(function () {
  'use strict';

  const STYLE_ID = 'spatial-algo-style';
  const state = { catalog: null, defaults: null };

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      '.algo-panel { font-family: inherit; font-size: 13px; color: #33475b; }',
      '.algo-panel .algo-title { font-weight: 600; margin-bottom: 8px; color: #2c3e50; }',
      '.algo-panel .algo-row { display: block; margin-bottom: 8px; }',
      '.algo-panel .algo-label { display: block; color: #5a6b80; font-size: 12px; margin-bottom: 3px; }',
      '.algo-panel select { width: 100%; padding: 5px 6px; font: inherit; font-size: 13px;',
      '  color: #33475b; background: #fff; border: 1px solid #cdd8e5; border-radius: 6px; }',
      '.algo-panel .algo-force { display: flex; align-items: center; gap: 6px;',
      '  color: #5a6b80; font-size: 12px; margin: 10px 0 0; cursor: pointer; }',
      '.algo-panel .algo-hint { color: #7a8aa0; font-size: 11.5px; line-height: 1.5; margin-top: 8px; }',
      '.algo-panel .algo-warn { color: #b06a00; font-size: 11.5px; line-height: 1.5; margin-top: 6px; }',
      '.algo-panel .algo-status { display: none; margin-top: 10px; padding: 7px 9px; border-radius: 6px;',
      '  background: #eef4fb; border: 1px solid #d6e4f3; color: #33556f; font-size: 11.5px; line-height: 1.5; }',
      '.algo-panel .algo-status.shown { display: block; }'
    ].join('\n');
    document.head.appendChild(style);
  }

  function optionText(algo) {
    return algo.name + (algo.default ? '（默认）' : '');
  }

  function fillSelect(select, task) {
    select.textContent = '';
    task.algorithms.forEach(function (algo) {
      const opt = document.createElement('option');
      opt.value = algo.id;
      opt.textContent = optionText(algo);
      if (algo.summary) opt.title = algo.summary;
      select.appendChild(opt);
    });
    select.value = state.defaults[select.dataset.task] || task.default;
  }

  window.mountSpatialAlgos = function (containerId, options) {
    const opts = options || {};
    const host = document.getElementById(containerId);
    if (!host) return;
    host.textContent = 'Loading algorithms…';
    fetch('/api/spatial-algos')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data || !data.ok) throw new Error((data && data.error) || 'failed');
        state.catalog = data;
        state.defaults = {
          contour: data.contour.default,
          classification: data.classification.default
        };
        render(host, data, opts);
      })
      .catch(function (e) {
        host.textContent = 'Algorithm list unavailable: ' + e.message;
      });
  };

  function render(host, data, opts) {
    ensureStyle();
    host.textContent = '';
    const panel = document.createElement('div');
    panel.className = 'algo-panel';

    if (opts.title !== false) {
      const title = document.createElement('div');
      title.className = 'algo-title';
      title.textContent = opts.title || '空间算法 (Spatial Algorithms)';
      panel.appendChild(title);
    }

    [['contour', '空间轮廓提取'], ['classification', '空间类型识别']].forEach(function (pair) {
      const key = pair[0], task = data[key];
      if (!task || !task.algorithms || !task.algorithms.length) return;
      const row = document.createElement('label');
      row.className = 'algo-row';
      const label = document.createElement('span');
      label.className = 'algo-label';
      label.textContent = task.label || pair[1];
      const select = document.createElement('select');
      select.className = 'algo-select';
      select.dataset.task = key;
      row.append(label, select);
      panel.appendChild(row);
      fillSelect(select, task);
      select.addEventListener('change', function () {
        state.defaults[key] = select.value;
      });
    });

    if (opts.showForce !== false) {
      const force = document.createElement('label');
      force.className = 'algo-force';
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.className = 'algo-force-box';
      const text = document.createElement('span');
      text.textContent = '忽略缓存，强制重新解析';
      force.append(box, text);
      panel.appendChild(force);
    }

    const llm = data.llm || {};
    if (!llm.enabled) {
      const warn = document.createElement('div');
      warn.className = 'algo-warn';
      warn.textContent = '⚠ 未检测到 LLM API Key：空间类型识别可能无类别输出（套间从属关系也会退化）。';
      panel.appendChild(warn);
    }
    const hint = document.createElement('div');
    hint.className = 'algo-hint';
    hint.textContent = 'LLM: ' + (llm.enabled ? ('已启用 · ' + (llm.model || '')) : '未启用');
    panel.appendChild(hint);

    const status = document.createElement('div');
    status.className = 'algo-status';
    panel.appendChild(status);

    host.appendChild(panel);
  }

  window.getSpatialAlgoSelection = function () {
    const pick = function (task, fallback) {
      const el = document.querySelector('.algo-select[data-task="' + task + '"]');
      return (el && el.value) || fallback || null;
    };
    const box = document.querySelector('.algo-force-box');
    const defaults = state.defaults || {};
    return {
      contourAlgo: pick('contour', defaults.contour),
      classifierAlgo: pick('classification', defaults.classification),
      forceReparse: !!(box && box.checked)
    };
  };

  window.setSpatialAlgoStatus = function (info) {
    const el = document.querySelector('.algo-status');
    if (!el) return;
    const text = typeof info === 'string' ? info : statusText(info);
    if (!text) return;
    el.textContent = text;
    el.classList.add('shown');
  };

  function statusText(d) {
    if (!d || !d.contourAlgo) return '';
    const bits = ['轮廓 ' + d.contourAlgo, '分类 ' + d.classifierAlgo];
    if (d.reused !== undefined) bits.push(d.reused ? '复用缓存' : '本次重新解析');
    bits.push(d.llmEnabled ? ('LLM ' + (d.llmModel || '已启用')) : 'LLM 未启用');
    return '当前展示结果：' + bits.join(' · ');
  }
})();
