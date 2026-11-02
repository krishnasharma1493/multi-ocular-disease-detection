// New screening: drop a fundus photo in the lens, fill the specimen tag, upload.
import { api, uploadScreening, OfflineError, ApiError, net, esc, mb, hhmm, hhmmss } from './util.js';
import { lensSVG } from './lens.js';
import { setTitle } from './app.js';

const MAX_BYTES = 10 * 1024 * 1024;
const REF_RE = /^P-\d{4}$/;

export async function renderCapture(view, { model }) {
  const today = await api('/screenings');
  const specimen = String(today.screenings.length + 1).padStart(2, '0');
  setTitle('New screening');
  const st = { file: null, url: null, err: null, rejected: false, up: null, capTime: null, busy: false };
  const small = () => window.innerWidth < 760;

  view.innerHTML = `<main id="main">
    <div class="capture-head">
      <div class="titles" style="display:flex;flex-direction:column;gap:12px"><span class="eyebrow">NEW SCREENING · SPECIMEN ${specimen} OF TODAY</span><h1>New screening</h1></div>
      <span class="eyebrow" style="letter-spacing:0.14em">ONE PHOTO · ONE EYE · FOUR DISEASES</span>
    </div>
    <div class="capture-grid">
      <div class="drop" id="drop">
        <div class="drop-lens" id="lens" role="img"></div>
        <div id="under" aria-live="polite"></div>
        <input type="file" id="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" class="sr-only" tabindex="-1">
        <input type="file" id="camera" accept="image/*" capture="environment" class="sr-only" tabindex="-1">
      </div>
      <div class="callout-col" id="callout"></div>
      <form class="form-col" id="form" novalidate>
        <div class="tag form-tag">
          <span class="punch" aria-hidden="true"></span>
          <div class="tag-head"><span>SPECIMEN TAG</span><span class="mute">No. ${specimen}</span></div>
          <div class="field"><label for="ref">PATIENT REF</label>
            <input id="ref" class="ref-input" name="ref" placeholder="P-____" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="6" aria-describedby="ref-hint" required>
            <span class="hint" id="ref-hint">Format P-0000, from the camp register</span></div>
          <fieldset class="field"><legend>EYE SCREENED</legend>
            <div class="eyes" style="margin-top:2px">
              <label class="eye-opt"><input type="radio" name="eye" value="L" aria-label="Left eye (OS)"><span aria-hidden="true">L</span></label>
              <span class="link-line" aria-hidden="true"></span>
              <label class="eye-opt"><input type="radio" name="eye" value="R" aria-label="Right eye (OD)"><span aria-hidden="true">R</span></label>
              <span class="eye-text" id="eye-text">Choose one eye</span>
            </div></fieldset>
          <div class="field" style="gap:6px"><label for="notes">NOTES</label>
            <textarea id="notes" class="notes" name="notes" rows="3" maxlength="2000" placeholder="Optional. Symptoms, dilation, anything the reviewer should know."></textarea></div>
          <div class="tag-foot"><span id="cap-time">CAPTURED —</span><span>${esc(model.model_name.replace('_', '-').toUpperCase())}</span></div>
        </div>
        <button type="submit" class="btn-primary" id="go" disabled aria-describedby="go-hint"><span>Analyze eye</span><span class="glyph" aria-hidden="true">→</span></button>
        <span class="btn-hint" id="go-hint"></span>
      </form>
    </div></main>`;

  const $ = (sel) => view.querySelector(sel);
  const lens = $('#lens'), under = $('#under'), callout = $('#callout'), form = $('#form');
  const refIn = $('#ref'), notesIn = $('#notes'), go = $('#go'), hint = $('#go-hint');
  const fileIn = $('#file'), camIn = $('#camera'), drop = $('#drop');

  const eye = () => (form.querySelector('input[name="eye"]:checked') || {}).value || null;

  function paint() {
    const size = small() ? 300 : 560;
    const lensState = st.up ? 'uploading' : st.file ? 'photo' : 'empty';
    lens.innerHTML = lensSVG({ size, state: lensState, photo: st.url, eye: eye() || 'R', progress: st.up ? st.up.loaded / st.up.total : 0 });
    lens.setAttribute('aria-label', st.up ? `Uploading ${Math.round(st.up.loaded / st.up.total * 100)} percent` : st.file ? `Photo placed: ${st.file.name}` : 'Empty lens. Place a fundus photo here.');
    const pick = `<div class="file-btns"><button type="button" class="btn" data-pick="file">${st.file ? 'Replace photo' : 'Browse files'}</button>${small() ? '<button type="button" class="btn" data-pick="camera">Take photo</button>' : ''}</div>`;
    if (!st.file) {
      under.innerHTML = `<div class="drop-text"><span class="big">Place fundus photo here</span><span class="small">(JPG / PNG, max 10 MB)</span><div style="margin-top:8px">${pick}</div></div>`;
    } else if (st.up) {
      const { loaded, total, t0, done } = st.up;
      const secs = (performance.now() - t0) / 1000, rate = loaded / Math.max(secs, 0.05);
      const left = Math.max(0, Math.ceil((total - loaded) / Math.max(rate, 1)));
      under.innerHTML = `<div class="drop-file"><span class="f">${esc(st.file.name)} · ${mb(st.file.size)}</span><span class="s">${done ? 'UPLOADED · SCREENING ON THE SERVER' : `${(loaded / 1048576).toFixed(1)} OF ${mb(total)} · ABOUT ${left} S LEFT`}</span></div>`;
    } else if (st.rejected) {
      under.innerHTML = `<div class="drop-file"><span class="f">${esc(st.file.name)} · ${mb(st.file.size)}</span><span class="s" style="color:var(--vermilion-deep);font-weight:600">▲ REJECTED · RETAKE OR REPLACE</span>${pick}</div>`;
    } else {
      under.innerHTML = `<div class="drop-file"><span class="f">${esc(st.file.name)} · ${mb(st.file.size)}</span><span class="s">PHOTO PLACED</span>${pick}</div>`;
    }
    if (st.err) {
      callout.innerHTML = `<div class="callout err" role="alert"><span class="code">${esc(st.err.code)}</span><span class="head">${esc(st.err.head)}</span><p>${esc(st.err.body)}</p><span class="data">${esc(st.err.data)}</span></div>`;
    } else if (!st.file || st.up) {
      callout.innerHTML = `<div class="callout"><span class="label">NOTE</span><p>Keep the optic disc and macula both inside the frame. Dilate first if the pupil is under 4 mm.</p></div>`;
    } else callout.innerHTML = '';
    paintButton();
  }

  function paintButton() {
    const refOk = REF_RE.test(refIn.value.trim().toUpperCase());
    const need = [];
    if (!st.file || st.rejected) need.push('A PHOTO');
    if (!refOk) need.push('A PATIENT REF');
    if (!eye()) need.push('AN EYE');
    go.disabled = !!st.up || need.length > 0 || (st.err && st.err.blocking);
    hint.textContent = st.up ? 'AVAILABLE WHEN THE UPLOAD COMPLETES'
      : st.rejected || (st.err && st.err.blocking) ? 'FIX THE PHOTO TO CONTINUE'
      : need.length ? 'NEEDS ' + need.join(need.length > 2 ? ', ' : ' AND ').replace(/, (?=[^,]*$)/, ' AND ') : 'READY · SCREENS FOUR DISEASES';
    const e = eye();
    $('#eye-text').textContent = e === 'L' ? 'Left eye (OS)' : e === 'R' ? 'Right eye (OD)' : 'Choose one eye';
    $('#cap-time').textContent = 'CAPTURED ' + (st.capTime ? hhmm(st.capTime) : '—');
  }

  function place(file) {
    if (!file || st.up) return;
    if (st.url) URL.revokeObjectURL(st.url);
    st.url = null; st.file = null; st.rejected = false; st.err = null;
    const ext = (file.name.split('.').pop() || '').toUpperCase();
    const okType = ['image/jpeg', 'image/png'].includes(file.type) || (!file.type && ['JPG', 'JPEG', 'PNG'].includes(ext));
    if (!okType) {
      const kind = file.type === 'image/heic' || file.type === 'image/heif' ? 'HEIC' : ext || file.type || 'an unknown type';
      st.err = { code: 'ERR · FILE TYPE', head: `This file is ${kind}, not JPG or PNG.`, body: 'Export the photo from the camera as JPG or PNG, then place it in the lens again.', data: `${file.name} · ${mb(file.size)}`, blocking: true };
    } else if (file.size > MAX_BYTES) {
      st.err = { code: 'ERR · FILE TOO LARGE', head: `This photo is ${mb(file.size)}. The limit is 10 MB.`, body: 'Save it at a lower resolution on the camera, or use the compressed copy, then try again.', data: `${file.name} · ${mb(file.size)}`, blocking: true };
    } else {
      st.file = file; st.url = URL.createObjectURL(file); st.capTime = new Date();
    }
    paint();
  }

  async function submit(e) {
    e.preventDefault();
    paintButton();
    if (go.disabled) return;
    const fd = new FormData();
    fd.append('image', st.file, st.file.name);
    fd.append('ref', refIn.value.trim().toUpperCase());
    fd.append('eye', eye());
    fd.append('notes', notesIn.value);
    st.err = null;
    st.up = { loaded: 0, total: st.file.size, t0: performance.now(), done: false };
    paint();
    let last = 0;
    try {
      const rec = await uploadScreening(fd, (loaded, total, done) => {
        st.up = { ...st.up, loaded: done ? st.up.total : loaded, total: done ? st.up.total : total, done: !!done };
        const now = performance.now();
        if (done || now - last > 80) { last = now; paint(); }
      });
      st.up = null;
      location.hash = `#/scan/${rec.id}`;
    } catch (err) {
      st.up = null;
      if (err instanceof OfflineError) {
        st.err = { code: 'ERR · NO RESPONSE', head: 'The analysis server did not answer.', body: 'Check that the RetinaScreen server is running, then press Analyze eye again. The photo stays in the lens.', data: net.lastContact ? `LAST CONTACT ${hhmmss(net.lastContact)}` : 'NO CONTACT YET' };
      } else if (err instanceof ApiError && err.detail && typeof err.detail === 'object') {
        st.err = { ...err.detail, blocking: err.status !== 422 || err.detail.code === 'ERR · IMAGE QUALITY' };
        st.rejected = err.detail.code === 'ERR · IMAGE QUALITY';
        if (['ref', 'eye'].includes(err.detail.code)) st.err = { code: 'ERR · SPECIMEN TAG', head: err.detail.head, body: err.detail.body, data: err.detail.data };
      } else {
        st.err = { code: `ERR · ${err.status || 'UNKNOWN'}`, head: 'The screening could not be completed.', body: 'Try again. If it keeps failing, restart the RetinaScreen server.', data: String(err.message || '') };
      }
      paint();
      callout.querySelector('[role="alert"]')?.scrollIntoView({ block: 'nearest' });
    }
  }

  view.addEventListener('click', (e) => {
    const b = e.target.closest('[data-pick]');
    if (b) (b.dataset.pick === 'camera' ? camIn : fileIn).click();
  });
  fileIn.addEventListener('change', () => { place(fileIn.files[0]); fileIn.value = ''; });
  camIn.addEventListener('change', () => { place(camIn.files[0]); camIn.value = ''; });
  refIn.addEventListener('input', () => {
    const v = refIn.value.toUpperCase().replace(/[^A-Z0-9-]/g, '');
    if (v !== refIn.value) refIn.value = v;
    const bad = v.length >= 6 && !REF_RE.test(v);
    refIn.setAttribute('aria-invalid', String(bad));
    $('#ref-hint').classList.toggle('bad', bad);
    paintButton();
  });
  form.addEventListener('change', (e) => { if (e.target.name === 'eye') paint(); });
  form.addEventListener('submit', submit);
  ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); lens.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); lens.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => place(e.dataTransfer.files[0]));
  let wasSmall = small();
  const onResize = () => { if (small() !== wasSmall) { wasSmall = small(); paint(); } };
  window.addEventListener('resize', onResize);
  paint();

  return () => {
    window.removeEventListener('resize', onResize);
    if (st.url) URL.revokeObjectURL(st.url);
  };
}
