// RetinaScreen client: hash router, top bezel and the shared system states.
import { api, OfflineError, ApiError, net, dayStamp, hhmmss, esc } from './util.js';
import { lensSVG } from './lens.js';
import { renderLedger } from './ledger.js';
import { renderCapture } from './capture.js';
import { renderFlow } from './flow.js';
import { renderDetail } from './detail.js';
import { renderModel } from './model.js';

const view = document.getElementById('view');
const bezel = document.getElementById('bezel');
const ctx = { model: null };
let cleanup = null;
let routeToken = 0;

const LOGO = (s = 28) => `<svg width="${s}" height="${s}" viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="12.5" fill="none" stroke="#1A1A17"/><circle cx="14" cy="14" r="7.5" fill="none" stroke="#1A1A17" stroke-width="3"/><circle cx="14" cy="14" r="1.8" fill="#1A1A17"/><line x1="14" y1="0" x2="14" y2="4" stroke="#1A1A17"/><line x1="14" y1="24" x2="14" y2="28" stroke="#1A1A17"/><line x1="0" y1="14" x2="4" y2="14" stroke="#1A1A17"/><line x1="24" y1="14" x2="28" y2="14" stroke="#1A1A17"/></svg>`;

function renderBezel(active) {
  const tab = (key, href, label) => `<a href="${href}"${active === key ? ' aria-current="page"' : ''}>${label}</a>`;
  bezel.className = 'bezel';
  bezel.innerHTML = `
    <a class="brand" href="#/ledger" aria-label="RetinaScreen, ledger">${LOGO()}<span>RetinaScreen</span></a>
    <button type="button" class="menu-btn" aria-expanded="false" aria-controls="nav">MENU</button>
    <nav id="nav" class="nav" aria-label="Main">
      ${tab('ledger', '#/ledger', 'Ledger')}<span class="dot" aria-hidden="true">·</span>
      ${tab('new', '#/new', 'New screening')}<span class="dot" aria-hidden="true">·</span>
      ${tab('model', '#/model', 'Model')}
    </nav>
    <div class="bezel-meta"><b>Today</b><span class="eyebrow">${dayStamp(new Date())}</span></div>`;
  const btn = bezel.querySelector('.menu-btn'), nav = bezel.querySelector('.nav');
  btn.addEventListener('click', () => {
    const open = nav.classList.toggle('open');
    btn.setAttribute('aria-expanded', String(open));
  });
}

export function setTitle(text) {
  document.title = text ? `${text} · RetinaScreen` : 'RetinaScreen';
}

export function renderNotFound(path) {
  renderBezel('');
  setTitle('Page not found');
  view.innerHTML = `
    <main id="main" class="state-page">
      <div>
        <h1 class="sr-only" tabindex="-1">Page not found</h1>
        <div aria-hidden="true">
          <div class="chart-row"><span class="n">1</span><span style="font:500 clamp(72px,13vw,190px)/1 var(--serif);letter-spacing:0.05em">PAGE</span><span class="acuity">20/200</span></div>
          <div class="chart-row"><span class="n">2</span><span style="font:500 clamp(46px,8.3vw,120px)/1.05 var(--serif);letter-spacing:0.08em">NOT</span><span class="acuity">20/100</span></div>
          <div class="chart-row"><span class="n">3</span><span style="font:500 clamp(30px,5vw,72px)/1.15 var(--serif);letter-spacing:0.12em">FOUND</span><span class="acuity">20/70</span></div>
        </div>
        <div style="display:flex;align-items:center;gap:28px;flex-wrap:wrap;margin-top:22px">
          <span class="eyebrow" style="font-size:11px;letter-spacing:0.1em">ERR 404 · ${esc(path.toUpperCase())} IS NOT IN THE LEDGER</span>
          <a class="link" href="#/ledger">← Back to ledger</a>
        </div>
      </div>
      <div style="justify-self:center">${lensSVG({ size: 380, state: 'empty' })}</div>
    </main>`;
  focusMain();
}

function renderOffline(retry) {
  renderBezel('ledger');
  setTitle('Instrument offline');
  const last = net.lastContact ? `LAST CONTACT ${hhmmss(net.lastContact)}` : 'NO CONTACT SINCE THIS PAGE OPENED';
  view.innerHTML = `
    <main id="main" class="offline-page">
      <div>${lensSVG({ size: window.innerWidth < 760 ? 300 : 420, state: 'offline' })}</div>
      <div class="stack-words" role="alert">
        <span class="eyebrow" style="margin-bottom:18px">NO RESPONSE FROM ANALYSIS SERVER</span>
        <h1 tabindex="-1" style="display:flex;flex-direction:column;gap:2px;font-weight:500">
          <span class="w1" style="font-size:clamp(52px,7vw,96px)">INSTRUMENT</span>
          <span class="w2" style="font-size:clamp(34px,4.5vw,62px);letter-spacing:0.08em">OFFLINE</span>
          <span class="w3" style="font-size:clamp(24px,2.8vw,40px);letter-spacing:0.12em">— RETRY</span>
        </h1>
        <div style="display:flex;align-items:center;gap:20px;margin-top:28px;flex-wrap:wrap">
          <button type="button" class="btn-primary" id="retry" style="height:52px;font-size:15px">Retry connection<span class="glyph" aria-hidden="true">↻</span></button>
          <span class="eyebrow" style="font-size:11px;line-height:1.6;letter-spacing:0.08em">${last}</span>
        </div>
      </div>
    </main>`;
  view.querySelector('#retry').addEventListener('click', retry);
  focusMain();
}

export function focusMain() {
  const h = view.querySelector('h1');
  if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
}

async function ensureModel() {
  if (!ctx.model) {
    ctx.model = await api('/model');
    const m = ctx.model;
    document.getElementById('foot-model').textContent = `RETINASCREEN · ${m.model_name.replace('_', '-').toUpperCase()} · ${m.img_size} PX`;
  }
  return ctx.model;
}

async function route() {
  const token = ++routeToken;
  if (cleanup) { cleanup(); cleanup = null; }
  const hash = location.hash.replace(/^#/, '') || '/ledger';
  const parts = hash.split('/').filter(Boolean);
  const [page, id] = parts;
  const screens = {
    ledger: { active: 'ledger', fn: renderLedger, ok: parts.length === 1 },
    new: { active: 'new', fn: renderCapture, ok: parts.length === 1 },
    scan: { active: 'new', fn: renderFlow, ok: parts.length === 2 },
    screening: { active: 'ledger', fn: renderDetail, ok: parts.length === 2 },
    model: { active: 'model', fn: renderModel, ok: parts.length === 1 },
  };
  const screen = screens[page];
  window.scrollTo(0, 0);
  if (!screen || !screen.ok) { renderNotFound('/' + parts.join('/')); return; }
  renderBezel(screen.active);
  view.innerHTML = `<main id="main" class="loading" aria-busy="true"><span class="eyebrow">LOADING</span></main>`;
  try {
    const model = await ensureModel();
    if (token !== routeToken) return;
    cleanup = await screen.fn(view, { id, model, isCurrent: () => token === routeToken }) || null;
    if (token === routeToken) focusMain();
  } catch (e) {
    if (token !== routeToken) return;
    if (e instanceof OfflineError) renderOffline(route);
    else if (e instanceof ApiError && e.status === 404) renderNotFound('/' + parts.join('/'));
    else {
      console.error(e);
      view.innerHTML = `<main id="main" class="loading" role="alert"><span class="eyebrow">SOMETHING WENT WRONG · ${esc(e.message || e)}</span></main>`;
    }
  }
}

window.addEventListener('hashchange', route);
route();
