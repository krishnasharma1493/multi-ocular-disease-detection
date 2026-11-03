import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { photoVersion, useAnalyzeScreening, useScreening, useScreeningImage } from '../features/screenings/api';
import { apiError, apiErrorMessage, isOffline, type Screening, type ScreeningResult } from '../lib/api/types';
import { COLORS, DISEASES, esc, eyeCode, eyeWord, orderedFindings, byProbability, pct, reducedMotion } from '../lib/format';
import { lensPhotoStyle, lensSVG } from '../lib/lens';
import { EyeDots } from '../components/Lens';
import { Loading, QueryError, useFocusHeading } from '../components/States';

const T = { up: 700, scanEnd: 3700, move: 900, verdict: 4400, ov0: 4600, ov1: 5400, ld0: 5200, ld: 700, settle: 6600, settleDur: 800, read0: 6800, end: 7600 };
const clamp = (x: number) => Math.max(0, Math.min(1, x));
const ease = (x: number) => { x = clamp(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };
const sine = (x: number) => -(Math.cos(Math.PI * clamp(x)) - 1) / 2;

function validGrid(g: unknown): g is number[][] {
  return Array.isArray(g) && g.length >= 4 && g.every((r) => Array.isArray(r) && r.length === g.length && r.every((v) => typeof v === 'number' && isFinite(v) && v >= 0 && v <= 1))
    && g.some((r: number[]) => r.some((v) => v > 0));
}

type Region = { m: number; cx: number; cy: number; share: number };
/** The two heaviest connected regions (cells >= 0.5) and their share of the map's weight. */
function regionsOf(grid: number[][]): Region[] {
  const n = grid.length, seen = grid.map((r) => r.map(() => false));
  let total = 0;
  grid.forEach((r) => r.forEach((v) => { total += v; }));
  const comps: Omit<Region, 'share'>[] = [];
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    if (seen[i][j] || grid[i][j] < 0.5) continue;
    let m = 0, sx = 0, sy = 0; const q: [number, number][] = [[i, j]]; seen[i][j] = true;
    while (q.length) {
      const [y, x] = q.pop()!, v = grid[y][x]; m += v; sx += (x + 0.5) * v; sy += (y + 0.5) * v;
      for (const [dy, dx] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const yy = y + dy, xx = x + dx;
        if (yy >= 0 && yy < n && xx >= 0 && xx < n && !seen[yy][xx] && grid[yy][xx] >= 0.5) { seen[yy][xx] = true; q.push([yy, xx]); }
      }
    }
    comps.push({ m, cx: sx / m, cy: sy / m });
  }
  return comps.sort((a, b) => b.m - a.m).slice(0, 2).map((c) => ({ ...c, share: total > 0 ? c.m / total : 0 }));
}

