import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { photoVersion, useDeleteScreening, useScreening, useScreeningImage, useUpdateScreening, useUploadImage } from '../features/screenings/api';
import { useCreateReview, useReviews } from '../features/reviews/api';
import { apiError, apiErrorMessage, parseUtc, type Eye, type ReviewDecision, type Screening } from '../lib/api/types';
import { env } from '../lib/env';
import { COLORS, TREATMENT, dayStamp, eyeCode, eyeLong, eyeWord, fileSize, hhmm, pct, sentence, summarize, byProbability } from '../lib/format';
import { EyeDots, Lens } from '../components/Lens';
import { Loading, QueryError, useFocusHeading } from '../components/States';

const READS: [ReviewDecision, string, string][] = [['agree', '✓', 'Agree'], ['disagree', '✕', 'Disagree'], ['unsure', '?', 'Unsure']];
const BADGE = (
  <svg width="16" height="16" viewBox="0 0 28 28" aria-hidden="true">
    <circle cx="14" cy="14" r="12.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
    <circle cx="14" cy="14" r="7.5" fill="none" stroke="currentColor" strokeWidth="3" />
  </svg>
);

function useSize() {
  const get = () => (window.innerWidth < 760 ? Math.min(330, window.innerWidth - 40) : 600);
  const [size, setSize] = useState(get);
  useEffect(() => {
    const on = () => setSize(get());
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return size;
}

function EditDialog({ s, onClose }: { s: Screening; onClose: () => void }) {
  const update = useUpdateScreening();
  const ref = useRef<HTMLDialogElement>(null);
  const [patientRef, setPatientRef] = useState(s.patient_ref);
  const [eye, setEye] = useState<Eye>(s.eye);
  const [notes, setNotes] = useState(s.notes ?? '');
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!patientRef.trim()) { setError('Enter the patient ref'); return; }
    try {
      await update.mutateAsync({ id: s.id, patient_ref: patientRef.trim().toUpperCase(), eye, notes: notes.trim() || null });
      onClose();
    } catch (err) {
      const f = apiError(err)?.fields;
      setError(f ? Object.values(f).flat().join(' ') : apiErrorMessage(err));
    }
  };
  return (
    <dialog ref={ref} className="dialog" aria-labelledby="edit-h" onClose={onClose}>
      <form onSubmit={submit} className="tag form-tag" noValidate>
        <div className="tag-head"><span id="edit-h">EDIT SPECIMEN TAG</span><span className="mute">{s.patient_ref}</span></div>
        <div className="field"><label htmlFor="e-ref">PATIENT REF</label>
          <input id="e-ref" className="ref-input" value={patientRef} maxLength={40} onChange={(e) => setPatientRef(e.target.value.toUpperCase())} aria-invalid={!patientRef.trim()} /></div>
        <fieldset className="field"><legend>EYE SCREENED</legend>
          <div className="eyes">
            {(['left', 'right'] as Eye[]).map((v) => (
              <label key={v} className="eye-opt"><input type="radio" name="e-eye" value={v} checked={eye === v} onChange={() => setEye(v)} aria-label={eyeLong(v)} /><span aria-hidden="true">{v === 'left' ? 'L' : 'R'}</span></label>
            ))}
            <span className="eye-text">{eyeLong(eye)}</span>
          </div></fieldset>
        <div className="field" style={{ gap: 6 }}><label htmlFor="e-notes">NOTES</label>
          <textarea id="e-notes" className="notes" rows={3} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} />
          <span className="hint" style={{ textAlign: 'right' }}>{notes.length} / 2000</span></div>
        {error && <span className="field-err" role="alert">▲ {error}</span>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-ink" disabled={update.isPending}>{update.isPending ? 'Saving…' : 'Save changes'}</button>
        </div>
      </form>
    </dialog>
  );
}

