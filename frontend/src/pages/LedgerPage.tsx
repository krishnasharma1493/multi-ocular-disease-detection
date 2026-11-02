import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useScreeningStats, useScreenings } from '../features/screenings/api';
import type { Screening } from '../lib/api/types';
import { COLORS, DISEASES, STATUS_LABEL, dayStamp, eyeCode, eyeWord, hhmm, sameDay, summarize, type Status, type Summary } from '../lib/format';
import { EyeDots, Lens } from '../components/Lens';
import { Loading, QueryError, useFocusHeading } from '../components/States';

type Item = { s: Screening; m: Summary };
const eyesLabel = (n: number) => `${n} ${n === 1 ? 'eye' : 'eyes'}`;
const ORDER: Status[] = ['possible', 'review', 'clear', 'pending'];

function Ruler({ items }: { items: Item[] }) {
  const start = new Date(items[0].m.created); start.setMinutes(0, 0, 0);
  const lastHour = new Date(items[items.length - 1].m.created); lastHour.setMinutes(0, 0, 0);
  const hours = Math.max(1, Math.round((lastHour.getTime() - start.getTime()) / 3600000) + 1);
  const span = hours * 60;
  const seen = new Set<string>();
  let lastLabel = -Infinity;
  const ticks = items.map(({ s, m }) => {
    const left = ((m.created.getTime() - start.getTime()) / 60000) / span * 100;
    const g = STATUS_LABEL[m.status];
    let lab = '';
    if (!seen.has(s.patient_ref) && left - lastLabel >= 8) { lab = s.patient_ref; lastLabel = left; }
    seen.add(s.patient_ref);
    return (
      <span key={s.id} className="tick" style={{ left: `${left.toFixed(2)}%` }}>
        <span className="g" style={{ color: g.color }}>{g.glyph}</span>
        <span className="bar" style={{ background: g.color }} />
        <span className="lab">{lab}</span>
      </span>
    );
  });
  const step = hours > 10 ? 2 : 1;
  const labels = [];
  for (let i = 0; i <= hours; i += step) {
    labels.push(<span key={i} className="hour" style={{ left: `${(i / hours * 100).toFixed(2)}%` }}>{hhmm(new Date(start.getTime() + i * 3600000))}</span>);
  }
  return (
    <div className="axis-wrap" aria-hidden="true">
      <div className="axis" style={{ top: 64, height: 1, background: 'var(--ink)' }} />
      <div className="axis ruler-minor" style={{ top: 56, height: 8, backgroundSize: `${(100 / hours / 12).toFixed(3)}% 100%` }} />
      <div className="axis ruler-major" style={{ top: 48, height: 16, backgroundSize: `${(100 / hours).toFixed(3)}% 100%` }} />
      <div className="axis" style={{ top: 0, bottom: 0 }}>{ticks}{labels}</div>
    </div>
  );
}

