// LensReadout: the signature dial. Four quadrants clockwise from 0°:
// Myopia, Cataract, Glaucoma, Diabetic retinopathy. Returns an SVG string.
import { esc, COLORS } from './util.js';

let uidCount = 0;
const f = (n) => (+n).toFixed(2);

export function lensSVG(P = {}) {
  const size = +(P.size ?? 440);
  const state = P.state ?? 'readout';
  const v = P.values ?? [0, 0, 0, 0];
  const th = P.thresholds ?? [0.5, 0.5, 0.5, 0.5];
  const thumb = size < 140, labels = size >= 300;
  const reveal = state === 'analyzing' ? +(P.reveal ?? 0) : 4;
  const s = P.eye === 'L' ? -1 : 1, C = 220, k = 440 / size;
  const u = 'lr' + (++uidCount).toString(36);
  const hw = Math.max(1, k * 0.75), hw2 = hw * 1.6, hw3 = hw * 2.4, hs = thumb ? 18 : 6;
  const g = thumb ? { pr: 116, c0: 134, c1: 192 } : { pr: 128, c0: 142, c1: 166 };
  g.cm = (g.c0 + g.c1) / 2; g.cw = g.c1 - g.c0; g.px = 220 - g.pr; g.pd = 2 * g.pr;
  const pt = (r, a) => { const t = a * Math.PI / 180; return [f(C + r * Math.sin(t)), f(C - r * Math.cos(t))]; };
  const sector = (r0, r1, a0, a1) => {
    if (a1 - a0 < 0.3) return '';
    const L = a1 - a0 > 180 ? 1 : 0;
    return `M${pt(r1, a0)}A${r1} ${r1} 0 ${L} 1 ${pt(r1, a1)}L${pt(r0, a1)}A${r0} ${r0} 0 ${L} 0 ${pt(r0, a0)}Z`;
  };
  const arc = (r, a0, a1, ccw) => ccw ? `M${pt(r, a1)}A${r} ${r} 0 0 0 ${pt(r, a0)}` : `M${pt(r, a0)}A${r} ${r} 0 0 1 ${pt(r, a1)}`;
  const ls = +(P.labelSize ?? 10.5);
  const names = ['MYOPIA', 'CATARACT', 'GLAUCOMA', ls > 11 ? 'DIABETIC RET.' : 'DIABETIC RETINOPATHY'];
  const { V, G, O, INK, MUTE } = COLORS;
  const showQuads = state === 'readout' || state === 'analyzing';
  const well = state === 'empty' || state === 'offline';
  const showPhoto = ['readout', 'analyzing', 'uploading', 'photo'].includes(state);
  const dash = state === 'offline' ? '6 7' : 'none';
  const pr = g.pr;
  const out = [];

  out.push(`<svg width="${size}" height="${size}" viewBox="0 0 440 440" style="display:block;overflow:visible;max-width:100%;height:auto" aria-hidden="true" focusable="false"><defs>`,
    `<radialGradient id="${u}b" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="#EE8048"/><stop offset="0.5" stop-color="#CF4A20"/><stop offset="0.82" stop-color="#962812"/><stop offset="1" stop-color="#3A0B04"/></radialGradient>`,
    `<radialGradient id="${u}d"><stop offset="0" stop-color="#FFF4CF"/><stop offset="0.45" stop-color="#F8C978"/><stop offset="1" stop-color="#E98A4A" stop-opacity="0"/></radialGradient>`,
    `<radialGradient id="${u}m"><stop offset="0" stop-color="#5C1207" stop-opacity="0.85"/><stop offset="1" stop-color="#5C1207" stop-opacity="0"/></radialGradient>`,
    `<clipPath id="${u}c"><circle cx="220" cy="220" r="${pr}"/></clipPath>`,
    `<pattern id="${u}h" width="${hs}" height="${hs}" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="${hs}" stroke="${INK}" stroke-width="${hw}"/></pattern>`,
    `</defs>`);

  if (!showQuads) {
    out.push(`<circle cx="220" cy="220" r="${g.cm}" fill="none" stroke="#E4DDCD" stroke-width="${g.cw}"/>`,
      `<circle cx="220" cy="220" r="${g.c0}" fill="none" stroke="${INK}" stroke-width="${hw}" stroke-dasharray="${dash}"/>`,
      `<circle cx="220" cy="220" r="${g.c1}" fill="none" stroke="${INK}" stroke-width="${hw}" stroke-dasharray="${dash}"/>`);
    if (state === 'uploading') {
      const prog = Math.max(0, Math.min(1, +(P.progress ?? 0)));
      out.push(`<path d="${sector(g.c0, g.c1, 0, Math.min(359.9, prog * 360))}" fill="${INK}"/>`);
    }
  }
  if (well) {
    out.push(`<circle cx="220" cy="220" r="${pr}" fill="#EFEADF" stroke="${INK}" stroke-width="${hw}" stroke-dasharray="${dash}"/>`,
      `<circle cx="220" cy="220" r="64" fill="none" stroke="#B9B09C" stroke-width="${hw}" stroke-dasharray="${dash}"/>`,
      `<circle cx="220" cy="220" r="6" fill="none" stroke="${INK}" stroke-width="${hw}"/>`);
  }
  if (showPhoto) {
    const X = (n) => f(C + n * s), Y = (n) => f(C + n);
    out.push(`<g clip-path="url(#${u}c)">`);
    if (P.photo) {
      out.push(`<image href="${esc(P.photo)}" x="${g.px}" y="${g.px}" width="${g.pd}" height="${g.pd}" preserveAspectRatio="xMidYMid slice"/>`);
    } else if (!P.photoUnder) {
      const vessels = [
        [`M${X(46)} ${Y(-8)}C${X(22)} ${Y(-72)} ${X(-40)} ${Y(-92)} ${X(-118)} ${Y(-58)}`, 4.5],
        [`M${X(46)} ${Y(-8)}C${X(20)} ${Y(62)} ${X(-40)} ${Y(86)} ${X(-118)} ${Y(56)}`, 4.5],
        [`M${X(46)} ${Y(-8)}C${X(62)} ${Y(-58)} ${X(72)} ${Y(-92)} ${X(58)} ${Y(-124)}`, 3.5],
        [`M${X(46)} ${Y(-8)}C${X(66)} ${Y(42)} ${X(76)} ${Y(82)} ${X(54)} ${Y(122)}`, 3.5],
        [`M${X(-8)} ${Y(-84)}Q${X(-30)} ${Y(-116)} ${X(-64)} ${Y(-122)}`, 2.5],
        [`M${X(-8)} ${Y(78)}Q${X(-34)} ${Y(110)} ${X(-70)} ${Y(114)}`, 2.5],
        [`M${X(46)} ${Y(-8)}Q${X(100)} ${Y(-20)} ${X(124)} ${Y(-40)}`, 2.5],
        [`M${X(30)} ${Y(-60)}Q${X(-10)} ${Y(-40)} ${X(-30)} ${Y(-20)}`, 1.8],
        [`M${X(28)} ${Y(50)}Q${X(-6)} ${Y(36)} ${X(-24)} ${Y(18)}`, 1.8],
      ];
      out.push(`<circle cx="220" cy="220" r="${pr}" fill="url(#${u}b)"/>`,
        ...vessels.map(([d, w]) => `<path d="${d}" fill="none" stroke="#6E1608" stroke-opacity="0.55" stroke-width="${w}" stroke-linecap="round"/>`),
        `<circle cx="${f(C - 50 * s)}" cy="${f(C + 6)}" r="34" fill="url(#${u}m)"/>`,
        `<circle cx="${f(C + 46 * s)}" cy="${f(C - 8)}" r="30" fill="url(#${u}d)"/>`);
    }
    if (state === 'analyzing') {
      const scanX = C - pr + 2 * pr * +(P.scan ?? 0);
      out.push(`<rect x="${f(scanX)}" y="0" width="440" height="440" fill="${INK}" fill-opacity="0.42"/>`,
        `<rect x="${f(scanX - 34)}" y="0" width="34" height="440" fill="#FFF3D6" fill-opacity="0.18"/>`,
        `<line x1="${f(scanX)}" y1="0" x2="${f(scanX)}" y2="440" stroke="#FFF6E2" stroke-width="2.5"/>`);
    }
    out.push(`</g><circle cx="220" cy="220" r="${pr}" fill="none" stroke="${INK}" stroke-width="${hw}"/>`);
    if (state === 'analyzing') {
      const sx = C - pr + 2 * pr * +(P.scan ?? 0);
      out.push(`<path d="M${f(sx - 6)} ${C - pr - 13}L${f(sx + 6)} ${C - pr - 13}L${f(sx)} ${C - pr - 3}ZM${f(sx - 6)} ${C + pr + 13}L${f(sx + 6)} ${C + pr + 13}L${f(sx)} ${C + pr + 3}Z" fill="${INK}"/>`);
    }
  }

  let cross = [];
  if (well) cross = [[C - pr, C, C - 16, C], [C + 16, C, C + pr, C], [C, C - pr, C, C - 16], [C, C + 16, C, C + pr]];
  else if (!thumb) cross = [0, 90, 180, 270].map((a) => [...pt(pr + 3, a), ...pt(g.c0 - 3, a)]);
  cross.forEach(([x1, y1, x2, y2]) => out.push(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${INK}" stroke-width="${hw}" stroke-dasharray="${dash}"/>`));

  const textEls = [];
  if (showQuads) {
    names.forEach((name, i) => {
      const a0 = i * 90 + 4, span = 82, a1 = a0 + span, fl = Math.floor(reveal);
      const done = i < fl, partial = !done && i === fl, frac = done ? 1 : partial ? reveal - fl : 0;
      const val = v[i], fe = a0 + span * val * frac, pos = done && val >= th[i], ta = a0 + span * th[i];
      const bottom = i === 1 || i === 2;
      const n1 = pt(g.c0 - 5, ta), n2 = pt(g.c1 + 5, ta), tip = pt(g.c1 + 4, ta), b1 = pt(g.c1 + 13, ta - 2), b2 = pt(g.c1 + 13, ta + 2);
      const o1 = pt(g.c1 + 2, fe), o2 = pt(g.c1 + (thumb ? 26 : 20), fe), cmp = pt(g.c1 + 18, a0 + span / 2);
      const paint = pos ? V : partial ? O : `url(#${u}h)`, stroke = pos || partial ? 'none' : INK;
      out.push(`<path d="${sector(g.c0, g.c1, a0, a1)}" fill="#E4DDCD" stroke="${INK}" stroke-width="${hw}"/>`,
        `<path d="${sector(g.c0, g.c1, a0, fe)}" fill="${paint}" stroke="${stroke}" stroke-width="${hw}"/>`,
        `<line x1="${n1[0]}" y1="${n1[1]}" x2="${n2[0]}" y2="${n2[1]}" stroke="${INK}" stroke-width="${hw2}"/>`,
        `<path d="M${tip}L${b1}L${b2}Z" fill="${INK}"/>`);
      if (pos) out.push(`<line x1="${o1[0]}" y1="${o1[1]}" x2="${o2[0]}" y2="${o2[1]}" stroke="${V}" stroke-width="${hw3}"/>`);
      if (thumb && done && !pos) out.push(`<circle cx="${cmp[0]}" cy="${cmp[1]}" r="9" fill="none" stroke="${G}" stroke-width="${hw3}"/>`);
      if (labels) {
        let st, sc;
        if (done) { st = pos ? ' ▲ POSSIBLE' : ' ○ CLEAR'; sc = pos ? V : G; }
        else if (partial) { st = ' ◐ MEASURING'; sc = O; } else { st = ' · QUEUED'; sc = MUTE; }
        const label = done || partial ? `${name} ${(val * frac * 100).toFixed(1)}%` : name;
        textEls.push(`<path id="${u}l${i}" d="${arc(bottom ? 212 : 201, a0, a1, bottom)}" fill="none"/>`,
          `<text font-family="IBM Plex Mono, monospace" font-size="${ls}" font-weight="500" letter-spacing="1" fill="${INK}"><textPath href="#${u}l${i}" startOffset="50%" text-anchor="middle">${label}<tspan fill="${sc}" font-weight="600">${st}</tspan></textPath></text>`);
      }
    });
  }
  if (!thumb) {
    const tickOp = state === 'offline' ? 0.35 : 1;
    for (let i = 0; i < 72; i++) {
      const a = i * 5, M = a % 30 === 0, p1 = pt(172, a), p2 = pt(M ? 186 : 178, a);
      out.push(`<line x1="${p1[0]}" y1="${p1[1]}" x2="${p2[0]}" y2="${p2[1]}" stroke="${INK}" stroke-width="${M ? hw * 1.4 : hw * 0.8}" stroke-opacity="${tickOp}"/>`);
    }
  }
  if (well && labels) {
    for (let i = 0; i < 12; i++) {
      const p = pt(199, i * 30);
      out.push(`<text x="${p[0]}" y="${p[1]}" text-anchor="middle" dominant-baseline="central" font-family="IBM Plex Mono, monospace" font-size="10" fill="${MUTE}">${i * 30}°</text>`);
    }
  }
  out.push(...textEls);
  if (state === 'uploading' && labels) {
    out.push(`<text x="220" y="16" text-anchor="middle" font-family="IBM Plex Mono, monospace" font-size="11" font-weight="600" letter-spacing="1.4" fill="${INK}">UPLOADING ${Math.round(+(P.progress ?? 0) * 100)}%</text>`);
  }
  out.push('</svg>');
  return out.join('');
}

// Square photo placed under a lens drawn with photoUnder, so it is not re-created every frame.
export function lensPhotoStyle(size) {
  const pr = 128, scale = size / 440;
  return `position:absolute;left:${(220 - pr) * scale}px;top:${(220 - pr) * scale}px;width:${2 * pr * scale}px;height:${2 * pr * scale}px;border-radius:50%;object-fit:cover`;
}
