// Shared helpers: escaping, colours, API access and screening-result wording.

export const COLORS = {
  V: '#D9481C', VT: '#C23E14', G: '#3F6B4E', O: '#C08A2B', OT: '#8A6118',
  INK: '#1A1A17', MUTE: '#5E5A50', PAPER: '#F3EFE6', CARD: '#EAE4D7',
};

export const DISEASES = ['Myopia', 'Cataract', 'Glaucoma', 'Diabetic Retinopathy'];
export const SHORT = { 'Diabetic Retinopathy': 'DR' };
// A disease within this many points below its threshold is flagged for review.
export const NEAR_NOTCH = 0.1;

export const TREATMENT = {
  Cataract: 'Cataract surgery',
  Myopia: 'Corrective lenses and ophthalmologist follow-up',
  Glaucoma: 'Eye drops, laser treatment, or surgery',
  'Diabetic Retinopathy': 'Blood sugar control, with laser treatment or eye injections if needed',
};

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

export const reducedMotion = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

export class OfflineError extends Error {}
export class ApiError extends Error {
  constructor(status, detail) { super(typeof detail === 'string' ? detail : 'Request failed'); this.status = status; this.detail = detail; }
}

export const net = { lastContact: null };

export async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch('/api' + path, { headers: { Accept: 'application/json', ...(opts.body ? { 'Content-Type': 'application/json' } : {}) }, ...opts });
  } catch (e) {
    throw new OfflineError(e.message);
  }
  net.lastContact = new Date();
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body.detail);
  return body;
}

// Upload with progress (fetch has no upload progress events).
export function uploadScreening(form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/screenings');
    xhr.responseType = 'json';
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded, e.total); };
    xhr.upload.onload = () => onProgress(1, 1, true);
    xhr.onload = () => {
      net.lastContact = new Date();
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
      else reject(new ApiError(xhr.status, xhr.response && xhr.response.detail));
    };
    xhr.onerror = () => reject(new OfflineError('network'));
    xhr.send(form);
  });
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const pad = (n) => String(n).padStart(2, '0');
export const parseTime = (iso) => new Date(iso);
export const hhmm = (d) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const hhmmss = (d) => `${hhmm(d)}:${pad(d.getSeconds())}`;
export const dayStamp = (d) => `${pad(d.getDate())} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
export const mb = (bytes) => (bytes < 102400 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);
export const pct = (x, digits = 1) => `${(x * 100).toFixed(digits)}%`;
export const pct0 = (x) => `${Math.round(x * 100)}%`;
export const eyeWord = (eye) => (eye === 'L' ? 'left' : 'right');
export const eyeLong = (eye) => (eye === 'L' ? 'Left (OS)' : 'Right (OD)');
export const lower = (name) => name.charAt(0) + name.slice(1).toLowerCase();
// "Diabetic Retinopathy" reads as "Diabetic retinopathy" in running text, as in the designs.
export const sentence = (name) => name.split(' ').map((w, i) => (i ? w.toLowerCase() : w)).join(' ');

export function eyeDots(eye, dot = 11) {
  const d = (on) => `<span class="eye-dot" style="width:${dot}px;height:${dot}px;background:${on ? COLORS.INK : 'transparent'}"></span>`;
  return `<span class="eye-dots" aria-label="${eyeWord(eye)} eye">L${d(eye === 'L')}${d(eye === 'R')}R</span>`;
}

// Summarise one screening record for the ledger, the flow and the detail screen.
export function summarize(rec) {
  const rows = DISEASES.map((name) => rec.results.find((r) => r.disease === name) || { disease: name, probability: 0, threshold: 1, positive: false });
  const vals = rows.map((r) => r.probability), ths = rows.map((r) => r.threshold);
  const positives = rows.filter((r) => r.positive);
  const primary = positives.slice().sort((a, b) => b.probability - a.probability)[0] || null;
  const near = rows.filter((r) => !r.positive && r.probability >= r.threshold - NEAR_NOTCH)
    .sort((a, b) => (b.probability - b.threshold) - (a.probability - a.threshold))[0] || null;
  const nearest = rows.slice().sort((a, b) => (b.probability / b.threshold) - (a.probability / a.threshold))[0];
  const status = positives.length ? 'possible' : near ? 'review' : 'clear';
  const tag = (r, sep = ' · NOTCH ') => `${(SHORT[r.disease] || r.disease).toUpperCase()} ${pct(r.probability)}${sep}${pct0(r.threshold)}`;
  let verdict, sub;
  if (status === 'possible') {
    verdict = 'Possible: ' + positives.map((r) => sentence(r.disease)).join(', ');
    sub = tag(primary);
  } else if (status === 'review') {
    verdict = `${sentence(near.disease)} close to notch`;
    sub = tag(near);
  } else {
    verdict = 'Not detected';
    sub = nearest.probability >= nearest.threshold / 2 ? tag(nearest) : 'ALL FOUR BELOW NOTCH';
  }
  return { rows, vals, ths, positives, primary, near, nearest, status, verdict, sub, created: parseTime(rec.created) };
}
