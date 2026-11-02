import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useBlocker, useNavigate } from 'react-router-dom';
import { useCreateScreening, useScreeningStats, useUploadImage } from '../features/screenings/api';
import { apiError, apiErrorMessage, isOffline } from '../lib/api/types';
import { env } from '../lib/env';
import { fileSize, hhmm } from '../lib/format';
import { Lens } from '../components/Lens';
import { useFocusHeading } from '../components/States';

const schema = z.object({
  patient_ref: z.string().trim().min(1, 'Enter the patient ref from the camp register').max(40, 'At most 40 characters'),
  eye: z.enum(['left', 'right'], { message: 'Choose one eye' }),
  notes: z.string().max(2000, 'At most 2000 characters'),
});
type Form = z.infer<typeof schema>;
type CaptureError = { code: string; head: string; body: string; data: string; blocking: boolean; rejected?: boolean };

const MAX_BYTES = env.VITE_MAX_UPLOAD_MB * 1024 * 1024;
const PASTE_KEYS = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘V' : 'Ctrl+V';

/** Clipboard images arrive as "image.png" (or unnamed); give them a readable, unique name. */
function namedPaste(blob: Blob, name?: string): File {
  const ext = blob.type === 'image/jpeg' ? 'jpg' : (blob.type.split('/')[1] || 'png');
  const generic = !name || /^image\.(png|jpe?g)$/i.test(name);
  const stamp = new Date().toTimeString().slice(0, 8).replace(/:/g, '');
  return new File([blob], generic ? `pasted-${stamp}.${ext}` : name!, { type: blob.type });
}

