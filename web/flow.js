// Screening flow: the slit-beam scan, the verdict and the Grad-CAM readout for one screening.
import { api, summarize, esc, eyeWord, pct, pct0, reducedMotion, COLORS, DISEASES } from './util.js';
import { lensSVG, lensPhotoStyle } from './lens.js';
import { setTitle } from './app.js';

const T = { up: 700, scanEnd: 3700, move: 900, verdict: 4400, ov0: 4600, ov1: 5400, ld0: 5200, ld: 700, settle: 6600, settleDur: 800, read0: 6800, end: 7600 };
const clamp = (x) => Math.max(0, Math.min(1, x));
const ease = (x) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const sine = (x) => -(Math.cos(Math.PI * clamp(x)) - 1) / 2;

function validGrid(g) {
  return Array.isArray(g) && g.length >= 4 && g.every((r) => Array.isArray(r) && r.length === g.length && r.every((v) => typeof v === 'number' && isFinite(v) && v >= 0 && v <= 1)) && g.some((r) => r.some((v) => v > 0));
}

// The two heaviest connected regions (cells >= 0.5) and their share of the map's weight.
function regionsOf(grid) {
  const n = grid.length, seen = grid.map((r) => r.map(() => false));
  let total = 0;
  grid.forEach((r) => r.forEach((v) => { total += v; }));
  const comps = [];
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    if (seen[i][j] || grid[i][j] < 0.5) continue;
    let m = 0, sx = 0, sy = 0; const q = [[i, j]]; seen[i][j] = true;
    while (q.length) {
      const [y, x] = q.pop(), v = grid[y][x]; m += v; sx += (x + 0.5) * v; sy += (y + 0.5) * v;
      [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dy, dx]) => {
        const yy = y + dy, xx = x + dx;
        if (yy >= 0 && yy < n && xx >= 0 && xx < n && !seen[yy][xx] && grid[yy][xx] >= 0.5) { seen[yy][xx] = true; q.push([yy, xx]); }
      });
    }
    comps.push({ m, cx: sx / m, cy: sy / m });
  }
  return comps.sort((a, b) => b.m - a.m).slice(0, 2).map((c) => ({ ...c, share: total > 0 ? c.m / total : 0 }));
}