function FindingsChart({ items }: { items: Item[] }) {
  const n = items.length, radii = [150, 120, 90, 60];
  const counts = DISEASES.map((name) => {
    let pos = 0, near = 0;
    items.forEach(({ m }) => {
      if (m.rows.find((r) => r.disease === name)?.positive) pos++;
      else if (m.near?.disease === name) near++;
    });
    return { name, pos, near };
  });
  const short: Record<string, string> = { 'Diabetic Retinopathy': 'DIABETIC RET.' };
  const aria = `Findings by disease, of ${eyesLabel(n)}: ` + counts.map((c) => `${c.name} ${c.pos} possible${c.near ? `, ${c.near} close to notch` : ''}`).join('; ') + '.';
  return (
    <svg width="360" height="360" viewBox="0 0 340 340" role="img" aria-label={aria} className="rings">
      {radii.map((r) => (
        <g key={r}>
          <circle cx="170" cy="170" r={r} fill="none" stroke="#E4DDCD" strokeWidth="14" />
          <circle cx="170" cy="170" r={r + 7} fill="none" stroke={COLORS.INK} strokeWidth="0.8" />
          <circle cx="170" cy="170" r={r - 7} fill="none" stroke={COLORS.INK} strokeWidth="0.8" />
        </g>
      ))}
      {counts.map((c, i) => {
        const r = radii[i], unit = (2 * Math.PI * r) / Math.max(n, 1);
        return (
          <g key={c.name} transform="rotate(-90 170 170)">
            {c.pos > 0 && <circle cx="170" cy="170" r={r} fill="none" stroke={COLORS.V} strokeWidth="14" strokeDasharray={`${(unit * c.pos).toFixed(1)} 10000`} />}
            {c.near > 0 && <circle cx="170" cy="170" r={r} fill="none" stroke={COLORS.O} strokeWidth="14" strokeDasharray={`${(unit * c.near).toFixed(1)} 10000`} strokeDashoffset={(-unit * c.pos).toFixed(1)} />}
          </g>
        );
      })}
      {n > 1 && n <= 72 && (
        <g stroke={COLORS.PAPER} strokeWidth="2.5">
          {Array.from({ length: n }, (_, i) => {
            const a = (i / n) * 2 * Math.PI;
            return <line key={i} x1={170 + 160 * Math.sin(a)} y1={170 - 160 * Math.cos(a)} x2={170 + 50 * Math.sin(a)} y2={170 - 50 * Math.cos(a)} />;
          })}
        </g>
      )}
      <g fontFamily="IBM Plex Mono, monospace" fontSize="10.5" fontWeight="500" textAnchor="end" fill={COLORS.INK} style={{ whiteSpace: 'pre' }}>
        {counts.map((c, i) => (
          <text key={c.name} x="162" y={[8, 40, 70, 100][i]}>{`${short[c.name] ?? c.name.toUpperCase()}  ${c.pos}${c.near ? ` +${c.near}◐` : ''}`}</text>
        ))}
      </g>
      <text x="170" y="166" textAnchor="middle" fontFamily="Newsreader, serif" fontSize="34" fontWeight="500" fill={COLORS.INK}>{n}</text>
      <text x="170" y="186" textAnchor="middle" fontFamily="IBM Plex Mono, monospace" fontSize="9.5" letterSpacing="1.5" fill={COLORS.MUTE}>{n === 1 ? 'EYE' : 'EYES'}</text>
    </svg>
  );
}

function ItemRow({ s, m }: Item) {
  const g = STATUS_LABEL[m.status];
  const eye = eyeCode(s.eye);
  return (
    <Link className="item" to={`/screenings/${s.id}`} aria-label={`${s.patient_ref}, ${eyeWord(s.eye)} eye, ${hhmm(m.created)}. ${m.verdict}. ${m.sub}.${s.latest_review === 'disagree' ? ' Reviewer disagrees.' : ''}`}>
      <span className="hole" aria-hidden="true" />
      <span className="lens-thumb" aria-hidden="true">
        {m.status === 'pending' ? <Lens size={72} state="empty" /> : <Lens size={72} values={m.vals} thresholds={m.ths} eye={eye ?? 'R'} />}
      </span>
      <span className="who" aria-hidden="true">
        <span className="ref" title={s.patient_ref}>{s.patient_ref}</span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}><EyeDots eye={eye} dot={9} /><span className="mono mute" style={{ fontSize: 11 }}>{hhmm(m.created)}</span></span>
      </span>
      <span className="what" aria-hidden="true"><b>{m.verdict}</b><span>{m.sub}</span></span>
      <span className={`state ${g.cls}`} aria-hidden="true"><span>{g.word}</span>{s.latest_review === 'disagree' ? <span className="stamp-sm">✕ REVIEWER: DISAGREE</span> : s.status === 'reviewed' && <span className="mute" style={{ fontSize: 10 }}>✓ REVIEWED</span>}</span>
    </Link>
  );
}

