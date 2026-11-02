import { useEffect, useRef, useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthProvider';
import { dayStamp } from '../lib/format';
import { Logo } from './Lens';

export function Footer() {
  return (
    <footer className="foot">
      <span>RESEARCH PROTOTYPE — NOT A DIAGNOSIS — CONFIRM WITH AN OPHTHALMOLOGIST</span>
      <span className="mute">RETINASCREEN · EFFICIENTNET-B0</span>
    </footer>
  );
}

const TABS: [string, string][] = [
  ['/', 'Ledger'],
  ['/screenings', 'Screenings'],
  ['/screenings/new', 'New screening'],
  ['/model', 'Model'],
];

export function AppShell() {
  const { logout } = useAuth();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navRef = useRef<HTMLElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => setOpen(false), [location.pathname]);

  // Mobile menu: Escape closes it and focus stays inside while open
  useEffect(() => {
    if (!open) return;
    const nav = navRef.current;
    nav?.querySelector<HTMLElement>('a')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setOpen(false); btnRef.current?.focus(); return; }
      if (e.key !== 'Tab' || !nav) return;
      const items = [btnRef.current, ...nav.querySelectorAll<HTMLElement>('a, button')].filter(Boolean) as HTMLElement[];
      const i = items.indexOf(document.activeElement as HTMLElement);
      if (e.shiftKey && i <= 0) { e.preventDefault(); items[items.length - 1].focus(); }
      else if (!e.shiftKey && i === items.length - 1) { e.preventDefault(); items[0].focus(); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <div className="frame">
      <a className="skip" href="#main">Skip to content</a>
      <header className="bezel">
        <Link className="brand" to="/" aria-label="RetinaScreen, ledger"><Logo /><span>RetinaScreen</span></Link>
        <button ref={btnRef} type="button" className="menu-btn" aria-expanded={open} aria-controls="nav" onClick={() => setOpen((o) => !o)}>
          {open ? 'CLOSE' : 'MENU'}
        </button>
        <nav id="nav" ref={navRef} className={`nav${open ? ' open' : ''}`} aria-label="Main">
          {TABS.map(([to, label], i) => (
            <span key={to} style={{ display: 'contents' }}>
              {i > 0 && <span className="dot" aria-hidden="true">·</span>}
              <NavLink to={to} end>{label}</NavLink>
            </span>
          ))}
          <button type="button" className="nav-signout" onClick={logout}>Sign out</button>
        </nav>
        <div className="bezel-meta">
          <b>Today</b>
          <span className="eyebrow">{dayStamp(new Date())}</span>
        </div>
        <span className="bezel-rule" aria-hidden="true" />
        <button type="button" className="signout" onClick={logout}>Sign out</button>
      </header>
      <div className="view">
        <Outlet />
      </div>
      <Footer />
    </div>
  );
}
