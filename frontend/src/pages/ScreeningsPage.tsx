import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useScreenings } from '../features/screenings/api';
import { parseUtc, type ScreeningStatus } from '../lib/api/types';
import { STATUS_LABEL, dayStamp, eyeCode, eyeWord, hhmm, summarize } from '../lib/format';
import { EyeDots, Lens } from '../components/Lens';
import { QueryError, useFocusHeading } from '../components/States';

const LIMIT = 20;
const STATUSES: [string, string][] = [['', 'All'], ['pending', 'Pending'], ['analyzed', 'Analyzed'], ['reviewed', 'Reviewed']];

export function ScreeningsPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const status = (params.get('status') ?? '') as ScreeningStatus | '';
  const page = Math.max(1, Number(params.get('page')) || 1);
  const [text, setText] = useState(q);
  const h = useFocusHeading<HTMLHeadingElement>();
  useEffect(() => setText(q), [q]);

  const update = (next: Record<string, string>) => {
    const merged = { q, status, page: String(page), ...next };
    const clean = Object.fromEntries(Object.entries(merged).filter(([k, v]) => v && !(k === 'page' && v === '1')));
    setParams(clean);
  };
  // Debounced search; a new search or filter starts at page 1
  useEffect(() => {
    if (text === q) return;
    const t = setTimeout(() => update({ q: text.trim(), page: '1' }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  const list = useScreenings({ page, limit: LIMIT, q: q || undefined, status: status || undefined });
  const filtered = !!q || !!status;
  const data = list.data;
  useEffect(() => { document.title = 'Screenings · RetinaScreen'; }, [data]);

  if (list.error && !data) return <QueryError error={list.error} path="/screenings" onRetry={() => list.refetch()} />;
  const total = data?.pagination.total ?? 0;
  const from = total ? (page - 1) * LIMIT + 1 : 0;
  const to = Math.min(total, page * LIMIT);
  const lastPage = data?.pagination.total_pages ?? 1;

  return (
    <main id="main">
      <div className="page-head">
        <div className="titles"><span className="eyebrow">SCREENINGS · ALL DAYS</span><h1 ref={h} tabIndex={-1}>All screenings</h1></div>
        <Link className="btn-primary" style={{ height: 52, width: 240 }} to="/screenings/new"><span>+ New screening</span><span className="glyph" aria-hidden="true">→</span></Link>
      </div>
      <div className="list-wrap">
        <div className="filters" role="search">
          <div className="field search">
            <label htmlFor="q" className="label">SEARCH PATIENT REF</label>
            <input id="q" className="line-input mono" type="search" value={text} placeholder="P-01" maxLength={40} onChange={(e) => setText(e.target.value)} />
          </div>
          <fieldset className="field">
            <legend className="label">STATUS</legend>
            <div className="seg" role="radiogroup" aria-label="Status filter">
              {STATUSES.map(([v, label]) => (
                <button key={v} type="button" role="radio" aria-checked={status === v} onClick={() => update({ status: v, page: '1' })}>{label}</button>
              ))}
            </div>
          </fieldset>
        </div>

        <div className="list-meta eyebrow" aria-live="polite">
          {list.isFetching && !data ? 'LOADING' : total ? `SHOWING ${from}–${to} OF ${total}` : ''}
          {list.error && data ? ' · ▲ REFRESH FAILED' : ''}
        </div>

        {!data ? (
          <div className="rows" aria-busy="true">{Array.from({ length: 5 }, (_, i) => <div key={i} className="row skeleton" />)}</div>
        ) : data.data.length === 0 ? (
          <div className="empty-list">
            <span className="w2 serif">{filtered || page > 1 ? 'No screenings match these filters' : 'No screenings yet'}</span>
            {filtered || page > 1
              ? <button type="button" className="btn" onClick={() => { setText(''); setParams({}); }}>Clear filters</button>
              : <Link className="btn" to="/screenings/new">New screening</Link>}
          </div>
        ) : (
          <table className="table">
            <caption className="sr-only">Screenings, newest first</caption>
            <thead><tr><th scope="col"><span className="sr-only">Readout</span></th><th scope="col">Patient ref</th><th scope="col">Eye</th><th scope="col">Status</th><th scope="col">Result</th><th scope="col">Created</th></tr></thead>
            <tbody>
              {data.data.map((s) => {
                const m = summarize(s);
                const g = STATUS_LABEL[m.status];
                const created = parseUtc(s.created_at);
                return (
                  <tr key={s.id}>
                    <td className="thumb" aria-hidden="true">{m.status === 'pending' ? <Lens size={48} state="empty" /> : <Lens size={48} values={m.vals} thresholds={m.ths} eye={eyeCode(s.eye) ?? 'R'} />}</td>
                    <td><Link className="row-link mono" to={`/screenings/${s.id}`} title={s.patient_ref}>{s.patient_ref}</Link></td>
                    <td><span className="sr-only">{eyeWord(s.eye)} eye</span><span aria-hidden="true"><EyeDots eye={eyeCode(s.eye)} dot={9} /></span></td>
                    <td><span className={`tagword ${g.cls}`}>{g.word}</span>{s.status === 'reviewed' && <span className="tagword mute"> · ✓ REVIEWED</span>}</td>
                    <td className="result"><b>{m.verdict}</b>{m.positives.length > 0 && <span className="chips">{m.positives.map((f) => <span key={f.code} className="chip">{f.disease}</span>)}</span>}</td>
                    <td className="mono mute when-cell">{hhmm(created)} · {dayStamp(created)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {data && lastPage > 1 && (
          <nav className="pager" aria-label="Pages">
            <button type="button" className="btn" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>← Previous</button>
            <span className="eyebrow">PAGE {page} OF {lastPage}</span>
            <button type="button" className="btn" disabled={page >= lastPage} onClick={() => update({ page: String(page + 1) })}>Next →</button>
          </nav>
        )}
      </div>
    </main>
  );
}
