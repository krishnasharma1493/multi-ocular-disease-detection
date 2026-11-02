// Screening detail: specimen facts, lens readout, readings and the reviewer's notes.
import { api, summarize, esc, eyeDots, eyeLong, eyeWord, hhmm, dayStamp, mb, pct, pct0, sentence, OfflineError, COLORS, TREATMENT } from './util.js';
import { lensSVG } from './lens.js';
import { setTitle } from './app.js';

const READS = [['agree', '✓', 'Agree'], ['disagree', '✕', 'Disagree'], ['unsure', '?', 'Unsure']];
const BADGE = `<svg width="16" height="16" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="12.5" fill="none" stroke="#1A1A17" stroke-width="1.5"/><circle cx="14" cy="14" r="7.5" fill="none" stroke="#1A1A17" stroke-width="3"/></svg>`;

export async function renderDetail(view, { id, model, isCurrent }) {
  let rec = await api('/screenings/' + encodeURIComponent(id));
  if (!isCurrent()) return null;
  const s = summarize(rec);
  const photo = `/api/screenings/${encodeURIComponent(rec.id)}/image`;
  setTitle(`${rec.ref} ${rec.eye} · Detail`);
  const pos = s.positives.length > 0;
  const nearest = s.nearest;
  const verdict = pos ? 'Possible: ' + s.positives.map((r) => sentence(r.disease)).join(', ') + '.' : 'Not detected.';
  const verdictSub = pos
    ? `${s.positives.length} OF 4 PAST NOTCH · ${s.primary.disease.toUpperCase()} ${pct(s.primary.probability)} vs ${pct0(s.primary.threshold)}`
    : `0 OF 4 PAST NOTCH · NEAREST: ${nearest.disease.toUpperCase()} ${pct(nearest.probability)} vs ${pct0(nearest.threshold)}`;
  const treatments = s.positives.map((r) => ({ k: 'USUAL TREATMENT · ' + r.disease.toUpperCase(), v: TREATMENT[r.disease] }));
  const img = rec.image;
  const facts = [
    ['PATIENT REF', rec.ref],
    ['EYE', eyeLong(rec.eye)],
    ['IMAGE', `${img.width} × ${img.height} · ${img.type} · ${mb(img.bytes)}`],
    ['QUALITY', `Sharpness ${rec.quality.sharpness.toFixed(2)} · ${rec.quality.pass ? 'pass' : 'fail'}`],
    ['SCREENING No.', rec.id],
    ...(rec.notes ? [['NOTES', rec.notes]] : []),
  ];
  const size = () => (window.innerWidth < 760 ? Math.min(330, window.innerWidth - 40) : 600);
  const modelLine = `${model.model_name === 'efficientnet_b0' ? 'EfficientNet-B0' : model.model_name} · ${rec.model.img_size} px · ${rec.model.ms} ms`;

  const statusHTML = () => {
    const disagree = rec.review && rec.review.read === 'disagree';
    const base = pos ? '▲ POSSIBLE' : '○ NOT DETECTED';
    return { text: base + (disagree ? ' · ✕ REVIEWER: DISAGREE' : ''), color: pos ? COLORS.VT : disagree ? COLORS.INK : COLORS.G };
  };

  view.innerHTML = `<main id="main">
    <div class="crumb">
      <a class="back" href="#/ledger">← LEDGER</a><span class="sep" aria-hidden="true"></span>
      <h1 class="ref">${esc(rec.ref)} <span class="sr-only">${eyeWord(rec.eye)} eye</span></h1>
      <span aria-hidden="true">${eyeDots(rec.eye)}</span>
      <span class="status" id="status"></span>
      <span class="when">CAPTURED ${hhmm(s.created)} · ${dayStamp(s.created)}</span>
    </div>
    <div class="detail-grid">
      <section class="facts" aria-labelledby="spec-h">
        <h2 id="spec-h" class="eyebrow" style="padding-bottom:14px">SPECIMEN</h2>
        <dl style="margin:0">${facts.map(([k, v]) => `<div class="fact"><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
      </section>
      <div class="detail-center">
        <span class="eyebrow" style="text-align:center">LENS READOUT · FOUR QUADRANTS · CLOCKWISE FROM 0°</span>
        <div id="lens" role="img" aria-label="${esc(`Lens readout. ` + s.rows.map((r) => `${r.disease} ${pct(r.probability)}, notch ${pct0(r.threshold)}, ${r.positive ? 'positive' : 'not detected'}`).join('; '))}"></div>
        <div class="verdict" style="gap:12px;margin-top:6px">
          <div class="verdict-line" style="gap:14px"><span class="glyph" aria-hidden="true" style="color:${pos ? COLORS.V : COLORS.G}">${pos ? '▲' : '○'}</span><span class="words">${esc(verdict)}</span></div>
          <span class="sub" style="line-height:1.4">${esc(verdictSub)}</span>
          <div id="override"></div>
        </div>
      </div>
      <section class="readings-col" aria-label="Readings" style="display:flex;flex-direction:column;min-width:0">
        <div class="readings-head"><span>READINGS</span><span>PROB · NOTCH</span></div>
        ${s.rows.map((r) => `<div class="reading" style="padding:16px 0 18px">
          <div class="reading-top"><span class="name">${sentence(r.disease)}</span><span class="res ${r.positive ? 'c-pos' : 'c-clr'}">${r.positive ? '▲ POSITIVE' : '○ NOT DETECTED'}</span></div>
          <div class="reading-nums"><span>${pct(r.probability)}</span><span class="mute">notch ${pct0(r.threshold)}</span></div>
          <div class="bar" aria-hidden="true"><div class="scale"></div><div class="base"></div><div class="fill" style="width:${(r.probability * 100).toFixed(2)}%;background:${r.positive ? COLORS.V : COLORS.INK}"></div><div class="notch" style="left:calc(${(r.threshold * 100).toFixed(2)}% - 1px)"></div></div>
        </div>`).join('')}
        <div class="live"><i aria-hidden="true"></i>${esc(modelLine)}</div>
        <div class="scope">Screens these four diseases only; other eye conditions are not checked.</div>
      </section>
    </div>
    <section class="notes-sec" aria-labelledby="notes-h">
      <div class="notes-row head"><div class="margin" aria-hidden="true"></div><div class="body"><h2 id="notes-h">Reviewer’s notes</h2><span class="badge">${BADGE}Verified by RetinaScreen AI</span></div></div>
      <div class="notes-row"><div class="margin" aria-hidden="true">① READ</div><div class="body">
        <span id="read-q" style="font:500 13px/1 var(--sans);color:var(--graphite)">Do you agree with the model’s verdict?</span>
        <div class="toggles" role="radiogroup" aria-labelledby="read-q" id="toggles"></div>
        <span class="save-state" id="save-state" aria-live="polite"></span>
      </div></div>
      ${treatments.length ? `<div class="notes-row"><div class="margin" aria-hidden="true">② NOTE</div><div class="body" style="padding-bottom:28px;gap:14px">
        ${treatments.map((tr) => `<div class="treat"><span class="k">${esc(tr.k)}</span><span class="v">${esc(tr.v)}</span></div>`).join('')}
      </div></div>` : ''}
    </section></main>`;

  const $ = (sel) => view.querySelector(sel);
  const toggles = $('#toggles'), saveState = $('#save-state');

  function paintReview() {
    const read = rec.review ? rec.review.read : null;
    toggles.innerHTML = READS.map(([key, g, label], i) => {
      const on = read === key, focusable = read ? on : i === 0;
      return `<button type="button" role="radio" aria-checked="${on}" tabindex="${focusable ? 0 : -1}" data-read="${key}"><span aria-hidden="true">${g}</span>${label}</button>`;
    }).join('');
    const st = statusHTML();
    const status = $('#status');
    status.textContent = st.text; status.style.color = st.color;
    $('#override').innerHTML = read === 'disagree'
      ? '<div class="override"><span>▲ HUMAN OVERRIDE</span><i aria-hidden="true"></i><span>REVIEWER: DISAGREE</span></div>' : '';
    saveState.textContent = rec.review ? `SAVED ${hhmm(new Date(rec.review.at))}` : 'NOT YET REVIEWED';
  }

  async function choose(key, focus) {
    if (rec.review && rec.review.read === key) return;
    const prev = rec.review;
    rec = { ...rec, review: { read: key, at: new Date().toISOString() } };
    paintReview();
    saveState.textContent = 'SAVING…';
    if (focus) toggles.querySelector(`[data-read="${key}"]`).focus();
    try {
      rec = await api(`/screenings/${encodeURIComponent(rec.id)}/review`, { method: 'PUT', body: JSON.stringify({ read: key }) });
      paintReview();
      if (focus) toggles.querySelector(`[data-read="${key}"]`).focus();
    } catch (e) {
      rec = { ...rec, review: prev };
      paintReview();
      saveState.textContent = e instanceof OfflineError ? 'NOT SAVED · SERVER OFFLINE' : 'NOT SAVED · TRY AGAIN';
    }
  }

  toggles.addEventListener('click', (e) => { const b = e.target.closest('[data-read]'); if (b) choose(b.dataset.read, true); });
  toggles.addEventListener('keydown', (e) => {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (!(e.key in keys)) return;
    e.preventDefault();
    const btns = [...toggles.querySelectorAll('[data-read]')];
    const i = btns.indexOf(document.activeElement);
    const next = btns[(i + keys[e.key] + btns.length) % btns.length];
    choose(next.dataset.read, true);
  });

  const paintLens = () => { $('#lens').innerHTML = lensSVG({ size: size(), values: s.vals, thresholds: s.ths, eye: rec.eye, photo, labelSize: size() < 400 ? 13 : 10.5 }); };
  let lastSize = size();
  const onResize = () => { if (size() !== lastSize) { lastSize = size(); paintLens(); } };
  window.addEventListener('resize', onResize);
  paintLens();
  paintReview();
  return () => window.removeEventListener('resize', onResize);
}