export function CapturePage() {
  const navigate = useNavigate();
  const stats = useScreeningStats();
  const create = useCreateScreening();
  const upload = useUploadImage();
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [err, setErr] = useState<CaptureError | null>(null);
  const [progress, setProgress] = useState<{ loaded: number; total: number; t0: number } | null>(null);
  const [capTime, setCapTime] = useState<Date | null>(null);
  const [over, setOver] = useState(false);
  const [createdId, setCreatedId] = useState<number | null>(null); // reused on retry: never a duplicate screening
  const doneRef = useRef(false); // set synchronously before the app's own navigation to the scan
  const [small, setSmall] = useState(() => window.innerWidth < 760);
  const [pasteMsg, setPasteMsg] = useState<string | null>(null);
  const placeRef = useRef<(f: File | undefined) => void>(() => undefined);
  const fileIn = useRef<HTMLInputElement>(null);
  const camIn = useRef<HTMLInputElement>(null);
  const h = useFocusHeading<HTMLHeadingElement>();
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { patient_ref: '', notes: '' }, mode: 'onChange' });
  const { errors, isDirty } = form.formState;
  const eye = form.watch('eye');
  const refValue = form.watch('patient_ref');
  const busy = !!progress || create.isPending;

  useEffect(() => { document.title = 'New screening · RetinaScreen'; }, []);
  useEffect(() => {
    const on = () => setSmall(window.innerWidth < 760);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  // Unsaved work: confirm before leaving (in-app navigation and tab close)
  const dirty = isDirty || !!file;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => !doneRef.current && dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    if (window.confirm('Leave this screening? The photo and specimen tag will be lost.')) blocker.proceed();
    else blocker.reset();
  }, [blocker]);
  useEffect(() => {
    if (!dirty) return;
    const on = (e: BeforeUnloadEvent) => { if (!doneRef.current) e.preventDefault(); };
    window.addEventListener('beforeunload', on);
    return () => window.removeEventListener('beforeunload', on);
  }, [dirty]);

  function place(f: File | undefined) {
    if (!f || busy) return;
    setErr(null);
    setPasteMsg(null);
    const ext = (f.name.split('.').pop() || '').toUpperCase();
    const okType = ['image/jpeg', 'image/png'].includes(f.type) || (!f.type && ['JPG', 'JPEG', 'PNG'].includes(ext));
    if (!okType) {
      const kind = f.type === 'image/heic' || f.type === 'image/heif' ? 'HEIC' : ext || f.type || 'an unknown type';
      setFile(null); setUrl(null);
      setErr({ code: 'ERR · FILE TYPE', head: `This file is ${kind}, not JPG or PNG.`, body: 'Export the photo from the camera as JPG or PNG, then place it in the lens again.', data: `${f.name} · ${fileSize(f.size)}`, blocking: true });
      return;
    }
    if (f.size > MAX_BYTES) {
      setFile(null); setUrl(null);
      setErr({ code: 'ERR · FILE TOO LARGE', head: `This photo is ${fileSize(f.size)}. The limit is ${env.VITE_MAX_UPLOAD_MB} MB.`, body: 'Save it at a lower resolution on the camera, or use the compressed copy, then try again.', data: `${f.name} · ${fileSize(f.size)}`, blocking: true });
      return;
    }
    setFile(f);
    setUrl(URL.createObjectURL(f));
    setCapTime(new Date());
  }

  placeRef.current = place;
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); place(e.dataTransfer.files[0]); };

  // Paste anywhere on the page (⌘V / Ctrl+V). Text pastes into the form fields are left alone.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = [...(e.clipboardData?.items ?? [])].find((i) => i.kind === 'file');
      const blob = item?.getAsFile();
      if (!blob) return;
      e.preventDefault();
      placeRef.current(namedPaste(blob, blob.name));
    };
    document.addEventListener('paste', onPaste);
    return () => document.removeEventListener('paste', onPaste);
  }, []);

  // "Paste image" button: reads the clipboard directly (needs the browser's clipboard permission)
  const pasteFromClipboard = async () => {
    setPasteMsg(null);
    if (!navigator.clipboard?.read) { setPasteMsg(`This browser can't read the clipboard from a button. Press ${PASTE_KEYS} instead.`); return; }
    try {
      for (const item of await navigator.clipboard.read()) {
        const type = item.types.find((t) => t.startsWith('image/'));
        if (type) { place(namedPaste(await item.getType(type))); return; }
      }
      setPasteMsg('No image on the clipboard. Copy a fundus photo first, then paste.');
    } catch {
      setPasteMsg(`Clipboard access was blocked. Press ${PASTE_KEYS} to paste instead.`);
    }
  };
  // Labels open the native file picker without a scripted click; Enter/Space work like a button
  const labelKey = (e: KeyboardEvent<HTMLLabelElement>) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); (e.currentTarget.control as HTMLInputElement | null)?.click(); }
  };

  const onSubmit = form.handleSubmit(async (values) => {
    if (!file || busy) return;
    setErr(null);
    try {
      let id = createdId;
      if (id == null) {
        const s = await create.mutateAsync({ patient_ref: values.patient_ref.trim(), eye: values.eye, notes: values.notes.trim() || null });
        id = s.id;
        setCreatedId(id);
      }
      setProgress({ loaded: 0, total: file.size, t0: performance.now() });
      await upload.mutateAsync({ id, file, onProgress: (loaded, total) => setProgress((p) => (p ? { ...p, loaded, total } : p)) });
      doneRef.current = true;
      navigate(`/screenings/${id}/scan`, { state: { fromCapture: true } });
    } catch (e) {
      setProgress(null);
      if (isOffline(e)) {
        setErr({ code: 'ERR · NO RESPONSE', head: 'The analysis server did not answer.', body: 'Check that the RetinaScreen server is running, then press Analyze eye again. The photo stays in the lens.', data: "CAN'T REACH THE SERVER", blocking: false });
        return;
      }
      const ae = apiError(e);
      if (ae?.code === 'VALIDATION_ERROR' && ae.fields) {
        Object.entries(ae.fields).forEach(([k, msgs]) => {
          if (k === 'patient_ref' || k === 'eye' || k === 'notes') form.setError(k, { message: msgs[0] });
        });
        return;
      }
      const data = ae?.fields?.file?.[0] ?? `${file.name} · ${fileSize(file.size)}`;
      if (ae?.code === 'IMAGE_QUALITY') {
        setErr({ code: 'ERR · IMAGE QUALITY', head: 'Too blurred to screen, or not a fundus photo.', body: 'Refocus on the optic disc and retake. Check the lens cap and that the camera is in fundus mode.', data, blocking: true, rejected: true });
      } else if (ae?.code === 'UNSUPPORTED_MEDIA_TYPE') {
        setErr({ code: 'ERR · FILE TYPE', head: `${ae.message}.`, body: 'Export the photo from the camera as JPG or PNG, then place it in the lens again.', data, blocking: true, rejected: true });
      } else if (ae?.code === 'PAYLOAD_TOO_LARGE') {
        setErr({ code: 'ERR · FILE TOO LARGE', head: `${ae.message}.`, body: 'Save it at a lower resolution on the camera, or use the compressed copy, then try again.', data, blocking: true, rejected: true });
      } else {
        setErr({ code: 'ERR · REQUEST FAILED', head: apiErrorMessage(e), body: 'Try again. If it keeps failing, restart the RetinaScreen server.', data, blocking: false });
      }
    }
  });

  const specimen = String((stats.data?.total ?? 0) + (createdId ? 0 : 1)).padStart(2, '0');
  const rejected = !!err?.rejected;
  const need: string[] = [];
  if (!file || rejected) need.push('A PHOTO');
  if (!refValue?.trim() || errors.patient_ref) need.push('A PATIENT REF');
  if (!eye) need.push('AN EYE');
  const canGo = !busy && need.length === 0 && !(err?.blocking);
  const hint = busy ? 'AVAILABLE WHEN THE UPLOAD COMPLETES'
    : rejected || err?.blocking ? 'FIX THE PHOTO TO CONTINUE'
    : need.length ? 'NEEDS ' + (need.length > 2 ? `${need.slice(0, -1).join(', ')} AND ${need[need.length - 1]}` : need.join(' AND '))
    : 'READY · SCREENS FOUR DISEASES';
  const lensSize = small ? 300 : 560;
  const pctDone = progress ? Math.min(1, progress.loaded / Math.max(progress.total, 1)) : 0;
  const pick = (
    <div className="file-btns">
      <label htmlFor="photo-file" className={`btn${busy ? ' is-disabled' : ''}`} role="button" tabIndex={busy ? -1 : 0} aria-disabled={busy} onKeyDown={labelKey}>{file ? 'Replace photo' : 'Browse files'}</label>
      <button type="button" className="btn" onClick={pasteFromClipboard} disabled={busy}>Paste image</button>
      {small && <label htmlFor="photo-camera" className={`btn${busy ? ' is-disabled' : ''}`} role="button" tabIndex={busy ? -1 : 0} aria-disabled={busy} onKeyDown={labelKey}>Take photo</label>}
    </div>
  );
  const pasteNote = <span className="paste-note" aria-live="polite">{pasteMsg ?? `or drag it onto the lens, or paste with ${PASTE_KEYS}`}</span>;

  let under;
  if (!file) {
    under = <div className="drop-text"><span className="big">Place fundus photo here</span><span className="small">(JPG / PNG, max {env.VITE_MAX_UPLOAD_MB} MB)</span><div style={{ marginTop: 8 }}>{pick}</div>{pasteNote}</div>;
  } else if (progress) {
    const secs = (performance.now() - progress.t0) / 1000;
    const rate = progress.loaded / Math.max(secs, 0.05);
    const left = Math.max(0, Math.ceil((progress.total - progress.loaded) / Math.max(rate, 1)));
    under = (
      <div className="drop-file">
        <span className="f">{file.name} · {fileSize(file.size)}</span>
        <span className="s">{pctDone >= 1 ? 'UPLOADED · CHECKING PHOTO' : `${(progress.loaded / 1048576).toFixed(1)} OF ${fileSize(progress.total)} · ABOUT ${left} S LEFT`}</span>
      </div>
    );
  } else if (rejected) {
    under = <div className="drop-file"><span className="f">{file.name} · {fileSize(file.size)}</span><span className="s" style={{ color: 'var(--vermilion-deep)', fontWeight: 600 }}>▲ REJECTED · RETAKE OR REPLACE</span>{pick}{pasteNote}</div>;
  } else {
    under = <div className="drop-file"><span className="f">{file.name} · {fileSize(file.size)}</span><span className="s">PHOTO PLACED</span>{pick}{pasteNote}</div>;
  }

  return (
    <main id="main">
      <div className="capture-head">
        <div className="titles"><span className="eyebrow">NEW SCREENING · SPECIMEN {specimen}</span><h1 ref={h} tabIndex={-1}>New screening</h1></div>
        <span className="eyebrow">ONE PHOTO · ONE EYE · FOUR DISEASES</span>
      </div>
      <div className="capture-grid">
        <div className="drop" onDragEnter={(e) => { e.preventDefault(); setOver(true); }} onDragOver={(e) => e.preventDefault()} onDragLeave={() => setOver(false)} onDrop={onDrop}>
          <label htmlFor="photo-file" className={`drop-target${busy ? ' is-disabled' : ''}`} title={busy ? undefined : 'Choose a fundus photo'}>
          <Lens className={`drop-lens${over ? ' over' : ''}`} size={lensSize} state={progress ? 'uploading' : file && !rejected ? 'photo' : file ? 'photo' : 'empty'}
            photo={url} eye={eye === 'left' ? 'L' : 'R'} progress={pctDone}
            label={progress ? `Uploading ${Math.round(pctDone * 100)} percent` : file ? `Photo placed: ${file.name}` : 'Empty lens. Place a fundus photo here.'} />
          </label>
          <div aria-live="polite">{under}</div>
          <input ref={fileIn} id="photo-file" type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" className="sr-only" tabIndex={-1} disabled={busy}
            onChange={(e) => { place(e.target.files?.[0]); e.target.value = ''; }} />
          <input ref={camIn} id="photo-camera" type="file" accept="image/*" capture="environment" className="sr-only" tabIndex={-1} disabled={busy}
            onChange={(e) => { place(e.target.files?.[0]); e.target.value = ''; }} />
        </div>
        <div className="callout-col">
          {err ? (
            <div className="callout err" role="alert"><span className="code">{err.code}</span><span className="head">{err.head}</span><p>{err.body}</p><span className="data">{err.data}</span></div>
          ) : (!file || progress) ? (
            <div className="callout"><span className="label">NOTE</span><p>Keep the optic disc and macula both inside the frame. Dilate first if the pupil is under 4 mm.</p></div>
          ) : null}
        </div>
        <form className="form-col" onSubmit={onSubmit} noValidate>
          <div className="tag form-tag">
            <span className="punch" aria-hidden="true" />
            <div className="tag-head"><span>SPECIMEN TAG</span><span className="mute">No. {specimen}</span></div>
            <div className="field">
              <label htmlFor="ref">PATIENT REF</label>
              <input id="ref" className="ref-input" placeholder="P-____" autoComplete="off" autoCapitalize="characters" spellCheck={false} maxLength={40}
                aria-invalid={!!errors.patient_ref} aria-describedby="ref-hint" disabled={createdId != null}
                {...form.register('patient_ref', { setValueAs: (v: string) => v.toUpperCase() })} />
              <span className={`hint${errors.patient_ref ? ' bad' : ''}`} id="ref-hint">{errors.patient_ref?.message ?? 'Format P-0000, from the camp register'}</span>
            </div>
            <fieldset className="field" disabled={createdId != null}>
              <legend>EYE SCREENED</legend>
              <div className="eyes" style={{ marginTop: 2 }}>
                <label className="eye-opt"><input type="radio" value="left" aria-label="Left eye (OS)" {...form.register('eye')} /><span aria-hidden="true">L</span></label>
                <span className="link-line" aria-hidden="true" />
                <label className="eye-opt"><input type="radio" value="right" aria-label="Right eye (OD)" {...form.register('eye')} /><span aria-hidden="true">R</span></label>
                <span className="eye-text">{eye === 'left' ? 'Left eye (OS)' : eye === 'right' ? 'Right eye (OD)' : 'Choose one eye'}</span>
              </div>
            </fieldset>
            <div className="field" style={{ gap: 6 }}>
              <label htmlFor="notes">NOTES</label>
              <textarea id="notes" className="notes" rows={3} maxLength={2000} disabled={createdId != null}
                placeholder="Optional. Symptoms, dilation, anything the reviewer should know." aria-describedby="notes-count" {...form.register('notes')} />
              <span id="notes-count" className="hint" style={{ textAlign: 'right' }}>{(form.watch('notes') ?? '').length} / 2000</span>
            </div>
            <div className="tag-foot"><span>CAPTURED {capTime ? hhmm(capTime) : '—'}</span><span>EFFICIENTNET-B0</span></div>
          </div>
          <button type="submit" className="btn-primary" disabled={!canGo} aria-describedby="go-hint"><span>Analyze eye</span><span className="glyph" aria-hidden="true">→</span></button>
          <span className="btn-hint" id="go-hint">{hint}</span>
        </form>
      </div>
    </main>
  );
}