function overlaySVG(grid, primary, t, lensSize, narrow) {
  const { V, INK, MUTE } = COLORS, px = 92, pd = 256;
  const n = grid.length, cell = pd / n, ovOp = ease((t - T.ov0) / (T.ov1 - T.ov0));
  const cells = [];
  grid.forEach((r, i) => r.forEach((v, j) => {
    if (v >= 0.25) cells.push(`<rect x="${(px + j * cell).toFixed(2)}" y="${(px + i * cell).toFixed(2)}" width="${(cell + 0.6).toFixed(2)}" height="${(cell + 0.6).toFixed(2)}" fill="${V}" fill-opacity="${(0.1 + 0.42 * (v - 0.25) / 0.75).toFixed(3)}"/>`);
  }));
  const regs = regionsOf(grid).map((r) => ({ ...r, x: px + r.cx * cell, y: px + r.cy * cell }));
  const ordered = regs.slice().sort((a, b) => a.y - b.y);
  const slots = ordered.length === 1 ? [Math.max(110, Math.min(330, ordered[0].y))] : [150, 300];
  const leaders = ordered.map((r, idx) => {
    const rank = regs.indexOf(r), p = ease((t - T.ld0 - rank * 250) / T.ld), ly = slots[idx];
    const out = [`<circle cx="${r.x}" cy="${r.y}" r="8" fill="none" stroke="#F3EFE6" stroke-width="3" opacity="${p}"/>`,
      `<circle cx="${r.x}" cy="${r.y}" r="8" fill="none" stroke="${INK}" stroke-width="1.2" opacity="${p}"/>`];
    if (narrow) {
      out.push(`<text x="${r.x + 12}" y="${r.y - 10}" font-family="IBM Plex Mono, monospace" font-size="13" font-weight="600" fill="#F3EFE6" stroke="${INK}" stroke-width="3" paint-order="stroke" opacity="${p}">${rank + 1}</text>`);
      return out.join('');
    }
    const Ax = -28, Bx = 22, dxl = r.x - Bx, dyl = r.y - ly, dl = Math.hypot(dxl, dyl) || 1, ux = dxl / dl, uy = dyl / dl;
    const tipX = r.x - ux * 10, tipY = r.y - uy * 10;
    const d = `M${Ax} ${ly}L${Bx} ${ly}L${tipX.toFixed(1)} ${tipY.toFixed(1)}`;
    const len = (Bx - Ax) + Math.hypot(tipX - Bx, tipY - ly);
    const ah = `M${tipX.toFixed(1)} ${tipY.toFixed(1)}L${(tipX - ux * 9 - uy * 4).toFixed(1)} ${(tipY - uy * 9 + ux * 4).toFixed(1)}L${(tipX - ux * 9 + uy * 4).toFixed(1)} ${(tipY - uy * 9 - ux * 4).toFixed(1)}Z`;
    const dash = `stroke-dasharray="${len.toFixed(1)}" stroke-dashoffset="${(len * (1 - p)).toFixed(1)}"`;
    const lab = clamp((p - 0.55) / 0.45);
    out.push(`<path d="${d}" fill="none" stroke="#F3EFE6" stroke-width="3.2" ${dash}/>`,
      `<path d="${d}" fill="none" stroke="${INK}" stroke-width="1.1" ${dash}/>`,
      `<path d="${ah}" fill="${INK}" stroke="#F3EFE6" stroke-width="0.8" opacity="${p >= 0.98 ? 1 : 0}"/>`,
      `<text x="-36" y="${ly - 4}" text-anchor="end" font-family="Instrument Sans, sans-serif" font-size="12.5" font-weight="600" fill="${INK}" opacity="${lab}">${rank === 0 ? 'Strongest Grad-CAM region' : 'Second Grad-CAM region'}</text>`,
      `<text x="-36" y="${ly + 12}" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="9.5" letter-spacing="0.6" fill="${MUTE}" opacity="${lab}">${esc(primary.toUpperCase())} · ${Math.round(r.share * 100)}% OF MAP WEIGHT</text>`);
    return out.join('');
  });
  const svg = `<svg viewBox="0 0 440 440" width="${lensSize}" height="${lensSize}" aria-hidden="true" style="position:absolute;inset:0;overflow:visible;pointer-events:none">
    <defs><clipPath id="sfclip"><circle cx="220" cy="220" r="128"/></clipPath>
    <filter id="sfsoft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="${(cell * 0.8).toFixed(1)}"/></filter></defs>
    <g clip-path="url(#sfclip)" opacity="${ovOp}"><g filter="url(#sfsoft)">${cells.join('')}</g></g>${leaders.join('')}</svg>`;
  const rows = regs.map((r, i) => ({ n: String(i + 1), label: i === 0 ? 'Strongest region' : 'Second region', share: Math.round(r.share * 100) + '% of weight' }));
  return { svg, rows };
}

