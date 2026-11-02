// Shared colours, formatting and screening-result wording.
import { parseUtc, type Eye, type Finding, type Screening } from './api/types';

export const COLORS = {
  V: '#D9481C', VT: '#C23E14', G: '#3F6B4E', O: '#C08A2B', OT: '#8A6118',
  INK: '#1A1A17', MUTE: '#5E5A50', PAPER: '#F3EFE6', CARD: '#EAE4D7',
};

export const DISEASES = ['Myopia', 'Cataract', 'Glaucoma', 'Diabetic Retinopathy'];
const SHORT: Record<string, string> = { 'Diabetic Retinopathy': 'DR' };
/** A disease within this many points below its threshold is flagged for review. */
export const NEAR_NOTCH = 0.1;

export const TREATMENT: Record<string, string> = {
  Cataract: 'Cataract surgery',
  Myopia: 'Corrective lenses and ophthalmologist follow-up',
  Glaucoma: 'Eye drops, laser treatment, or surgery',
  'Diabetic Retinopathy': 'Blood sugar control, with laser treatment or eye injections if needed',
};

const ESC: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

export const reducedMotion = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];
const pad = (n: number) => String(n).padStart(2, '0');
export const hhmm = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const hhmmss = (d: Date) => `${hhmm(d)}:${pad(d.getSeconds())}`;
export const dayStamp = (d: Date) => `${pad(d.getDate())} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
export const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
export const fileSize = (bytes: number) => (bytes < 102400 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);
export const pct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;
export const num2 = (x: number | null | undefined) => (x == null ? '—' : x.toFixed(2));

export const eyeCode = (eye: Eye): 'L' | 'R' | null => (eye === 'left' ? 'L' : eye === 'right' ? 'R' : null);
export const eyeWord = (eye: Eye) => (eye === 'left' ? 'left' : eye === 'right' ? 'right' : 'unrecorded');
export const eyeLong = (eye: Eye) => (eye === 'left' ? 'Left (OS)' : eye === 'right' ? 'Right (OD)' : 'Not recorded');
/** "Diabetic Retinopathy" reads as "Diabetic retinopathy" in running text, as in the designs. */
export const sentence = (name: string) => name.split(' ').map((w, i) => (i ? w.toLowerCase() : w)).join(' ');

export type Status = 'possible' | 'review' | 'clear' | 'pending';

export type Summary = {
  rows: Finding[];
  vals: number[];
  ths: number[];
  positives: Finding[];
  primary: Finding | null;
  near: Finding | null;
  nearest: Finding | null;
  status: Status;
  verdict: string;
  sub: string;
  created: Date;
};

/** Order findings Myopia, Cataract, Glaucoma, Diabetic Retinopathy (the lens quadrants). */
export function orderedFindings(findings: Finding[]): Finding[] {
  return DISEASES.map((d) => findings.find((f) => f.disease === d)).filter((f): f is Finding => !!f);
}

/** The same findings for the readings list: highest probability first (ties keep the quadrant order). */
export function byProbability(findings: Finding[]): Finding[] {
  return orderedFindings(findings).sort((a, b) => b.probability - a.probability);
}

export function summarize(s: Screening): Summary {
  const created = parseUtc(s.created_at);
  const findings = s.result ? orderedFindings(s.result.findings) : [];
  if (!s.result || findings.length !== 4) {
    return { rows: [], vals: [0, 0, 0, 0], ths: [0.5, 0.5, 0.5, 0.5], positives: [], primary: null, near: null, nearest: null,
      status: 'pending', verdict: s.has_image ? 'Awaiting analysis' : 'No photo yet', sub: s.has_image ? 'NOT ANALYZED' : 'UPLOAD A FUNDUS PHOTO', created };
  }
  const rows = findings;
  const positives = rows.filter((r) => r.positive);
  const primary = positives.slice().sort((a, b) => b.probability - a.probability)[0] ?? null;
  const near = rows.filter((r) => !r.positive && r.probability >= r.threshold - NEAR_NOTCH)
    .sort((a, b) => (b.probability - b.threshold) - (a.probability - a.threshold))[0] ?? null;
  const nearest = rows.slice().sort((a, b) => (b.probability / b.threshold) - (a.probability / a.threshold))[0];
  const status: Status = positives.length ? 'possible' : near ? 'review' : 'clear';
  const tag = (r: Finding) => `${(SHORT[r.disease] ?? r.disease).toUpperCase()} ${pct(r.probability)} · THRESHOLD ${pct(r.threshold)}`;
  let verdict: string, sub: string;
  if (primary) {
    verdict = 'Possible: ' + positives.map((r) => sentence(r.disease)).join(', ');
    sub = tag(primary);
  } else if (near) {
    verdict = `${sentence(near.disease)} close to notch`;
    sub = tag(near);
  } else {
    verdict = 'Not detected';
    sub = nearest.probability >= nearest.threshold / 2 ? tag(nearest) : 'ALL FOUR BELOW NOTCH';
  }
  return { rows, vals: rows.map((r) => r.probability), ths: rows.map((r) => r.threshold), positives, primary, near, nearest, status, verdict, sub, created };
}

export const STATUS_LABEL: Record<Status, { word: string; head: string; cls: string; glyph: string; color: string }> = {
  possible: { word: '▲ POSSIBLE', head: '▲ POSSIBLE', cls: 'c-pos', glyph: '▲', color: COLORS.V },
  review: { word: '◐ REVIEW', head: '◐ PENDING REVIEW', cls: 'c-rev', glyph: '◐', color: COLORS.O },
  clear: { word: '○ CLEAR', head: '○ NOT DETECTED', cls: 'c-clr', glyph: '○', color: COLORS.G },
  pending: { word: '· NOT ANALYZED', head: '· AWAITING ANALYSIS', cls: 'mute', glyph: '·', color: COLORS.MUTE },
};
