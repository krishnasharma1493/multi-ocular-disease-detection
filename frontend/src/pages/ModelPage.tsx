import { useEffect } from 'react';
import { useModelCard } from '../features/model/api';
import type { DiseaseCard } from '../lib/api/types';
import { dayStamp, num2, sentence } from '../lib/format';
import { Loading, QueryError, useFocusHeading } from '../components/States';

const C = { x: 120, y: 122 }, R = 86;
const ang = (v: number) => -135 + (Math.max(0.5, Math.min(1, v)) - 0.5) / 0.5 * 270;
const pt = (r: number, a: number): [string, string] => { const t = (a * Math.PI) / 180; return [(C.x + r * Math.sin(t)).toFixed(2), (C.y - r * Math.cos(t)).toFixed(2)]; };

function Gauge({ d }: { d: DiseaseCard }) {
  const s = pt(R, -135), e = pt(R, 135);
  const ticks = Array.from({ length: 21 }, (_, i) => {
    const v = 0.5 + i * 0.025, M = i % 4 === 0, a = ang(v), p = pt(M ? 74 : 80, a), q = pt(R, a);
    return <line key={i} x1={p[0]} y1={p[1]} x2={q[0]} y2={q[1]} stroke="currentColor" strokeWidth={M ? 1.6 : 0.8} />;
  });
  const labs = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0].map((v) => {
    const p = pt(60, ang(v));
    return <text key={v} x={p[0]} y={p[1]} textAnchor="middle" dominantBaseline="central" fontFamily="IBM Plex Mono, monospace" fontSize="10" fill="var(--graphite)">{v === 1 ? '1.0' : String(v).slice(1)}</text>;
  });
  const n = d.test_roc_auc != null ? pt(80, ang(d.test_roc_auc)) : null;
  const ap = d.test_ap != null ? [pt(R + 3, ang(d.test_ap)), pt(R + 13, ang(d.test_ap) - 3.5), pt(R + 13, ang(d.test_ap) + 3.5)] : null;
  const figs: [string, string][] = [
    ['AUC', num2(d.test_roc_auc)], ['AP', num2(d.test_ap)], ['THRESHOLD', d.threshold == null ? '—' : `${Math.round(d.threshold * 100)}%`],
    ['PRECISION', num2(d.test_precision)], ['RECALL', num2(d.test_recall)], ['F1', num2(d.test_f1)],
    ['POSITIVES', d.test_positives == null ? '—' : String(d.test_positives)],
  ];
  const odir: [string, string][] = [['ODIR AP', num2(d.odir_ap)], ['ODIR AUC', num2(d.odir_roc_auc)]];
  const weak = d.odir_ap != null && d.odir_ap < 0.6;
  return (
    <div className="gauge">
      <h3>{sentence(d.disease)}</h3>
      <svg width="240" height="210" viewBox="0 0 240 210" style={{ overflow: 'visible' }} role="img" aria-label={`${d.disease}: test AUC ${num2(d.test_roc_auc)}, AP ${num2(d.test_ap)}`}>
        <path d={`M${s}A${R} ${R} 0 1 1 ${e}`} fill="none" stroke="currentColor" strokeWidth="1" />
        {ticks}{labs}
        {ap && <path d={`M${ap[0]}L${ap[1]}L${ap[2]}Z`} fill="currentColor" />}
        {n && <line x1="120" y1="122" x2={n[0]} y2={n[1]} stroke="currentColor" strokeWidth="2" strokeLinecap="round" />}
        <circle cx="120" cy="122" r="6" fill="var(--paper)" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <dl className="figs">
        {figs.map(([k, v]) => <div key={k}><dt>{k}</dt><dd aria-label={v === '—' ? 'not available' : undefined}>{v}</dd></div>)}
        <div className="figs-sub"><dt>EVERYDAY ODIR PHOTOS ONLY</dt><dd /></div>
        {odir.map(([k, v]) => <div key={k} className={weak && k === 'ODIR AP' ? 'weak' : undefined}><dt>{k}</dt><dd aria-label={v === '—' ? 'not available' : undefined}>{v}</dd></div>)}
      </dl>
    </div>
  );
}