export async function renderFlow(view, { id, isCurrent }) {
  const rec = await api('/screenings/' + encodeURIComponent(id));
  if (!isCurrent()) return null;
  const s = summarize(rec);
  const names = DISEASES, vals = s.vals, ths = s.ths, pos = s.rows.map((r) => r.positive);
  const posNames = names.filter((_, i) => pos[i]);
  const primary = s.primary ? s.primary.disease : null;
  const best = s.primary ? s.primary.probability : 0;
  const photo = `/api/screenings/${encodeURIComponent(rec.id)}/image`;
  const imgSize = rec.model.img_size;
  setTitle(`${rec.ref}, ${eyeWord(rec.eye)} eye`);

  let kind = 'none', grid = null, reason = '', layer = '';
  if (primary) {
    const m = (rec.maps || []).find((x) => x.disease === primary);
    if (!m) reason = 'The result has no map for ' + primary + '.';
    else if (m.available === false) reason = 'Grad-CAM returned an empty map for ' + primary + '.';
    else if (!validGrid(m.grid)) reason = 'The map failed validation (expected a square grid of values from 0 to 1).';
    else { grid = m.grid; layer = m.layer || ''; }
    kind = grid ? 'map' : 'fallback';
  }

  view.innerHTML = `<main id="main" style="display:flex;flex-direction:column">
    <header class="page-head">
      <div class="titles"><span class="eyebrow" id="fl-eyebrow"></span><h1 id="fl-title"></h1></div>
      <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
        <button type="button" class="btn" id="replay" style="font-size:11.5px"><span aria-hidden="true" class="mono">↺</span>Replay</button>
      </div>
    </header>
    <p class="sr-only" aria-live="polite" id="fl-live"></p>
    <div class="flow-main">
      <div class="stage" id="stage">
        <div class="lens-col" id="lens-col">
          <div class="lens-box" id="lens-box" role="img">
            <img alt="" id="photo" src="${photo}">
            <div class="layer" id="lens-layer"></div>
            <div class="layer" id="ov-layer" style="overflow:visible"></div>
          </div>
          <div class="verdict" id="verdict"></div>
        </div>
        <div class="log-col" id="log-col">
          <div class="tag">
            <div class="tag-head"><span>SPECIMEN TAG</span><span class="mute">MODEL OUTPUT</span></div>
            <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap"><span class="mono" style="font:600 30px/1 var(--mono)">${esc(rec.ref)}</span>${eyeDots(rec.eye)}<span class="mono mute" style="margin-left:auto;font-size:11px;overflow-wrap:anywhere">${esc(rec.image.name)}</span></div>
          </div>
          <div class="log" id="log"></div>
        </div>
        <div class="read-col" id="read-col"></div>
      </div>
    </div></main>`;

  const $ = (sel) => view.querySelector(sel);
  const stage = $('#stage'), lensCol = $('#lens-col'), lensBox = $('#lens-box'), photoEl = $('#photo');
  const el = { eyebrow: $('#fl-eyebrow'), title: $('#fl-title'), live: $('#fl-live'), lens: $('#lens-layer'), ov: $('#ov-layer'), verdict: $('#verdict'), log: $('#log'), read: $('#read-col'), logCol: $('#log-col') };
  const last = {};
  const put = (key, node, html, prop = 'innerHTML') => { if (last[key] !== html) { last[key] = html; node[prop] = html; } };

  let t = -1, raf = 0, dx = null, narrow = stage.clientWidth < 1100;
  const ro = window.ResizeObserver ? new ResizeObserver(([e]) => { const nw = e.contentRect.width < 1100; if (nw !== narrow) { narrow = nw; frame(); } }) : null;
  if (ro) ro.observe(stage);

  function measure() {
    if (narrow) { dx = 0; return; }
    const a = stage.getBoundingClientRect(), b = lensCol.getBoundingClientRect();
    dx = (a.left + a.width / 2) - (b.left + b.width / 2);
  }

  const eyeW = eyeWord(rec.eye);
  const rows = names.map((n, i) => ({ name: n, p: pct(vals[i]), t: pct0(ths[i]), res: pos[i] ? '▲ POSITIVE' : '○ NOT DETECTED', cls: pos[i] ? 'c-pos' : 'c-clr' }));
  const verdict = posNames.length ? 'Possible: ' + posNames.join(', ') + '.' : 'Not detected.';
  const verdictSub = posNames.length
    ? `${posNames.length} OF 4 PAST THRESHOLD · ${primary.toUpperCase()} ${pct(best)} vs ${pct0(ths[names.indexOf(primary)])}`
    : '0 OF 4 PAST THRESHOLD';
  const lensAria = `Lens readout for ${rec.ref}, ${eyeW} eye. ` + names.map((n, i) => `${n} ${pct(vals[i])}, threshold ${pct0(ths[i])}, ${pos[i] ? 'positive' : 'not detected'}`).join('; ') + '.';
  lensBox.setAttribute('aria-label', lensAria);

  function frame() {
    const lensSize = narrow ? Math.min(340, stage.clientWidth) : 520;
    const final = t >= T.settle, idle = t < 0;
    const lrState = idle ? 'empty' : t < T.up ? 'uploading' : t < T.scanEnd ? 'analyzing' : 'readout';
    const reveal = clamp((t - T.up) / 750 / 4) * 4, scan = sine((t - T.up) / (T.scanEnd - T.up));
    const e1 = ease((t - T.scanEnd) / T.move), e2 = ease((t - T.settle) / T.settleDur);
    const shift = narrow ? 0 : (dx || 0);
    const curr = names[Math.min(3, Math.floor(reveal))];

    stage.style.gridTemplateColumns = narrow ? 'minmax(0,1fr)' : final ? 'minmax(0,1fr) 560px minmax(0,1fr)' : '560px minmax(0,1fr)';
    lensCol.style.gridColumn = narrow ? '1' : final ? '2' : '1';
    lensCol.style.transformOrigin = `50% ${lensSize / 2}px`;
    lensCol.style.transform = t < T.scanEnd ? 'none' : !final ? `translateX(${(shift * e1).toFixed(1)}px) scale(${(1 + 0.12 * e1).toFixed(4)})` : `scale(${(1.12 - 0.12 * e2).toFixed(4)})`;
    lensBox.style.width = lensBox.style.height = lensSize + 'px';
    put('photoStyle', photoEl.style, lensPhotoStyle(lensSize) + `;opacity:${idle ? 0 : 1}`, 'cssText');
    put('lens', el.lens, lensSVG({ size: lensSize, state: lrState, values: vals, thresholds: ths, eye: rec.eye, photoUnder: true, reveal: reveal.toFixed(3), scan: scan.toFixed(4), progress: clamp(t / T.up).toFixed(3), labelSize: narrow ? 13 : 10.5 }));

    let regionRows = [];
    if (kind === 'map' && t >= T.ov0) {
      const o = overlaySVG(grid, primary, t, lensSize, narrow);
      put('ov', el.ov, o.svg); regionRows = o.rows;
    } else put('ov', el.ov, '');

    const phase = idle ? 'READY' : t < T.up ? 'PLACING PHOTO' : t < T.scanEnd ? `SLIT BEAM ${Math.round(scan * 100)}% · ${curr.toUpperCase()}` : !final ? 'RESULT' : 'READOUT';
    put('eyebrow', el.eyebrow, 'NEW SCREENING · ' + phase, 'textContent');
    put('title', el.title, (t < T.scanEnd ? 'Analyzing ' : '') + `${rec.ref}, ${eyeW} eye`, 'textContent');
    put('live', el.live, idle ? '' : t < T.up ? 'Photo placed. Uploading.' : t < T.scanEnd ? 'Analyzing ' + curr + '.'
      : 'Analysis complete. ' + (posNames.length ? 'Possible: ' + posNames.join(', ') + '.' : 'Not detected.') + (kind === 'fallback' ? ' Explanation map unavailable.' : ''), 'textContent');

    const vOp = t >= T.scanEnd ? ease((t - T.verdict) / 600) : 0;
    el.verdict.style.opacity = vOp;
    put('verdict', el.verdict, `<div class="verdict-line"><span aria-hidden="true" class="glyph" style="color:${posNames.length ? COLORS.V : COLORS.G}">${posNames.length ? '▲' : '○'}</span><span class="words">${esc(verdict)}</span></div><span class="sub">${esc(verdictSub)}</span>`);

    el.logCol.style.gridColumn = narrow ? '1' : '2';
    el.logCol.style.gridRow = narrow ? '2' : '1';
    el.logCol.style.display = final ? 'none' : 'flex';
    el.logCol.style.opacity = t < T.scanEnd ? 1 : (1 - e1).toFixed(3);
    const done = (i) => reveal - i >= 1, meas = (i) => reveal - i > 0 && reveal - i < 1;
    const log = [
      ['Photo placed', t >= T.up ? '✓' : 'UPLOADING', t >= T.up ? COLORS.INK : COLORS.OT],
      [`crop_fundus → ${imgSize} × ${imgSize}`, t >= T.up ? '✓' : '—', t >= T.up ? COLORS.INK : COLORS.MUTE],
      ...names.map((n, i) => done(i) ? [n, pct(vals[i]) + ' ' + (pos[i] ? '▲ POSSIBLE' : '○ CLEAR'), pos[i] ? COLORS.VT : COLORS.G]
        : meas(i) ? [n, '◐ MEASURING', COLORS.OT] : [n, 'QUEUED', COLORS.MUTE]),
    ];
    put('log', el.log, log.map(([a, b, c]) => `<div style="color:${c}"><span>${esc(a)}</span><b>${b}</b></div>`).join(''));

    el.read.style.gridColumn = narrow ? '1' : '3';
    el.read.style.gridRow = narrow ? '2' : '1';
    el.read.style.justifySelf = narrow ? 'center' : 'end';
    el.read.style.maxWidth = narrow ? '560px' : '420px';
    el.read.style.display = final ? 'flex' : 'none';
    el.read.style.opacity = ease((t - T.read0) / 800);
    let panel = '';
    if (kind === 'map') {
      panel = `<div class="panel" style="border:1px solid var(--ink)"><span class="k c-pos">▲ ATTENTION MAP · GRAD-CAM</span>
        <p>Tinted regions weighed most in the model’s ${esc(primary)} score${layer ? ' (layer ' + esc(layer) + ')' : ''}. They show where the model looked, not a confirmed lesion.</p>
        ${regionRows.map((rg) => `<div class="region"><span style="font-weight:600">${rg.n}</span><span>${rg.label}</span><span>${rg.share}</span></div>`).join('')}</div>`;
    } else if (kind === 'fallback') {
      panel = `<div class="panel" style="border:1px dashed var(--ink)"><span class="k c-rev">◐ EXPLANATION MAP UNAVAILABLE</span>
        <p>No regions are highlighted, because there is no reliable Grad-CAM map for this result. The probabilities above are unaffected.</p><span class="why">${esc(reason)}</span></div>`;
    } else {
      panel = `<div class="panel" style="border:1px solid var(--rule)"><span class="k c-clr">○ NO OVERLAY</span><p>No disease passed its threshold, so there is no positive result to explain.</p></div>`;
    }
    put('read', el.read, final ? `<div class="readings-head"><span>READINGS</span><span>PROB · THRESHOLD</span></div>
      ${rows.map((r) => `<div class="reading"><div class="reading-top"><span class="name">${r.name}</span><span class="res ${r.cls}">${r.res}</span></div><div class="reading-nums"><span>${r.p}</span><span class="mute">threshold ${r.t}</span></div></div>`).join('')}
      ${panel}
      <div class="scope" style="margin-top:14px">Screens these four diseases only; other eye conditions are not checked.</div>
      <a class="link" style="margin-top:18px" href="#/screening/${esc(rec.id)}">Open reviewer’s notes →</a>` : '');
  }

  function play() {
    cancelAnimationFrame(raf); dx = null;
    if (reducedMotion()) { t = T.end; frame(); return; }
    const t0 = performance.now();
    const step = (now) => {
      const tt = now - t0;
      if (tt >= T.scanEnd && dx == null) measure();
      t = Math.min(tt, T.end);
      frame();
      if (tt < T.end) raf = requestAnimationFrame(step);
    };
    t = 0; frame(); raf = requestAnimationFrame(step);
  }

  $('#replay').addEventListener('click', play);
  play();
  return () => { cancelAnimationFrame(raf); if (ro) ro.disconnect(); };
}

function eyeDots(eye) {
  const d = (on) => `<span class="eye-dot" style="width:11px;height:11px;background:${on ? COLORS.INK : 'transparent'}"></span>`;
  return `<span class="eye-dots" aria-label="${eyeWord(eye)} eye screened">L${d(eye === 'L')}${d(eye === 'R')}R</span>`;
}