function overlaySVG(grid: number[][], primary: string, t: number, lensSize: number, narrow: boolean): string {
  const { V, INK, MUTE } = COLORS, px = 92, pd = 256;
  const n = grid.length, cell = pd / n, ovOp = ease((t - T.ov0) / (T.ov1 - T.ov0));
  const cells: string[] = [];
  grid.forEach((r, i) => r.forEach((v, j) => {
    if (v >= 0.25) cells.push(`<rect x="${(px + j * cell).toFixed(2)}" y="${(px + i * cell).toFixed(2)}" width="${(cell + 0.6).toFixed(2)}" height="${(cell + 0.6).toFixed(2)}" fill="${V}" fill-opacity="${(0.1 + 0.42 * (v - 0.25) / 0.75).toFixed(3)}"/>`);
  }));
  const regs = regionsOf(grid).map((r) => ({ ...r, x: px + r.cx * cell, y: px + r.cy * cell }));
  const ordered = regs.slice().sort((a, b) => a.y - b.y);
  const slots = ordered.length === 1 ? [Math.max(110, Math.min(330, ordered[0].y))] : [150, 300];
  const leaders = ordered.map((r, idx) => {
    const rank = regs.indexOf(r), p = ease((t - T.ld0 - rank * 250) / T.ld), ly = slots[idx];
    const out = [`<circle cx="${r.x}" cy="${r.y}" r="8" fill="none" stroke="${COLORS.PAPER}" stroke-width="3" opacity="${p}"/>`,
      `<circle cx="${r.x}" cy="${r.y}" r="8" fill="none" stroke="${INK}" stroke-width="1.2" opacity="${p}"/>`];
    if (narrow) {
      out.push(`<text x="${r.x + 12}" y="${r.y - 10}" font-family="IBM Plex Mono, monospace" font-size="13" font-weight="600" fill="${COLORS.PAPER}" stroke="${INK}" stroke-width="3" paint-order="stroke" opacity="${p}">${rank + 1}</text>`);
      return out.join('');
    }
    const Ax = -28, Bx = 22, dxl = r.x - Bx, dyl = r.y - ly, dl = Math.hypot(dxl, dyl) || 1, ux = dxl / dl, uy = dyl / dl;
    const tipX = r.x - ux * 10, tipY = r.y - uy * 10;
    const d = `M${Ax} ${ly}L${Bx} ${ly}L${tipX.toFixed(1)} ${tipY.toFixed(1)}`;
    const len = (Bx - Ax) + Math.hypot(tipX - Bx, tipY - ly);
    const ah = `M${tipX.toFixed(1)} ${tipY.toFixed(1)}L${(tipX - ux * 9 - uy * 4).toFixed(1)} ${(tipY - uy * 9 + ux * 4).toFixed(1)}L${(tipX - ux * 9 + uy * 4).toFixed(1)} ${(tipY - uy * 9 - ux * 4).toFixed(1)}Z`;
    const dash = `stroke-dasharray="${len.toFixed(1)}" stroke-dashoffset="${(len * (1 - p)).toFixed(1)}"`;
    const lab = clamp((p - 0.55) / 0.45);
    out.push(`<path d="${d}" fill="none" stroke="${COLORS.PAPER}" stroke-width="3.2" ${dash}/>`,
      `<path d="${d}" fill="none" stroke="${INK}" stroke-width="1.1" ${dash}/>`,
      `<path d="${ah}" fill="${INK}" stroke="${COLORS.PAPER}" stroke-width="0.8" opacity="${p >= 0.98 ? 1 : 0}"/>`,
      `<text x="-36" y="${ly - 4}" text-anchor="end" font-family="Instrument Sans, sans-serif" font-size="12.5" font-weight="600" fill="${INK}" opacity="${lab}">${rank === 0 ? 'Strongest Grad-CAM region' : 'Second Grad-CAM region'}</text>`,
      `<text x="-36" y="${ly + 12}" text-anchor="end" font-family="IBM Plex Mono, monospace" font-size="9.5" letter-spacing="0.6" fill="${MUTE}" opacity="${lab}">${esc(primary.toUpperCase())} · ${Math.round(r.share * 100)}% OF MAP WEIGHT</text>`);
    return out.join('');
  });
  return `<svg viewBox="0 0 440 440" width="${lensSize}" height="${lensSize}" aria-hidden="true" style="position:absolute;inset:0;overflow:visible;pointer-events:none">
    <defs><clipPath id="sfclip"><circle cx="220" cy="220" r="128"/></clipPath>
    <filter id="sfsoft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="${(cell * 0.8).toFixed(1)}"/></filter></defs>
    <g clip-path="url(#sfclip)" opacity="${ovOp}"><g filter="url(#sfsoft)">${cells.join('')}</g></g>${leaders.join('')}</svg>`;
}

type ExplainKind = { kind: 'map' | 'fallback' | 'none'; grid: number[][] | null; layer: string; reason: string };

function explainOf(result: ScreeningResult | null, primary: string | null): ExplainKind {
  if (!result || !primary) return { kind: 'none', grid: null, layer: '', reason: '' };
  const m = (result.maps ?? []).find((x) => x.disease === primary);
  if (!m) return { kind: 'fallback', grid: null, layer: '', reason: `The result has no map for ${primary}.` };
  if (!m.available) return { kind: 'fallback', grid: null, layer: '', reason: `Grad-CAM returned an empty map for ${primary}.` };
  if (!validGrid(m.grid)) return { kind: 'fallback', grid: null, layer: '', reason: 'The map failed validation (expected a square grid of values from 0 to 1).' };
  return { kind: 'map', grid: m.grid, layer: m.layer, reason: '' };
}

