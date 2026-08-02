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
