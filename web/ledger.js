// Ledger: today's screenings as a triage queue, a time ruler and findings by disease.
import { api, summarize, esc, eyeDots, hhmm, dayStamp, COLORS, DISEASES } from './util.js';
import { lensSVG } from './lens.js';
import { setTitle } from './app.js';

const GROUPS = {
  possible: { head: '▲ POSSIBLE', word: '▲ POSSIBLE', cls: 'c-pos', glyph: '▲', color: COLORS.V },
  review: { head: '◐ PENDING REVIEW', word: '◐ REVIEW', cls: 'c-rev', glyph: '◐', color: COLORS.O },
  clear: { head: '○ NOT DETECTED', word: '○ CLEAR', cls: 'c-clr', glyph: '○', color: COLORS.G },
};

const eyesLabel = (n) => `${n} ${n === 1 ? 'eye' : 'eyes'}`;

function ruler(items) {
  const times = items.map((it) => it.s.created);
  const start = new Date(times[0]); start.setMinutes(0, 0, 0);
  const lastHour = new Date(times[times.length - 1]); lastHour.setMinutes(0, 0, 0);
  const hours = Math.max(1, Math.round((lastHour - start) / 3600000) + 1);
  const span = hours * 60;
  const seen = new Set();
  let lastLabel = -Infinity;
  const ticks = items.map(({ rec, s }) => {
    const min = (s.created - start) / 60000, g = GROUPS[s.status], left = min / span * 100;
    // One label per patient, skipped when it would collide with the previous label.
    let lab = '';
    if (!seen.has(rec.ref) && left - lastLabel >= 8) { lab = rec.ref; lastLabel = left; }
    seen.add(rec.ref);
    return `<span class="tick" style="left:${left.toFixed(2)}%"><span class="g" style="color:${g.color}">${g.glyph}</span><span class="bar" style="background:${g.color}"></span><span class="lab">${esc(lab)}</span></span>`;
  }).join('');
  const step = hours > 10 ? 2 : 1;
  const labels = [];
  for (let i = 0; i <= hours; i += step) {
    const d = new Date(start.getTime() + i * 3600000);
    labels.push(`<span class="hour" style="left:${(i / hours * 100).toFixed(2)}%">${hhmm(d)}</span>`);
  }
  return `<div class="axis-wrap" aria-hidden="true">
    <div class="axis" style="top:64px;height:1px;background:var(--ink)"></div>
    <div class="axis" style="top:56px;height:8px;background:linear-gradient(90deg,var(--ink) 0 1px,transparent 1px) 0 0/${(100 / hours / 12).toFixed(3)}% 100% repeat-x;opacity:0.5"></div>
    <div class="axis" style="top:48px;height:16px;background:linear-gradient(90deg,var(--ink) 0 1px,transparent 1px) 0 0/${(100 / hours).toFixed(3)}% 100% repeat-x"></div>
    <div class="axis" style="top:0;bottom:0">${ticks}${labels.join('')}</div>
  </div>`;
}