function Flow({ screening, photo, result, analyzeError, onRetry }: {
  screening: Screening; photo: string | null; result: ScreeningResult | null; analyzeError: unknown; onRetry: () => void;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const lensColRef = useRef<HTMLDivElement>(null);
  const lensBoxRef = useRef<HTMLDivElement>(null);
  const photoRef = useRef<HTMLImageElement>(null);
  const lensRef = useRef<HTMLDivElement>(null);
  const ovRef = useRef<HTMLDivElement>(null);
  const verdictRef = useRef<HTMLDivElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const logColRef = useRef<HTMLDivElement>(null);
  const readRef = useRef<HTMLDivElement>(null);
  const eyebrowRef = useRef<HTMLSpanElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const liveRef = useRef<HTMLParagraphElement>(null);
  const [narrow, setNarrow] = useState(false);
  const [replayKey, setReplayKey] = useState(0);
  const [final, setFinal] = useState(false);
  useFocusHeading<HTMLHeadingElement>();

  const eye = eyeCode(screening.eye) ?? 'R';
  const eyeW = eyeWord(screening.eye);
  const findings = useMemo(() => (result ? orderedFindings(result.findings) : []), [result]);
  const vals = findings.length === 4 ? findings.map((f) => f.probability) : [0, 0, 0, 0];
  const ths = findings.length === 4 ? findings.map((f) => f.threshold) : [0.5, 0.5, 0.5, 0.5];
  const pos = findings.map((f) => f.positive);
  const posNames = findings.filter((f) => f.positive).map((f) => f.disease);
  const primaryF = findings.filter((f) => f.positive).sort((a, b) => b.probability - a.probability)[0] ?? null;
  const primary = primaryF?.disease ?? null;
  const explain = useMemo(() => explainOf(result, primary), [result, primary]);
  const regionRows = explain.kind === 'map' && explain.grid ? regionsOf(explain.grid).map((r, i) => ({ n: i + 1, label: i === 0 ? 'Strongest region' : 'Second region', share: `${Math.round(r.share * 100)}% of weight` })) : [];
  const imgSize = 384;
  const verdict = posNames.length ? `Possible: ${posNames.join(', ')}.` : 'Not detected.';
  const verdictSub = primaryF ? `${posNames.length} OF 4 PAST THRESHOLD · ${primaryF.disease.toUpperCase()} ${pct(primaryF.probability)} vs ${pct(primaryF.threshold)}` : '0 OF 4 PAST THRESHOLD';

  useLayoutEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    setNarrow(stage.clientWidth < 1100);
    const ro = new ResizeObserver(([e]) => setNarrow(e.contentRect.width < 1100));
    ro.observe(stage);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const stage = stageRef.current!, lensCol = lensColRef.current!, lensBox = lensBoxRef.current!;
    const last: Record<string, string> = {};
    const put = (key: string, el: HTMLElement | null, value: string, prop: 'innerHTML' | 'textContent' = 'innerHTML') => {
      if (el && last[key] !== value) { last[key] = value; el[prop] = value; }
    };
    let raf = 0, dx: number | null = null;
    const measure = () => {
      if (narrow) { dx = 0; return; }
      const a = stage.getBoundingClientRect(), b = lensCol.getBoundingClientRect();
      dx = (a.left + a.width / 2) - (b.left + b.width / 2);
    };

    const frame = (t: number, waiting: boolean, wait: number) => {
      const lensSize = narrow ? Math.min(340, stage.clientWidth) : 520;
      const isFinal = !waiting && t >= T.settle;
      const lrState = waiting ? 'analyzing' : t < T.up ? 'uploading' : t < T.scanEnd ? 'analyzing' : 'readout';
      const reveal = waiting ? 0 : clamp((t - T.up) / 750 / 4) * 4;
      const scan = waiting ? sine((Math.sin(wait / 900) + 1) / 2) : sine((t - T.up) / (T.scanEnd - T.up));
      const e1 = ease((t - T.scanEnd) / T.move), e2 = ease((t - T.settle) / T.settleDur);
      const shift = narrow ? 0 : (dx ?? 0);
      const curr = DISEASES[Math.min(3, Math.floor(reveal))];

      stage.style.gridTemplateColumns = narrow ? 'minmax(0,1fr)' : isFinal ? 'minmax(0,1fr) 560px minmax(0,1fr)' : '560px minmax(0,1fr)';
      lensCol.style.gridColumn = narrow ? '1' : isFinal ? '2' : '1';
      lensCol.style.transformOrigin = `50% ${lensSize / 2}px`;
      lensCol.style.transform = waiting || t < T.scanEnd ? 'none'
        : !isFinal ? `translateX(${(shift * e1).toFixed(1)}px) scale(${(1 + 0.12 * e1).toFixed(4)})` : `scale(${(1.12 - 0.12 * e2).toFixed(4)})`;
      lensBox.style.width = lensBox.style.height = `${lensSize}px`;
      if (photoRef.current) Object.assign(photoRef.current.style, Object.fromEntries(Object.entries(lensPhotoStyle(lensSize)).map(([k, v]) => [k, typeof v === 'number' ? `${v}px` : v])));
      put('lens', lensRef.current, lensSVG({ size: lensSize, state: lrState, values: vals, thresholds: ths, eye, photoUnder: true, reveal: reveal.toFixed(3), scan: scan.toFixed(4), progress: clamp(t / T.up).toFixed(3), labelSize: narrow ? 13 : 10.5 }));
      put('ov', ovRef.current, explain.kind === 'map' && explain.grid && !waiting && t >= T.ov0 ? overlaySVG(explain.grid, primary!, t, lensSize, narrow) : '');

      const phase = waiting ? 'SLIT BEAM · RUNNING THE MODEL' : t < T.up ? 'PLACING PHOTO' : t < T.scanEnd ? `SLIT BEAM ${Math.round(scan * 100)}% · ${curr.toUpperCase()}` : !isFinal ? 'RESULT' : 'READOUT';
      put('eyebrow', eyebrowRef.current, `NEW SCREENING · ${phase}`, 'textContent');
      put('title', titleRef.current, `${waiting || t < T.scanEnd ? 'Analyzing ' : ''}${screening.patient_ref}, ${eyeW} eye`, 'textContent');
      put('live', liveRef.current, waiting ? 'Analyzing. Running the model.' : t < T.up ? 'Photo placed.' : t < T.scanEnd ? `Analyzing ${curr}.`
        : `Analysis complete. ${posNames.length ? `Possible: ${posNames.join(', ')}.` : 'Not detected.'}${explain.kind === 'fallback' ? ' Explanation map unavailable.' : ''}`, 'textContent');

      if (verdictRef.current) verdictRef.current.style.opacity = String(!waiting && t >= T.scanEnd ? ease((t - T.verdict) / 600) : 0);
      const lc = logColRef.current!;
      lc.style.gridColumn = narrow ? '1' : '2';
      lc.style.gridRow = narrow ? '2' : '1';
      lc.style.display = isFinal ? 'none' : 'flex';
      lc.style.opacity = waiting || t < T.scanEnd ? '1' : (1 - e1).toFixed(3);
      const done = (i: number) => reveal - i >= 1, meas = (i: number) => (waiting && i === 0) || (reveal - i > 0 && reveal - i < 1);
      const log: [string, string, string][] = [
        ['Photo placed', '✓', COLORS.INK],
        [`crop_fundus → ${imgSize} × ${imgSize}`, '✓', COLORS.INK],
        ...DISEASES.map((n, i): [string, string, string] => (!waiting && done(i)) ? [n, `${pct(vals[i])} ${pos[i] ? '▲ POSSIBLE' : '○ CLEAR'}`, pos[i] ? COLORS.VT : COLORS.G]
          : meas(i) ? [n, '◐ MEASURING', COLORS.OT] : [n, 'QUEUED', COLORS.MUTE]),
      ];
      put('log', logRef.current, log.map(([a, b, c]) => `<div style="color:${c}"><span>${esc(a)}</span><b>${b}</b></div>`).join(''));
      const rd = readRef.current!;
      rd.style.gridColumn = narrow ? '1' : '3';
      rd.style.gridRow = narrow ? '2' : '1';
      rd.style.justifySelf = narrow ? 'center' : 'end';
      rd.style.maxWidth = narrow ? '560px' : '420px';
      rd.style.display = isFinal ? 'flex' : 'none';
      rd.style.opacity = String(ease((t - T.read0) / 800));
      setFinal(isFinal);
    };

    if (!result) {
      // The model is running: sweep the slit beam until the result arrives
      const w0 = performance.now();
      const wait = (now: number) => { frame(0, true, now - w0); raf = requestAnimationFrame(wait); };
      if (reducedMotion()) frame(0, true, 0); else raf = requestAnimationFrame(wait);
      return () => cancelAnimationFrame(raf);
    }
    if (reducedMotion()) { frame(T.end, false, 0); return; }
    const start = replayKey === 0 && screening.status !== 'pending' && !analyzeError ? 0 : T.up;
    const t0 = performance.now() - start;
    const step = (now: number) => {
      const t = now - t0;
      if (t >= T.scanEnd && dx == null) measure();
      frame(Math.min(t, T.end), false, 0);
      if (t < T.end) raf = requestAnimationFrame(step);
    };
    frame(start, false, 0);
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, narrow, replayKey]);

  const lensAria = result
    ? `Lens readout for ${screening.patient_ref}, ${eyeW} eye. ` + findings.map((f) => `${f.disease} ${pct(f.probability)}, threshold ${pct(f.threshold)}, ${f.positive ? 'positive' : 'not detected'}`).join('; ') + '.'
    : `Analyzing ${screening.patient_ref}, ${eyeW} eye.`;
  const offline = analyzeError ? apiError(analyzeError)?.code === 'MODEL_OFFLINE' : false;

  return (
    <main id="main" style={{ display: 'flex', flexDirection: 'column' }}>
      <header className="page-head">
        <div className="titles"><span className="eyebrow" ref={eyebrowRef} /><h1 ref={titleRef} tabIndex={-1} /></div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <button type="button" className="btn" style={{ fontSize: 11.5 }} disabled={!result} onClick={() => setReplayKey((k) => k + 1)}>
            <span aria-hidden="true" className="mono">↺</span>Replay
          </button>
        </div>
      </header>
      <p className="sr-only" aria-live="polite" ref={liveRef} />
      <div className="flow-main">
        {!!analyzeError && (
          <div className={`notice ${offline ? 'notice-amber' : 'notice-red'}`} role="alert">
            <span className="label">{offline ? '◐ MODEL OFFLINE' : isOffline(analyzeError) ? '▲ ERR · NO RESPONSE' : '▲ ERR · ANALYSIS FAILED'}</span>
            <p>{offline ? 'Model offline: no result for this image. Nothing has been made up; try again when the model is running.' : apiErrorMessage(analyzeError)}</p>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <button type="button" className="btn" onClick={onRetry}>Try again</button>
              <Link className="btn" to={`/screenings/${screening.id}`}>Open screening</Link>
            </div>
          </div>
        )}
        <div className="stage" ref={stageRef}>
          <div className="lens-col" ref={lensColRef}>
            <div className="lens-box" ref={lensBoxRef} role="img" aria-label={lensAria}>
              {photo && <img alt="" ref={photoRef} src={photo} />}
              <div className="layer" ref={lensRef} />
              <div className="layer" ref={ovRef} style={{ overflow: 'visible' }} />
            </div>
            <div className="verdict" ref={verdictRef} style={{ opacity: 0 }}>
              <div className="verdict-line"><span aria-hidden="true" className="glyph" style={{ color: posNames.length ? COLORS.V : COLORS.G }}>{posNames.length ? '▲' : '○'}</span><span className="words">{verdict}</span></div>
              <span className="sub">{verdictSub}</span>
            </div>
          </div>
          <div className="log-col" ref={logColRef}>
            <div className="tag">
              <div className="tag-head"><span>SPECIMEN TAG</span><span className="mute">{result ? (result.demo ? 'DEMO RESULT · PRECOMPUTED, NOT LIVE' : `LIVE MODEL OUTPUT · ${result.latency_ms} MS`) : 'MODEL RUNNING'}</span></div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                <span className="mono" style={{ font: '600 30px/1 var(--mono)' }}>{screening.patient_ref}</span>
                <EyeDots eye={eyeCode(screening.eye)} />
                <span className="mono mute" style={{ marginLeft: 'auto', fontSize: 11, overflowWrap: 'anywhere' }}>{screening.image?.name ?? ''}</span>
              </div>
            </div>
            <div className="log" ref={logRef} />
          </div>
          <div className="read-col" ref={readRef} style={{ display: 'none' }} aria-hidden={!final}>
            <div className="readings-head"><span>READINGS</span><span>PROB · THRESHOLD</span></div>
            {byProbability(findings).map((f) => (
              <div key={f.code} className="reading">
                <div className="reading-top"><span className="name">{f.disease}</span><span className={`res ${f.positive ? 'c-pos' : 'c-clr'}`}>{f.positive ? '▲ POSITIVE' : '○ NOT DETECTED'}</span></div>
                <div className="reading-nums"><span className="prob">{pct(f.probability)}</span><span className="mute">threshold {pct(f.threshold)}</span></div>
              </div>
            ))}
            {explain.kind === 'map' && (
              <div className="panel" style={{ border: '1px solid var(--ink)' }}>
                <span className="k c-pos">▲ ATTENTION MAP · GRAD-CAM</span>
                <p>Tinted regions weighed most in the model’s {primary} score{explain.layer ? ` (layer ${explain.layer})` : ''}. They show where the model looked, not a confirmed lesion.</p>
                {regionRows.map((rg) => <div key={rg.n} className="region"><span style={{ fontWeight: 600 }}>{rg.n}</span><span>{rg.label}</span><span>{rg.share}</span></div>)}
              </div>
            )}
            {explain.kind === 'fallback' && (
              <div className="panel" style={{ border: '1px dashed var(--ink)' }}>
                <span className="k c-rev">◐ EXPLANATION MAP UNAVAILABLE</span>
                <p>No regions are highlighted, because there is no reliable Grad-CAM map for this result. The probabilities above are unaffected.</p>
                <span className="why">{explain.reason}</span>
              </div>
            )}
            {explain.kind === 'none' && (
              <div className="panel" style={{ border: '1px solid var(--rule)' }}>
                <span className="k c-clr">○ NO OVERLAY</span>
                <p>No disease passed its threshold, so there is no positive result to explain.</p>
              </div>
            )}
            <div className="scope" style={{ marginTop: 14 }}>Screens these four diseases only; other eye conditions are not checked.</div>
            <Link className="link" style={{ marginTop: 18 }} to={`/screenings/${screening.id}`}>Open reviewer’s notes →</Link>
          </div>
        </div>
      </div>
    </main>
  );
}