export function ModelPage() {
  const card = useModelCard();
  const h = useFocusHeading<HTMLHeadingElement>(!!card.data);
  useEffect(() => { document.title = 'Model · RetinaScreen'; }, [card.data]);
  if (card.isPending) return <Loading label="READING THE CALIBRATION CERTIFICATE" />;
  if (card.error) return <QueryError error={card.error} path="/model" onRetry={() => card.refetch()} />;
  const m = card.data;
  const pretty = m.model_name === 'efficientnet_b0' ? 'EfficientNet-B0' : m.model_name;
  const weakest = m.diseases.filter((d) => d.odir_ap != null).sort((a, b) => (a.odir_ap ?? 1) - (b.odir_ap ?? 1))[0];
  const role = (ds: string[]) => (ds.length >= 3 ? 'multi-disease' : ds.map((x) => x.toLowerCase()).join(', ') || 'normal controls');
  return (
    <main id="main">
      <div className="cert-wrap"><div className="cert-outer"><div className="cert">
        <div className="cert-top">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <span className="eyebrow" style={{ letterSpacing: '0.18em' }}>INSTRUMENT CALIBRATION CERTIFICATE</span>
            <h1 ref={h} tabIndex={-1}>Certificate of calibration</h1>
          </div>
          <div className="serial">
            <span className="eyebrow">CHECKPOINT</span>
            <b>RS-CAL-{(m.checkpoint_sha256 ?? 'UNKNOWN').slice(0, 8).toUpperCase()}</b>
            <span className="eyebrow" style={{ letterSpacing: '0.12em' }}>{m.checkpoint_modified ? `ISSUED ${dayStamp(new Date(m.checkpoint_modified))}` : 'ISSUE DATE UNKNOWN'}</span>
            <span className={`live-badge ${m.live ? 'on' : 'off'}`}><i aria-hidden="true" />{m.live ? `LIVE · ${(m.device ?? '').toUpperCase()}` : 'OFFLINE · STORED RESULTS ONLY'}</span>
          </div>
        </div>
        <p className="cert-line">
          Model {pretty} · <span className="n">{m.img_size ?? '—'}</span> px · {m.test_images
            ? <>tested on <span className="n">{m.test_images}</span> held-out eyes from unseen patients</>
            : 'no held-out test metrics found next to the checkpoint'}
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div className="eyebrow" style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', letterSpacing: '0.14em' }}>
            <span>GAUGES · ONE PER DISEASE</span><span>NEEDLE = AUC · ▼ = AP · SCALE 0.5–1.0</span>
          </div>
          <div className="gauges">{m.diseases.map((d) => <Gauge key={d.code} d={d} />)}</div>
        </div>
        {weakest && weakest.odir_ap != null && weakest.odir_ap < 0.6 && (
          <div className="notice notice-amber">
            <span className="label">◐ WEAKEST NUMBER</span>
            <p>{sentence(weakest.disease)} on everyday ODIR camp photos scores an AP of {num2(weakest.odir_ap)}, far below its {num2(weakest.test_ap)} on the full test set. Treat {weakest.disease.toLowerCase()} results on camp photos with extra caution.</p>
          </div>
        )}
        <div className="cert-foot">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <span className="label">SOURCE DATASETS · {m.sources.length}</span>
            {m.sources.length ? m.sources.map((d, i) => (
              <div key={d.name} className="ds"><span className="mute">{String(i + 1).padStart(2, '0')}</span><b>{d.name}</b><span>{role(d.diseases)}</span></div>
            )) : <span className="mute" style={{ fontSize: 13 }}>Not recorded in metrics.json.</span>}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <span className="label">KNOWN LIMITATIONS</span>
            <ol className="limits">{m.limitations.map((l) => <li key={l}>{l}</li>)}</ol>
          </div>
          <div className="seal">
            <svg width="150" height="150" viewBox="0 0 150 150" style={{ transform: 'rotate(-8deg)' }} role="img" aria-label="Seal: research prototype, not clinically validated">
              <defs><path id="sealArc" d="M75 75 m-54 0 a54 54 0 1 1 108 0 a54 54 0 1 1 -108 0" /></defs>
              <circle cx="75" cy="75" r="72" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <circle cx="75" cy="75" r="66" fill="none" stroke="currentColor" strokeWidth="0.75" />
              <circle cx="75" cy="75" r="40" fill="none" stroke="currentColor" strokeWidth="0.75" />
              <circle cx="75" cy="75" r="22" fill="none" stroke="currentColor" strokeWidth="5" />
              <circle cx="75" cy="75" r="3" fill="currentColor" />
              <text fontFamily="IBM Plex Mono, monospace" fontSize="8.4" letterSpacing="1.6" fill="currentColor"><textPath href="#sealArc">RESEARCH PROTOTYPE · NOT CLINICALLY VALIDATED ·</textPath></text>
            </svg>
            <span className="eyebrow" style={{ fontSize: 10, lineHeight: 1.4, letterSpacing: '0.1em', textAlign: 'center' }}>RETINASCREEN<br />RESEARCH TEAM</span>
          </div>
        </div>
      </div></div></div>
    </main>
  );
}