function findingsChart(items) {
  const n = items.length, radii = [150, 120, 90, 60];
  const counts = DISEASES.map((name) => {
    let pos = 0, near = 0;
    items.forEach(({ s }) => {
      const r = s.rows.find((x) => x.disease === name);
      if (r.positive) pos++;
      else if (s.near && s.near.disease === name) near++;
    });
    return { name, pos, near };
  });
  const arcs = counts.map((c, i) => {
    const r = radii[i], unit = 2 * Math.PI * r / n, out = [];
    if (c.pos) out.push(`<circle cx="170" cy="170" r="${r}" fill="none" stroke="${COLORS.V}" stroke-width="14" stroke-dasharray="${(unit * c.pos).toFixed(1)} 10000" transform="rotate(-90 170 170)"/>`);
    if (c.near) out.push(`<circle cx="170" cy="170" r="${r}" fill="none" stroke="${COLORS.O}" stroke-width="14" stroke-dasharray="${(unit * c.near).toFixed(1)} 10000" stroke-dashoffset="${(-unit * c.pos).toFixed(1)}" transform="rotate(-90 170 170)"/>`);
    return out.join('');
  }).join('');
  const spokes = n > 1 && n <= 72 ? Array.from({ length: n }, (_, i) => {
    const a = i / n * 2 * Math.PI, x1 = 170 + 160 * Math.sin(a), y1 = 170 - 160 * Math.cos(a), x2 = 170 + 50 * Math.sin(a), y2 = 170 - 50 * Math.cos(a);
    return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`;
  }).join('') : '';
  const labelName = { 'Diabetic Retinopathy': 'DIABETIC RET.' };
  const labels = counts.map((c, i) => `<text x="162" y="${[8, 40, 70, 100][i]}">${labelName[c.name] || c.name.toUpperCase()}  ${c.pos}${c.near ? ` +${c.near}◐` : ''}</text>`).join('');
  const aria = `Findings by disease, of ${eyesLabel(n)}: ` + counts.map((c) => `${c.name} ${c.pos} possible${c.near ? `, ${c.near} close to notch` : ''}`).join('; ') + '.';
  const rings = radii.map((r) => `<circle cx="170" cy="170" r="${r}" fill="none" stroke="#E4DDCD" stroke-width="14"/><circle cx="170" cy="170" r="${r + 7}" fill="none" stroke="#1A1A17" stroke-width="0.8"/><circle cx="170" cy="170" r="${r - 7}" fill="none" stroke="#1A1A17" stroke-width="0.8"/>`).join('');
  return `<svg width="360" height="360" viewBox="0 0 340 340" role="img" aria-label="${esc(aria)}" style="align-self:center;overflow:visible;max-width:100%;height:auto">
    ${rings}${arcs}
    <g stroke="#F3EFE6" stroke-width="2.5">${spokes}</g>
    <g font-family="IBM Plex Mono, monospace" font-size="10.5" font-weight="500" text-anchor="end" fill="#1A1A17" style="white-space:pre">${labels}</g>
    <text x="170" y="166" text-anchor="middle" font-family="Newsreader, serif" font-size="34" font-weight="500" fill="#1A1A17">${n}</text>
    <text x="170" y="186" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="9.5" letter-spacing="1.5" fill="#5E5A50">${n === 1 ? 'EYE' : 'EYES'}</text>
  </svg>`;
}

function itemRow({ rec, s }, g) {
  const disagree = rec.review && rec.review.read === 'disagree';
  return `<a class="item" href="#/screening/${esc(rec.id)}" aria-label="${esc(`${rec.ref}, ${rec.eye === 'L' ? 'left' : 'right'} eye, ${hhmm(s.created)}. ${s.verdict}. ${s.sub}.${disagree ? ' Reviewer disagrees.' : ''}`)}">
    <span class="hole" aria-hidden="true"></span>
    <span class="lens-thumb" aria-hidden="true">${lensSVG({ size: 72, values: s.vals, thresholds: s.ths, eye: rec.eye })}</span>
    <span class="who" aria-hidden="true"><span class="ref">${esc(rec.ref)}</span><span style="display:flex;align-items:center;gap:8px">${eyeDots(rec.eye, 9)}<span class="mono mute" style="font-size:11px">${hhmm(s.created)}</span></span></span>
    <span class="what" aria-hidden="true"><b>${esc(s.verdict)}</b><span>${esc(s.sub)}</span></span>
    <span class="state ${g.cls}" aria-hidden="true"><span>${g.word}</span>${disagree ? '<span class="stamp-sm">✕ REVIEWER: DISAGREE</span>' : ''}</span>
  </a>`;
}

export async function renderLedger(view) {
  const data = await api('/screenings');
  const items = data.screenings.map((rec) => ({ rec, s: summarize(rec) }));
  const today = dayStamp(new Date());
  const n = items.length;
  setTitle('Ledger');

  if (!n) {
    view.innerHTML = `<main id="main">
      <div class="ledger-head"><div class="meta"><span>LEDGER · ${today} · NO SCREENINGS YET</span></div><h1>Today’s camp — 0 eyes screened</h1></div>
      <div class="ruler-row empty">
        <div class="axis-wrap" aria-hidden="true"><div class="axis" style="top:64px;height:1px;background:var(--ink)"></div><div class="axis" style="top:56px;height:8px;background:linear-gradient(90deg,var(--ink) 0 1px,transparent 1px) 0 0/5% 100% repeat-x;opacity:0.5"></div></div>
        <a class="new-btn" href="#/new"><span aria-hidden="true">+</span>New screening</a>
      </div>
      <div class="empty-hero">
        <div aria-hidden="true">${lensSVG({ size: window.innerWidth < 760 ? 280 : 380, state: 'empty' })}</div>
        <div class="stack-words"><span class="w1">NO EYES</span><span class="w2">SCREENED</span><span class="w3">YET TODAY</span>
        <p>Each photo you analyze is filed here as a specimen tag, ordered by urgency.</p></div>
      </div></main>`;
    return;
  }

  const first = items[0].s.created, last = items[n - 1].s.created;
  const byRef = {};
  items.forEach(({ rec }) => { (byRef[rec.ref] = byRef[rec.ref] || new Set()).add(rec.eye); });
  const patients = Object.keys(byRef).length;
  const both = Object.values(byRef).every((set) => set.size === 2);
  const urgency = (s) => Math.max(...s.rows.map((r) => r.probability - r.threshold));
  const groups = ['possible', 'review', 'clear'].map((key) => ({
    key, g: GROUPS[key],
    items: items.filter((it) => it.s.status === key).sort((a, b) => urgency(b.s) - urgency(a.s)),
  })).filter((grp) => grp.items.length);

  view.innerHTML = `<main id="main">
    <div class="ledger-head">
      <div class="meta"><span>LEDGER · ${today} · ${hhmm(first)} – ${hhmm(last)}</span><span>${patients} ${patients === 1 ? 'PATIENT' : 'PATIENTS'} · ${both ? 'BOTH EYES' : eyesLabel(n).toUpperCase()}</span></div>
      <h1>Today’s camp — ${eyesLabel(n)} screened</h1>
    </div>
    <div class="ruler-row">${ruler(items)}<a class="new-btn" href="#/new"><span aria-hidden="true">+</span>New screening</a></div>
    <div class="ledger-grid">
      <section aria-labelledby="queue-h" style="display:flex;flex-direction:column;gap:28px;min-width:0">
        <div class="section-head"><h2 id="queue-h">Triage queue</h2><span class="eyebrow" style="letter-spacing:0.14em">ORDERED BY URGENCY</span></div>
        ${groups.map(({ g, items: list }) => `<div class="group"><div class="group-head ${g.cls}"><span>${g.head}</span><span>${list.length}</span></div>${list.map((it) => itemRow(it, g)).join('')}</div>`).join('')}
      </section>
      <section aria-labelledby="find-h" style="display:flex;flex-direction:column;gap:24px;min-width:0">
        <div class="section-head"><h2 id="find-h">Findings by disease</h2><span class="eyebrow" style="letter-spacing:0.14em">OF ${eyesLabel(n).toUpperCase()}</span></div>
        ${findingsChart(items)}
        <div class="legend"><span>ONE DIVISION = ONE EYE</span><span><span class="c-pos">▲</span> POSSIBLE · <span class="c-rev">◐</span> REVIEW</span></div>
      </section>
    </div></main>`;
}