export function ScanPage() {
  const rawId = useParams().id;
  const id = Number(rawId);
  const screening = useScreening(id);
  const image = useScreeningImage(id, photoVersion(screening.data), !!screening.data?.has_image);
  const analyze = useAnalyzeScreening();
  const started = useRef(false);
  const s = screening.data;

  useEffect(() => { if (s) document.title = `${s.patient_ref}, ${eyeWord(s.eye)} eye · RetinaScreen`; }, [s]);
  useEffect(() => {
    if (!s || started.current || s.result || !s.has_image) return;
    started.current = true;
    analyze.mutate(id);
  }, [s, id, analyze]);

  if (!Number.isInteger(id) || id <= 0) return <QueryError error={{ response: { status: 404 } }} path={`/screenings/${rawId}/scan`} onRetry={() => undefined} />;
  if (screening.isPending) return <Loading label="LOADING SCREENING" />;
  if (screening.error) return <QueryError error={screening.error} path={`/screenings/${id}`} onRetry={() => screening.refetch()} />;
  if (!s!.has_image) return <Navigate to={`/screenings/${id}`} replace />;
  if (image.isPending && !image.url) return <Loading label="PLACING PHOTO" />;
  const result = analyze.data ?? s!.result ?? null;
  return (
    <Flow screening={s!} photo={image.url} result={result} analyzeError={analyze.error}
      onRetry={() => { analyze.reset(); analyze.mutate(id); }} />
  );
}
