import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useBlocker, useNavigate } from 'react-router-dom';
import { useCreateScreening, useUploadImage } from '../features/screenings/api';
import { apiError, apiErrorMessage, isOffline } from '../lib/api/types';
import { env } from '../lib/env';
import { fileSize, hhmm } from '../lib/format';
import { Lens } from '../components/Lens';
import { useFocusHeading } from '../components/States';
import { reducedMotion } from '../lib/motion';

const schema = z.object({
  eye: z.enum(['left', 'right'], { message: 'Choose one eye' }),
  image_source: z.enum(['clinic_fundus', 'phone_20d'], { message: 'Choose where the photo is from' }),
  notes: z.string().max(2000, 'At most 2000 characters'),
});
type Form = z.infer<typeof schema>;
type CaptureError = { code: string; head: string; body: string; data: string; blocking: boolean; rejected?: boolean };
type Source = 'clinic_fundus' | 'phone_20d';
const PHONE_TIP = 'Fill the frame with the bright round view through the lens, and avoid glare.';

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
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { notes: '' }, mode: 'onChange' });
  const { errors, isDirty } = form.formState;
  const eye = form.watch('eye');
  const source = form.watch('image_source') as Source | undefined;
  const busy = !!progress || create.isPending;

  useEffect(() => { document.title = 'New screening · RetinaScreen'; }, []);
  useEffect(() => {
    const on = () => setSmall(window.innerWidth < 760);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  // A newly placed photo opens in the lens like an iris (the lens SVG is rebuilt on every render, so animate once here)
  useEffect(() => {
    if (!url || reducedMotion()) return;
    const img = document.querySelector<SVGImageElement>('.drop-lens image');
    img?.animate(
      [{ clipPath: 'circle(0% at 50% 50%)', filter: 'blur(8px)' }, { clipPath: 'circle(71% at 50% 50%)', filter: 'blur(0)' }],
      { duration: 760, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' },
    );
  }, [url]);

  // Unsaved work: confirm before leaving (in-app navigation and tab close)
  const dirty = isDirty || !!file;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => !doneRef.current && dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (blocker.state !== 'blocked') return;
    if (window.confirm('Leave this screening? The photo you chose will not be saved.')) blocker.proceed();
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
      setErr({ code: 'ERR · FILE TYPE', head: kind === 'HEIC' ? 'This photo is in HEIC format.' : `This file is ${kind}, not JPG or PNG.`, body: kind === 'HEIC' ? 'Choose a JPG or PNG photo, or set your iPhone camera to Most Compatible so photos save as JPG, then try again.' : 'Choose a JPG or PNG photo, then try again.', data: `${f.name} · ${fileSize(f.size)}`, blocking: true });
      return;
    }
    if (f.size > MAX_BYTES) {
      setFile(null); setUrl(null);
      setErr({ code: 'ERR · FILE TOO LARGE', head: `This photo is ${fileSize(f.size)}. The limit is ${env.VITE_MAX_UPLOAD_MB} MB.`, body: 'Choose a smaller copy of the photo, for example one saved at a lower quality, then try again.', data: `${f.name} · ${fileSize(f.size)}`, blocking: true });
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
      setPasteMsg('No image on the clipboard. Copy a photo first, then paste.');
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
        const s = await create.mutateAsync({ eye: values.eye, image_source: values.image_source, notes: values.notes.trim() || null });
        id = s.id;
        setCreatedId(id);
      }
      setProgress({ loaded: 0, total: file.size, t0: performance.now() });
      await upload.mutateAsync({ id, file, onProgress: (loaded, total) => setProgress((p) => (p ? { ...p, loaded, total } : p)) });
      doneRef.current = true;
      navigate(`/screenings/${id}/scan`, { state: { fromCapture: true }, viewTransition: true });
    } catch (e) {
      setProgress(null);
      if (isOffline(e)) {
        setErr({ code: 'ERR · NO RESPONSE', head: 'The analysis server did not answer.', body: 'Check your connection and that the RetinaScreen server is running, then press Check my eye again. Your photo stays in the lens.', data: "CAN'T REACH THE SERVER", blocking: false });
        return;
      }
      const ae = apiError(e);
      if (ae?.code === 'VALIDATION_ERROR' && ae.fields) {
        Object.entries(ae.fields).forEach(([k, msgs]) => {
          if (k === 'image_source' || k === 'eye' || k === 'notes') form.setError(k, { message: msgs[0] });
        });
        return;
      }
      const data = ae?.fields?.file?.[0] ?? `${file.name} · ${fileSize(file.size)}`;
      if (ae?.code === 'IMAGE_QUALITY') {
        setErr({ code: 'ERR · IMAGE QUALITY', head: ae.message.replace(/\.?$/, '.'), body: source === 'phone_20d' ? `Retake the photo. ${PHONE_TIP}` : 'Upload a sharper copy of the photo, or a different one from your eye clinic.', data, blocking: true, rejected: true });
      } else if (ae?.code === 'UNSUPPORTED_MEDIA_TYPE') {
        setErr({ code: 'ERR · FILE TYPE', head: ae.message.replace(/\.?$/, '.'), body: 'Choose a JPG or PNG photo, then try again.', data, blocking: true, rejected: true });
      } else if (ae?.code === 'PAYLOAD_TOO_LARGE') {
        setErr({ code: 'ERR · FILE TOO LARGE', head: ae.message.replace(/\.?$/, '.'), body: 'Choose a smaller copy of the photo, then try again.', data, blocking: true, rejected: true });
      } else {
        setErr({ code: 'ERR · REQUEST FAILED', head: apiErrorMessage(e), body: 'Please try again in a moment.', data, blocking: false });
      }
    }
  });

  const rejected = !!err?.rejected;
  const need: string[] = [];
  if (!file || rejected) need.push('A PHOTO');
  if (!source) need.push('WHERE THE PHOTO IS FROM');
  if (!eye) need.push('AN EYE');
  const canGo = !busy && need.length === 0 && !(err?.blocking);
  const hint = busy ? 'AVAILABLE WHEN THE UPLOAD COMPLETES'
    : rejected || err?.blocking ? 'FIX THE PHOTO TO CONTINUE'
    : need.length ? 'NEEDS ' + (need.length > 2 ? `${need.slice(0, -1).join(', ')} AND ${need[need.length - 1]}` : need.join(' AND '))
    : 'READY · CHECKS FOUR EYE DISEASES';
  const lensSize = small ? 300 : 560;
  const pctDone = progress ? Math.min(1, progress.loaded / Math.max(progress.total, 1)) : 0;
  const pick = (
    <div className="file-btns">
      <label htmlFor="photo-file" className={`btn${busy ? ' is-disabled' : ''}`} role="button" tabIndex={busy ? -1 : 0} aria-disabled={busy} onKeyDown={labelKey}>{file ? 'Replace photo' : 'Choose photo'}</label>
      <button type="button" className="btn" onClick={pasteFromClipboard} disabled={busy}>Paste image</button>
      {small && <label htmlFor="photo-camera" className={`btn${busy ? ' is-disabled' : ''}`} role="button" tabIndex={busy ? -1 : 0} aria-disabled={busy} onKeyDown={labelKey}>Take photo</label>}
    </div>
  );
  const pasteNote = <span className="paste-note" aria-live="polite">{pasteMsg ?? `or drag it onto the lens, or paste with ${PASTE_KEYS}`}</span>;

  let under;
  if (!file) {
    under = <div className="drop-text"><span className="big">Place your photo here</span><span className="small">JPG or PNG, up to {env.VITE_MAX_UPLOAD_MB} MB. Use the full-size photo, not a screenshot or thumbnail: small photos give less certain results. On an iPhone, set Camera to “Most Compatible” so photos save as JPG.</span><div style={{ marginTop: 8 }}>{pick}</div>{pasteNote}</div>;
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
    under = <div className="drop-file"><span className="f">{file.name} · {fileSize(file.size)}</span><span className="s" style={{ color: 'var(--vermilion-deep)', fontWeight: 600 }}>▲ PHOTO NOT ACCEPTED · RETAKE OR REPLACE</span>{pick}{pasteNote}</div>;
  } else {
    under = <div className="drop-file"><span className="f">{file.name} · {fileSize(file.size)}</span><span className="s">PHOTO PLACED</span>{pick}{pasteNote}</div>;
  }

  return (
    <main id="main">
      <div className="capture-head">
        <div className="titles"><span className="eyebrow">NEW SCREENING</span><h1 ref={h} tabIndex={-1}>New screening</h1></div>
        <span className="eyebrow">ONE PHOTO · ONE EYE · FOUR EYE DISEASES</span>
      </div>
      <div className="capture-grid">
        <div className="drop" onDragEnter={(e) => { e.preventDefault(); setOver(true); }} onDragOver={(e) => e.preventDefault()} onDragLeave={() => setOver(false)} onDrop={onDrop}>
          <label htmlFor="photo-file" className={`drop-target${busy ? ' is-disabled' : ''}`} title={busy ? undefined : 'Choose a photo'}>
          <Lens className={`drop-lens${over ? ' over' : ''}`} size={lensSize} state={progress ? 'uploading' : file && !rejected ? 'photo' : file ? 'photo' : 'empty'}
            photo={url} eye={eye === 'left' ? 'L' : 'R'} progress={pctDone}
            label={progress ? `Uploading ${Math.round(pctDone * 100)} percent` : file ? `Photo placed: ${file.name}` : 'Empty lens. Place your photo here.'} />
          </label>
          <div aria-live="polite">{under}</div>
          <input ref={fileIn} id="photo-file" type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" className="sr-only" tabIndex={-1} disabled={busy}
            onChange={(e) => { place(e.target.files?.[0]); e.target.value = ''; }} />
          <input ref={camIn} id="photo-camera" type="file" accept="image/*" capture="environment" className="sr-only" tabIndex={-1} disabled={busy} aria-label="Take a photo with the camera"
            onChange={(e) => { place(e.target.files?.[0]); e.target.value = ''; }} />
        </div>
        <div className="callout-col">
          {err ? (
            <div key={`${err.code}${err.head}`} className="callout err" role="alert"><span className="code">{err.code}</span><span className="head">{err.head}</span><p>{err.body}</p><span className="data">{err.data}</span></div>
          ) : (!file || progress) ? (
            <div className="callout"><span className="label">{source === 'phone_20d' ? 'TIP' : 'BEFORE YOU START'}</span><p>{source === 'phone_20d' ? PHONE_TIP : 'Use a photo of the back of your eye (a fundus photo) from an eye clinic. Both the optic disc and the macula should be in the frame.'}</p></div>
          ) : null}
        </div>
        <form className="form-col" onSubmit={onSubmit} noValidate>
          <div className="tag form-tag">
            <span className="punch" aria-hidden="true" />
            <div className="tag-head"><span>ABOUT THIS PHOTO</span></div>
            <fieldset className="field" disabled={createdId != null}>
              <legend>WHERE IS THIS PHOTO FROM?</legend>
              <label className="source-opt"><input type="radio" value="clinic_fundus" {...form.register('image_source')} /><span>A fundus photo from an eye clinic</span></label>
              <label className="source-opt"><input type="radio" value="phone_20d" {...form.register('image_source')} /><span>A photo I took with my phone and a 20D lens</span></label>
              {source === 'phone_20d' && <span className="hint">{PHONE_TIP} The model has not been tested on phone photos, so the result will be experimental.</span>}
              {errors.image_source && <span className="hint bad">{errors.image_source.message}</span>}
            </fieldset>
            <fieldset className="field" disabled={createdId != null}>
              <legend>WHICH EYE IS IT?</legend>
              <div className="eyes" style={{ marginTop: 2 }}>
                <label className="eye-opt"><input type="radio" value="left" aria-label="Left eye (OS)" {...form.register('eye')} /><span aria-hidden="true">L</span></label>
                <span className="link-line" aria-hidden="true" />
                <label className="eye-opt"><input type="radio" value="right" aria-label="Right eye (OD)" {...form.register('eye')} /><span aria-hidden="true">R</span></label>
                <span className="eye-text">{eye === 'left' ? 'Left eye (OS)' : eye === 'right' ? 'Right eye (OD)' : 'Choose one eye'}</span>
              </div>
            </fieldset>
            <div className="field" style={{ gap: 6 }}>
              <label htmlFor="notes">ANYTHING YOU WANT TO REMEMBER ABOUT THIS PHOTO (OPTIONAL)</label>
              <textarea id="notes" className="notes" rows={3} maxLength={2000} disabled={createdId != null}
                placeholder="For example: symptoms, or when the photo was taken." aria-describedby="notes-count" {...form.register('notes')} />
              <span id="notes-count" className="hint" style={{ textAlign: 'right' }}>{(form.watch('notes') ?? '').length} / 2000</span>
            </div>
            <div className="tag-foot"><span>CHOSEN {capTime ? hhmm(capTime) : '—'}</span><span>EFFICIENTNET-B0</span></div>
          </div>
          <button type="submit" className="btn-primary" disabled={!canGo} aria-describedby="go-hint"><span>Check my eye</span><span className="glyph" aria-hidden="true">→</span></button>
          <span className="btn-hint" id="go-hint">{hint}</span>
        </form>
      </div>
    </main>
  );
}