export function LedgerPage() {
  const list = useScreenings({ limit: 100 });
  const stats = useScreeningStats();
  const [small, setSmall] = useState(() => window.innerWidth < 760);
  useEffect(() => {
    const on = () => setSmall(window.innerWidth < 760);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  useEffect(() => { document.title = 'Ledger · RetinaScreen'; }, [list.data, stats.data]);
  const h = useFocusHeading<HTMLHeadingElement>(!!list.data);

  if (list.isPending || stats.isPending) return <Loading label="OPENING THE LEDGER" />;
  if (list.error || stats.error) return <QueryError error={list.error ?? stats.error} path="/" onRetry={() => { list.refetch(); stats.refetch(); }} />;

  const now = new Date();
  const items: Item[] = list.data.data.map((s) => ({ s, m: summarize(s) }))
    .filter((it) => sameDay(it.m.created, now))
    .sort((a, b) => a.m.created.getTime() - b.m.created.getTime());
  const n = items.length;
  const st = stats.data;
  const totals = `${st.total} IN ALL · ${st.flagged} FLAGGED · ${st.by_status.pending} AWAITING ANALYSIS`;

  if (!n) {
    return (
      <main id="main">
        <div className="ledger-head">
          <div className="meta"><span>LEDGER · {dayStamp(now)} · NO SCREENINGS YET</span><span>{totals}</span></div>
          <h1 ref={h} tabIndex={-1}>Today’s camp — 0 eyes screened</h1>
        </div>
        <div className="ruler-row empty">
          <div className="axis-wrap" aria-hidden="true">
            <div className="axis" style={{ top: 64, height: 1, background: 'var(--ink)' }} />
            <div className="axis ruler-minor" style={{ top: 56, height: 8, backgroundSize: '5% 100%' }} />
          </div>
          <Link className="new-btn" to="/screenings/new"><span aria-hidden="true">+</span>New screening</Link>
        </div>
        <div className="empty-hero">
          <Lens size={small ? 260 : 380} state="empty" />
          <div className="stack-words">
            <span className="w1">NO EYES</span><span className="w2">SCREENED</span><span className="w3">YET TODAY</span>
            <p>Each photo you analyze is filed here as a specimen tag, ordered by urgency.{st.total > 0 && <> Earlier days are under <Link to="/screenings">Screenings</Link>.</>}</p>
          </div>
        </div>
      </main>
    );
  }

  const byRef: Record<string, Set<string>> = {};
  items.forEach(({ s }) => { (byRef[s.patient_ref] ??= new Set()).add(s.eye); });
  const patients = Object.keys(byRef).length;
  const both = Object.values(byRef).every((set) => set.has('left') && set.has('right'));
  const urgency = (m: Summary) => (m.rows.length ? Math.max(...m.rows.map((r) => r.probability - r.threshold)) : -2);
  const groups = ORDER.map((key) => ({ key, g: STATUS_LABEL[key], list: items.filter((it) => it.m.status === key).sort((a, b) => urgency(b.m) - urgency(a.m)) }))
    .filter((grp) => grp.list.length);
  const analyzed = items.filter((it) => it.m.status !== 'pending');

  return (
    <main id="main">
      <div className="ledger-head">
        <div className="meta">
          <span>LEDGER · {dayStamp(now)} · {hhmm(items[0].m.created)} – {hhmm(items[n - 1].m.created)}</span>
          <span>{patients} {patients === 1 ? 'PATIENT' : 'PATIENTS'} · {both ? 'BOTH EYES' : eyesLabel(n).toUpperCase()}</span>
        </div>
        <h1 ref={h} tabIndex={-1}>Today’s camp — {eyesLabel(n)} screened</h1>
      </div>
      <div className="ruler-row"><Ruler items={items} /><Link className="new-btn" to="/screenings/new"><span aria-hidden="true">+</span>New screening</Link></div>
      <div className="ledger-grid">
        <section aria-labelledby="queue-h" className="col">
          <div className="section-head"><h2 id="queue-h">Triage queue</h2><span className="eyebrow">ORDERED BY URGENCY</span></div>
          {groups.map(({ key, g, list: rows }) => (
            <div key={key} className="group">
              <div className={`group-head ${g.cls}`}><span>{g.head}</span><span>{rows.length}</span></div>
              {rows.map((it) => <ItemRow key={it.s.id} {...it} />)}
            </div>
          ))}
          <Link className="link" to="/screenings">All screenings, search and filters →</Link>
        </section>
        <section aria-labelledby="find-h" className="col" style={{ gap: 24 }}>
          <div className="section-head"><h2 id="find-h">Findings by disease</h2><span className="eyebrow">OF {eyesLabel(analyzed.length).toUpperCase()}</span></div>
          {analyzed.length ? <FindingsChart items={analyzed} /> : <p className="mute">No eye analyzed yet today.</p>}
          <div className="legend"><span>ONE DIVISION = ONE EYE</span><span><span className="c-pos">▲</span> POSSIBLE · <span className="c-rev">◐</span> REVIEW</span></div>
          <div className="legend" style={{ borderTop: 0, paddingTop: 0 }}><span>{totals}</span></div>
        </section>
      </div>
    </main>
  );
}
