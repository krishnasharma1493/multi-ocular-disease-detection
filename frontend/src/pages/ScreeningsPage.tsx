import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useScreenings } from '../features/screenings/api';
import { parseUtc, type Screening, type ScreeningStatus } from '../lib/api/types';
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

  const isSearch = !!q.trim();
  const list = useScreenings({
    page: isSearch ? 1 : page,
    limit: isSearch ? 100 : LIMIT,
    status: status || undefined,
  });

  const queryLower = q.trim().toLowerCase();
  const rawData = list.data;

  // Filter client-side when search query is present to allow searching by date or eye
  const allFiltered: Screening[] = (rawData?.data ?? []).filter((s) => {
    if (!queryLower) return true;
    const created = parseUtc(s.created_at);
    const dateStr = dayStamp(created).toLowerCase();
    const eyeStr = s.eye.toLowerCase();
    const eyeWordStr = eyeWord(s.eye).toLowerCase();
    const refStr = s.patient_ref.toLowerCase();
    return dateStr.includes(queryLower) || eyeStr.includes(queryLower) || eyeWordStr.includes(queryLower) || refStr.includes(queryLower);
  });

  const total = isSearch ? allFiltered.length : (rawData?.pagination.total ?? 0);
  const lastPage = isSearch ? Math.max(1, Math.ceil(total / LIMIT)) : (rawData?.pagination.total_pages ?? 1);
  const displayedItems = isSearch ? allFiltered.slice((page - 1) * LIMIT, page * LIMIT) : (rawData?.data ?? []);
  const from = total ? (page - 1) * LIMIT + 1 : 0;
  const to = Math.min(total, page * LIMIT);
  const filtered = !!q || !!status;

  useEffect(() => { document.title = 'All results · RetinaScreen'; }, [rawData]);

  if (list.error && !rawData) return <QueryError error={list.error} path="/screenings" onRetry={() => list.refetch()} />;

  return (
    <main id="main">
      <div className="page-head">
        <div className="titles"><span className="eyebrow">YOUR SCREENING HISTORY</span><h1 ref={h} tabIndex={-1}>All results</h1></div>
        <Link viewTransition className="btn-primary" style={{ height: 52, width: 240 }} to="/screenings/new"><span>+ New screening</span><span className="glyph" aria-hidden="true">→</span></Link>
      </div>
      <div className="list-wrap">
        <div className="filters" role="search">
          <div className="field search">
            <label htmlFor="q" className="label">SEARCH BY DATE OR EYE</label>
            <input id="q" className="line-input mono" type="search" value={text} placeholder="e.g. left, right, or date" maxLength={40} onChange={(e) => setText(e.target.value)} />
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
          {list.isFetching && !rawData ? 'LOADING' : total ? `SHOWING ${from}–${to} OF ${total}` : ''}
          {list.error && rawData ? ' · ▲ REFRESH FAILED' : ''}
        </div>

        {!rawData ? (
          <div className="rows" aria-busy="true">{Array.from({ length: 5 }, (_, i) => <div key={i} className="row skeleton" />)}</div>
        ) : displayedItems.length === 0 ? (
          <div className="empty-list">
            <span className="w2 serif">{filtered || page > 1 ? 'No screenings match these filters' : 'No screenings yet'}</span>
            {filtered || page > 1
              ? <button type="button" className="btn" onClick={() => { setText(''); setParams({}); }}>Clear filters</button>
              : <Link viewTransition className="btn" to="/screenings/new">New screening</Link>}
          </div>
        ) : (
          <table className="table">
            <caption className="sr-only">Screenings, newest first</caption>
            <thead><tr><th scope="col"><span className="sr-only">Readout</span></th><th scope="col">Screening</th><th scope="col">Eye</th><th scope="col">Status</th><th scope="col">Result</th><th scope="col">Created</th></tr></thead>
            <tbody>
              {displayedItems.map((s) => {
                const m = summarize(s);
                const g = STATUS_LABEL[m.status];
                const created = parseUtc(s.created_at);
                return (
                  <tr key={s.id}>
                    <td className="thumb" aria-hidden="true">{m.status === 'pending' ? <Lens size={48} state="empty" /> : <Lens size={48} values={m.vals} thresholds={m.ths} eye={eyeCode(s.eye) ?? 'R'} />}</td>
                    <td><Link viewTransition className="row-link mono" to={`/screenings/${s.id}`}>Screening #{s.id}</Link></td>
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

        {rawData && lastPage > 1 && (
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