function ReviewSection({ s }: { s: Screening }) {
  const reviews = useReviews(s.id, !!s.result);
  const create = useCreateReview(s.id);
  const latest = reviews.data?.[0] ?? null;
  const [choice, setChoice] = useState<ReviewDecision | null>(null);
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const groupRef = useRef<HTMLDivElement>(null);
  const read = choice ?? latest?.decision ?? null;
  const treatments = s.result ? s.result.findings.filter((f) => f.positive) : [];

  const onKey = (e: KeyboardEvent) => {
    const keys: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (!(e.key in keys)) return;
    e.preventDefault();
    const i = Math.max(0, READS.findIndex(([k]) => k === read));
    const next = READS[(i + keys[e.key] + READS.length) % READS.length][0];
    setChoice(next);
    groupRef.current?.querySelector<HTMLButtonElement>(`[data-read="${next}"]`)?.focus();
  };
  const save = async () => {
    if (!choice) return;
    setMsg(null);
    try {
      await create.mutateAsync({ decision: choice, note: note.trim() || null });
      setChoice(null); setNote('');
    } catch (err) {
      setMsg(apiError(err)?.code === 'CONFLICT' ? 'Analyze the screening before reviewing it.' : `Not saved · ${apiErrorMessage(err)}`);
    }
  };

  return (
    <section className="notes-sec" aria-labelledby="notes-h">
      <div className="notes-row head"><div className="margin" aria-hidden="true" /><div className="body"><h2 id="notes-h">Reviewer’s notes</h2><span className="badge">{BADGE}Verified by RetinaScreen AI</span></div></div>
      <div className="notes-row"><div className="margin" aria-hidden="true">① READ</div><div className="body">
        {!s.result ? (
          <p className="mute" style={{ font: '500 13px/1.5 var(--sans)' }}>Analyze the screening before reviewing it.</p>
        ) : (
          <>
            <span id="read-q" style={{ font: '500 13px/1 var(--sans)', color: 'var(--graphite)' }}>Do you agree with the model’s verdict?</span>
            <div className="toggles" role="radiogroup" aria-labelledby="read-q" ref={groupRef} onKeyDown={onKey}>
              {READS.map(([key, g, label], i) => {
                const on = read === key;
                return (
                  <button key={key} type="button" role="radio" aria-checked={on} tabIndex={(read ? on : i === 0) ? 0 : -1} data-read={key} onClick={() => setChoice(key)}>
                    <span aria-hidden="true">{g}</span>{label}
                  </button>
                );
              })}
            </div>
            {choice && (
              <div className="review-form">
                <label htmlFor="r-note" className="label">NOTE (OPTIONAL)</label>
                <textarea id="r-note" className="notes" rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What you saw in the photo." />
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
                  <button type="button" className="btn btn-ink" onClick={save} disabled={create.isPending}>{create.isPending ? 'Saving…' : 'Save read'}</button>
                  <button type="button" className="btn" onClick={() => { setChoice(null); setNote(''); }}>Cancel</button>
                  <span className="hint">{note.length} / 1000</span>
                </div>
              </div>
            )}
            <span className="save-state" aria-live="polite">{msg ?? (latest ? `SAVED ${hhmm(parseUtc(latest.created_at))} · ${dayStamp(parseUtc(latest.created_at))}` : reviews.isPending ? 'LOADING' : 'NOT YET REVIEWED')}</span>
            {reviews.data && reviews.data.length > 0 && (
              <ol className="review-log" aria-label="Earlier reads, newest first">
                {reviews.data.map((r) => (
                  <li key={r.id}>
                    <span className="mono">{hhmm(parseUtc(r.created_at))}</span>
                    <b>{READS.find(([k]) => k === r.decision)?.[2]}</b>
                    <span>{r.note ?? '—'}</span>
                  </li>
                ))}
              </ol>
            )}
          </>
        )}
      </div></div>
      {treatments.length > 0 && (
        <div className="notes-row"><div className="margin" aria-hidden="true">② NOTE</div><div className="body" style={{ paddingBottom: 28, gap: 14 }}>
          {treatments.map((f) => (
            <div key={f.code} className="treat"><span className="k">USUAL TREATMENT · {f.disease.toUpperCase()}</span><span className="v">{TREATMENT[f.disease]}</span></div>
          ))}
        </div></div>
      )}
    </section>
  );
}

