import { Component, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { apiErrorMessage, apiStatus, isOffline } from '../lib/api/types';
import { hhmmss } from '../lib/format';
import { Lens } from './Lens';

const useSmall = () => {
  const [small, setSmall] = useState(() => window.innerWidth < 760);
  useEffect(() => {
    const on = () => setSmall(window.innerWidth < 760);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return small;
};

/** Moves focus to the page heading after a route change, for keyboard and screen-reader users. */
export function useFocusHeading<T extends HTMLElement>(ready = true) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (ready) ref.current?.focus({ preventScroll: true });
  }, [ready]);
  return ref;
}

export function Loading({ label = 'LOADING' }: { label?: string }) {
  return (
    <main id="main" className="loading" aria-busy="true">
      <div className="loading-inner">
        <Lens size={160} state="empty" className="pulse" />
        <span className="eyebrow" role="status">{label}</span>
      </div>
    </main>
  );
}

export function NotFound({ path }: { path: string }) {
  const h = useFocusHeading<HTMLHeadingElement>();
  const small = useSmall();
  useEffect(() => { document.title = 'Page not found · RetinaScreen'; }, []);
  return (
    <main id="main" className="state-page">
      <div>
        <h1 ref={h} tabIndex={-1} className="sr-only">Page not found</h1>
        <div aria-hidden="true">
          <div className="chart-row"><span className="n">1</span><span className="chart-w" style={{ font: '500 clamp(72px,13vw,190px)/1 var(--serif)', letterSpacing: '0.05em' }}>PAGE</span><span className="acuity">20/200</span></div>
          <div className="chart-row"><span className="n">2</span><span className="chart-w" style={{ font: '500 clamp(46px,8.3vw,120px)/1.05 var(--serif)', letterSpacing: '0.08em' }}>NOT</span><span className="acuity">20/100</span></div>
          <div className="chart-row"><span className="n">3</span><span className="chart-w" style={{ font: '500 clamp(30px,5vw,72px)/1.15 var(--serif)', letterSpacing: '0.12em' }}>FOUND</span><span className="acuity">20/70</span></div>
        </div>
        <div className="state-actions">
          <span className="eyebrow" style={{ fontSize: 11, letterSpacing: '0.1em' }}>ERR 404 · {path.toUpperCase()} IS NOT IN THE LEDGER</span>
          <Link className="link" to="/">← Back to ledger</Link>
        </div>
      </div>
      <div style={{ justifySelf: 'center' }}><Lens size={small ? 260 : 380} state="empty" /></div>
    </main>
  );
}

export function Offline({ onRetry }: { onRetry: () => void }) {
  const h = useFocusHeading<HTMLHeadingElement>();
  const small = useSmall();
  const [last] = useState(() => new Date());
  useEffect(() => { document.title = 'Instrument offline · RetinaScreen'; }, []);
  return (
    <main id="main" className="offline-page">
      <Lens size={small ? 280 : 420} state="offline" />
      <div className="stack-words" role="alert">
        <span className="eyebrow" style={{ marginBottom: 18 }}>NO RESPONSE FROM ANALYSIS SERVER</span>
        <h1 ref={h} tabIndex={-1} className="stack-h">
          <span className="w1" style={{ fontSize: 'clamp(52px,7vw,96px)' }}>INSTRUMENT</span>
          <span className="w2" style={{ fontSize: 'clamp(34px,4.5vw,62px)', letterSpacing: '0.08em' }}>OFFLINE</span>
          <span className="w3" style={{ fontSize: 'clamp(24px,2.8vw,40px)', letterSpacing: '0.12em' }}>— RETRY</span>
        </h1>
        <div className="state-actions" style={{ marginTop: 28 }}>
          <button type="button" className="btn-primary" style={{ height: 52, fontSize: 15 }} onClick={onRetry}>
            Retry connection<span className="glyph" aria-hidden="true">↻</span>
          </button>
          <span className="eyebrow" style={{ fontSize: 11, lineHeight: 1.6, letterSpacing: '0.08em' }}>NO CONTACT AT {hhmmss(last)}</span>
        </div>
      </div>
    </main>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const h = useFocusHeading<HTMLHeadingElement>();
  return (
    <main id="main" className="loading">
      <div className="error-state" role="alert">
        <span className="label c-pos">▲ ERR · REQUEST FAILED</span>
        <h1 ref={h} tabIndex={-1}>{message}</h1>
        {onRetry && <button type="button" className="btn" onClick={onRetry}>Try again</button>}
      </div>
    </main>
  );
}

/** One place that turns a failed query into the right system state. */
export function QueryError({ error, onRetry, path }: { error: unknown; onRetry: () => void; path: string }) {
  if (isOffline(error)) return <Offline onRetry={onRetry} />;
  if (apiStatus(error) === 404) return <NotFound path={path} />;
  return <ErrorState message={apiErrorMessage(error)} onRetry={onRetry} />;
}

type BoundaryState = { error: Error | null };
export class ErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null };
  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="frame">
        <main id="main" className="loading">
          <div className="error-state" role="alert">
            <span className="label c-pos">▲ ERR · THE PAGE FAILED TO DRAW</span>
            <h1>Something went wrong on this screen.</h1>
            <button type="button" className="btn" onClick={() => window.location.reload()}>Reload</button>
          </div>
        </main>
      </div>
    );
  }
}
