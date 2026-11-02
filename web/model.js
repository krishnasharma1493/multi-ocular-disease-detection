// Model: the checkpoint's calibration certificate, from the checkpoint and outputs/metrics.json.
import { esc, dayStamp, sentence } from './util.js';
import { setTitle } from './app.js';

const C = { x: 120, y: 122 }, R = 86;
const ang = (v) => -135 + (Math.max(0.5, Math.min(1, v)) - 0.5) / 0.5 * 270;
const pt = (r, a) => { const t = a * Math.PI / 180; return [(C.x + r * Math.sin(t)).toFixed(2), (C.y - r * Math.cos(t)).toFixed(2)]; };
const num = (v) => (v == null ? '—' : v.toFixed(2));

function gauge(name, m, threshold) {
  const ticks = Array.from({ length: 21 }, (_, i) => {
    const v = 0.5 + i * 0.025, M = i % 4 === 0, a = ang(v), p = pt(M ? 74 : 80, a), q = pt(R, a);
    return `<line x1="${p[0]}" y1="${p[1]}" x2="${q[0]}" y2="${q[1]}" stroke="#1A1A17" stroke-width="${M ? 1.6 : 0.8}"/>`;
  }).join('');
  const labs = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0].map((v) => {
    const p = pt(60, ang(v));
    return `<text x="${p[0]}" y="${p[1]}" text-anchor="middle" dominant-baseline="central" font-family="IBM Plex Mono, monospace" font-size="10" fill="#5E5A50">${v === 1 ? '1.0' : String(v).slice(1)}</text>`;
  }).join('');
  const s = pt(R, -135), e = pt(R, 135);
  let needle = '', ap = '';
  if (m && m.roc_auc != null) {
    const n = pt(80, ang(m.roc_auc));
    needle = `<line x1="120" y1="122" x2="${n[0]}" y2="${n[1]}" stroke="#1A1A17" stroke-width="2" stroke-linecap="round"/>`;
  }
  if (m && m.ap != null) {
    const t1 = pt(R + 3, ang(m.ap)), t2 = pt(R + 13, ang(m.ap) - 3.5), t3 = pt(R + 13, ang(m.ap) + 3.5);
    ap = `<path d="M${t1}L${t2}L${t3}Z" fill="#1A1A17"/>`;
  }
  const figs = [['AUC', num(m && m.roc_auc)], ['AP', num(m && m.ap)], ['THRESHOLD', Math.round(threshold * 100) + '%'], ['PRECISION', num(m && m.precision)], ['RECALL', num(m && m.recall)]];
  const aria = m ? `${name}: AUC ${num(m.roc_auc)}, AP ${num(m.ap)}` : `${name}: no test metrics`;
  return `<div class="gauge"><h3>${esc(sentence(name))}</h3>
    <svg width="240" height="210" viewBox="0 0 240 210" style="overflow:visible" role="img" aria-label="${esc(aria)}">
      <path d="M${s}A${R} ${R} 0 1 1 ${e}" fill="none" stroke="#1A1A17" stroke-width="1"/>${ticks}${labs}${ap}${needle}
      <circle cx="120" cy="122" r="6" fill="#F3EFE6" stroke="#1A1A17" stroke-width="1.5"/></svg>
    <dl class="figs">${figs.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl></div>`;
}

export async function renderModel(view, { model }) {
  setTitle('Model');
  const metrics = model.metrics;
  const pretty = model.model_name === 'efficientnet_b0' ? 'EfficientNet-B0' : model.model_name;
  const sources = (metrics && metrics.sources) || [];
  const role = (d) => (d.diseases.length >= 3 ? 'multi-disease' : d.diseases.map((x) => x.toLowerCase()).join(', ') || 'normal controls');
  const issued = new Date(model.checkpoint.modified);
  view.innerHTML = `<main id="main"><div class="cert-wrap"><div class="cert-outer"><div class="cert">
    <div class="cert-top">
      <div style="display:flex;flex-direction:column;gap:14px"><span class="eyebrow" style="letter-spacing:0.18em">INSTRUMENT CALIBRATION CERTIFICATE</span><h1>Certificate of calibration</h1></div>
      <div class="serial"><span class="eyebrow">CHECKPOINT</span><b>RS-CAL-${esc(model.checkpoint.sha256.slice(0, 8).toUpperCase())}</b><span class="eyebrow" style="letter-spacing:0.12em">ISSUED ${dayStamp(issued)}</span></div>
    </div>
    <p class="cert-line">Model ${esc(pretty)} · <span class="n">${model.img_size}</span> px · ${metrics && metrics.test_images ? `tested on <span class="n">${metrics.test_images}</span> held-out eyes from unseen patients` : 'no held-out test metrics found next to the checkpoint (outputs/metrics.json)'}</p>
    <div style="display:flex;flex-direction:column;gap:14px">
      <div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap" class="eyebrow"><span style="letter-spacing:0.14em">GAUGES · ONE PER DISEASE</span><span style="letter-spacing:0.14em">NEEDLE = AUC · ▼ = AP · SCALE 0.5–1.0</span></div>
      <div class="gauges">${model.diseases.map((d, i) => gauge(d, metrics && metrics.per_class[d], model.thresholds[i])).join('')}</div>
    </div>
    <div class="cert-foot">
      <div style="display:flex;flex-direction:column;gap:12px"><span class="label">SOURCE DATASETS · ${sources.length}</span>
        ${sources.length ? sources.map((d, i) => `<div class="ds"><span class="mute">${String(i + 1).padStart(2, '0')}</span><b>${esc(d.name)}</b><span>${esc(role(d))}</span></div>`).join('') : '<span class="mute" style="font-size:13px">Not recorded in metrics.json.</span>'}
      </div>
      <div style="display:flex;flex-direction:column;gap:12px"><span class="label">KNOWN LIMITATIONS</span>
        <ol class="limits">
          <li>It screens only these four diseases.</li>
          <li>It may flag photos that show other conditions.</li>
          <li>The myopia class learned pathological myopia, so mild myopia can look normal.</li>
          <li>Glaucoma on everyday camp photos is its weakest area.</li>
          <li>It is not clinically validated.</li>
        </ol></div>
      <div class="seal">
        <svg width="150" height="150" viewBox="0 0 150 150" style="transform:rotate(-8deg)" role="img" aria-label="Seal: research prototype, not clinically validated"><defs><path id="sealArc" d="M75 75 m-54 0 a54 54 0 1 1 108 0 a54 54 0 1 1 -108 0"/></defs><circle cx="75" cy="75" r="72" fill="none" stroke="#1A1A17" stroke-width="1.5"/><circle cx="75" cy="75" r="66" fill="none" stroke="#1A1A17" stroke-width="0.75"/><circle cx="75" cy="75" r="40" fill="none" stroke="#1A1A17" stroke-width="0.75"/><circle cx="75" cy="75" r="22" fill="none" stroke="#1A1A17" stroke-width="5"/><circle cx="75" cy="75" r="3" fill="#1A1A17"/><text font-family="IBM Plex Mono, monospace" font-size="8.4" letter-spacing="1.6" fill="#1A1A17"><textPath href="#sealArc">RESEARCH PROTOTYPE · NOT CLINICALLY VALIDATED ·</textPath></text></svg>
        <span class="eyebrow" style="font-size:10px;line-height:1.4;letter-spacing:0.1em;text-align:center">RETINASCREEN<br>RESEARCH TEAM</span>
      </div>
    </div>
  </div></div></div></main>`;
}