export function DetailPage() {
  const rawId = useParams().id;
  const id = Number(rawId);
  const navigate = useNavigate();
  const screening = useScreening(id);
  const s = screening.data;
  const image = useScreeningImage(id, photoVersion(s), !!s?.has_image);
  const del = useDeleteScreening();
  const upload = useUploadImage();
  const reviews = useReviews(id, !!s?.result);
  const [editing, setEditing] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const fileIn = useRef<HTMLInputElement>(null);
  const size = useSize();
  const h = useFocusHeading<HTMLHeadingElement>(!!s);
  useEffect(() => { if (s) document.title = `${s.patient_ref} ${eyeWord(s.eye)} eye · Detail · RetinaScreen`; }, [s]);

  if (!Number.isInteger(id) || id <= 0) return <QueryError error={{ response: { status: 404 } }} path={`/screenings/${rawId}`} onRetry={() => undefined} />;
  if (screening.isPending) return <Loading label="LOADING SCREENING" />;
  if (screening.error || !s) return <QueryError error={screening.error} path={`/screenings/${rawId}`} onRetry={() => screening.refetch()} />;

  const m = summarize(s);
  const pos = m.positives.length > 0;
  const created = parseUtc(s.created_at);
  const disagree = reviews.data?.[0]?.decision === 'disagree';
  const verdict = !s.result ? (s.has_image ? 'Awaiting analysis.' : 'No photo yet.') : pos ? `Possible: ${m.positives.map((r) => sentence(r.disease)).join(', ')}.` : 'Not detected.';
  const verdictSub = !s.result ? (s.has_image ? 'RUN THE ANALYSIS TO SCREEN FOUR DISEASES' : 'UPLOAD A FUNDUS PHOTO FIRST')
    : pos ? `${m.positives.length} OF 4 PAST THRESHOLD · ${m.primary!.disease.toUpperCase()} ${pct(m.primary!.probability)} vs ${pct(m.primary!.threshold)}`
    : `0 OF 4 PAST THRESHOLD · NEAREST: ${m.nearest!.disease.toUpperCase()} ${pct(m.nearest!.probability)} vs ${pct(m.nearest!.threshold)}`;
  const statusText = !s.result ? '· NOT ANALYZED' : (pos ? '▲ POSSIBLE' : '○ NOT DETECTED') + (disagree ? ' · ✕ REVIEWER: DISAGREE' : '') + (s.status === 'reviewed' && !disagree ? ' · ✓ REVIEWED' : '');
  const statusColor = !s.result ? COLORS.MUTE : pos ? COLORS.VT : disagree ? COLORS.INK : COLORS.G;
  const img = s.image;
  const facts: [string, string][] = [
    ['PATIENT REF', s.patient_ref],
    ['EYE', eyeLong(s.eye)],
    ['IMAGE', img ? `${img.width} × ${img.height} · ${img.type} · ${fileSize(img.bytes)}` : 'No photo uploaded'],
    ...(img?.sharpness != null ? [['QUALITY', `Sharpness ${img.sharpness.toFixed(2)} · pass`] as [string, string]] : []),
    ['STATUS', s.status === 'pending' ? 'Pending analysis' : s.status === 'analyzed' ? 'Analyzed' : 'Reviewed'],
    ...(s.notes ? [['NOTES', s.notes] as [string, string]] : []),
  ];
  const lensLabel = s.result
    ? 'Lens readout. ' + m.rows.map((r) => `${r.disease} ${pct(r.probability)}, threshold ${pct(r.threshold)}, ${r.positive ? 'positive' : 'not detected'}`).join('; ')
    : s.has_image ? `Fundus photo, ${eyeWord(s.eye)} eye, ${s.patient_ref}` : 'Empty lens: no photo uploaded';

  const replacePhoto = async (f: File | undefined) => {
    if (!f) return;
    setUploadErr(null);
    if (!['image/jpeg', 'image/png'].includes(f.type)) { setUploadErr('Only JPEG or PNG photos.'); return; }
    if (f.size > env.VITE_MAX_UPLOAD_MB * 1024 * 1024) { setUploadErr(`Photo is larger than ${env.VITE_MAX_UPLOAD_MB} MB.`); return; }
    if (s.result && !window.confirm('Replacing the photo clears the current result. Continue?')) return;
    try {
      await upload.mutateAsync({ id: s.id, file: f });
    } catch (err) {
      const ae = apiError(err);
      setUploadErr(`${apiErrorMessage(err)}${ae?.fields?.file ? ` · ${ae.fields.file[0]}` : ''}`);
    }
  };
  const remove = async () => {
    if (!window.confirm(`Delete screening ${s.patient_ref}? Its photo and reviews are deleted too.`)) return;
    try {
      await del.mutateAsync(s.id);
      navigate('/screenings', { replace: true });
    } catch (err) {
      setUploadErr(`Not deleted · ${apiErrorMessage(err)}`);
    }
  };

  return (
    <main id="main">
      <div className="crumb">
        <Link className="back" to="/">← LEDGER</Link><span className="sep" aria-hidden="true" />
        <h1 className="ref" ref={h} tabIndex={-1}>{s.patient_ref} <span className="sr-only">{eyeWord(s.eye)} eye</span></h1>
        <span aria-hidden="true"><EyeDots eye={eyeCode(s.eye)} /></span>
        <span className="status" style={{ color: statusColor }}>{statusText}</span>
        <span className="when">CAPTURED {hhmm(created)} · {dayStamp(created)}</span>
        <div className="crumb-actions">
          <button type="button" className="btn btn-sm" onClick={() => setEditing(true)}>Edit</button>
          <button type="button" className="btn btn-sm" onClick={() => fileIn.current?.click()} disabled={upload.isPending}>{upload.isPending ? 'Uploading…' : s.has_image ? 'Replace photo' : 'Upload photo'}</button>
          <button type="button" className="btn btn-sm btn-danger" onClick={remove} disabled={del.isPending}>Delete</button>
          <input ref={fileIn} type="file" accept="image/jpeg,image/png" className="sr-only" tabIndex={-1} aria-hidden="true" onChange={(e) => { replacePhoto(e.target.files?.[0]); e.target.value = ''; }} />
        </div>
      </div>
      {uploadErr && <div className="notice notice-red" role="alert" style={{ margin: '16px var(--margin) 0' }}><span className="label">▲ ERR</span><p>{uploadErr}</p></div>}
      <div className="detail-grid">
        <section className="facts" aria-labelledby="spec-h">
          <h2 id="spec-h" className="eyebrow" style={{ paddingBottom: 14 }}>SPECIMEN</h2>
          <dl style={{ margin: 0 }}>{facts.map(([k, v]) => <div key={k} className="fact"><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        </section>
        <div className="detail-center">
          <span className="eyebrow" style={{ textAlign: 'center' }}>LENS READOUT · FOUR QUADRANTS · CLOCKWISE FROM 0°</span>
          {s.has_image && image.isError && <span className="field-err" role="alert">▲ The photo could not be loaded.</span>}
          <Lens size={size} label={lensLabel} state={s.result ? 'readout' : s.has_image ? 'photo' : 'empty'} values={m.vals} thresholds={m.ths}
            eye={eyeCode(s.eye) ?? 'R'} photo={image.url} labelSize={size < 400 ? 13 : 10.5} />
          <div className="verdict" style={{ gap: 12, marginTop: 6 }}>
            <div className="verdict-line" style={{ gap: 14 }}>
              <span className="glyph" aria-hidden="true" style={{ color: !s.result ? COLORS.MUTE : pos ? COLORS.V : COLORS.G }}>{!s.result ? '·' : pos ? '▲' : '○'}</span>
              <span className="words">{verdict}</span>
            </div>
            <span className="sub">{verdictSub}</span>
            {disagree && <div className="override"><span>▲ HUMAN OVERRIDE</span><i aria-hidden="true" /><span>REVIEWER: DISAGREE</span></div>}
            {s.has_image && (
              <Link className="btn-primary analyze-btn" to={`/screenings/${s.id}/scan`}>
                <span>{s.result ? 'Re-run analysis' : 'Analyze eye'}</span><span className="glyph" aria-hidden="true">→</span>
              </Link>
            )}
          </div>
        </div>
        <section className="readings-col" aria-label="Readings">
          <div className="readings-head"><span>READINGS</span><span>PROB · THRESHOLD</span></div>
          {s.result ? byProbability(s.result.findings).map((r) => (
            <div key={r.code} className="reading" style={{ padding: '16px 0 18px' }}>
              <div className="reading-top"><span className="name">{sentence(r.disease)}</span><span className={`res ${r.positive ? 'c-pos' : 'c-clr'}`}>{r.positive ? '▲ POSITIVE' : '○ NOT DETECTED'}</span></div>
              <div className="reading-nums"><span className="prob">{pct(r.probability)}</span><span className="mute">threshold {pct(r.threshold)}</span></div>
              <meter className="sr-only" min={0} max={1} value={r.probability} aria-label={`${r.disease} probability ${pct(r.probability)}, threshold ${pct(r.threshold)}`} />
              <div className="bar" aria-hidden="true">
                <div className="scale" /><div className="base" />
                <div className="fill" style={{ width: `${(r.probability * 100).toFixed(2)}%`, background: r.positive ? COLORS.V : COLORS.INK }} />
                <div className="notch" style={{ left: `calc(${(r.threshold * 100).toFixed(2)}% - 1px)` }} />
              </div>
            </div>
          )) : <p className="mute" style={{ padding: '16px 0', font: '500 13.5px/1.5 var(--sans)' }}>No readings yet. {s.has_image ? 'Run the analysis to screen this photo.' : 'Upload a fundus photo, then analyze it.'}</p>}
          {s.result && (
            <div className="live"><i aria-hidden="true" />{s.result.demo
              ? 'DEMO RESULT · precomputed for this sample photo, not a live run'
              : `EfficientNet-B0 · live · ${s.result.latency_ms} ms`}
              {' · '}{s.result.model?.run_id ? `run ${s.result.model.run_id}` : 'run not recorded'}
              {s.result.model?.checkpoint_sha256 ? ` · checkpoint ${s.result.model.checkpoint_sha256.slice(0, 8)}` : ''}</div>
          )}
          <div className="scope">Screens these four diseases only; other eye conditions are not checked.</div>
        </section>
      </div>
      <ReviewSection s={s} />
      {editing && <EditDialog s={s} onClose={() => setEditing(false)} />}
    </main>
  );
}
