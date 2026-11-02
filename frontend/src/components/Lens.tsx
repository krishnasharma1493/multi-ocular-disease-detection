import { lensSVG, type LensProps } from '../lib/lens';

/** The signature LensReadout dial. Decorative unless a label is given (then role="img"). */
export function Lens({ label, className, ...props }: LensProps & { label?: string; className?: string }) {
  return (
    <div
      className={className}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      dangerouslySetInnerHTML={{ __html: lensSVG(props) }}
    />
  );
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true" focusable="false">
      <circle cx="14" cy="14" r="12.5" fill="none" stroke="currentColor" />
      <circle cx="14" cy="14" r="7.5" fill="none" stroke="currentColor" strokeWidth="3" />
      <circle cx="14" cy="14" r="1.8" fill="currentColor" />
      <line x1="14" y1="0" x2="14" y2="4" stroke="currentColor" />
      <line x1="14" y1="24" x2="14" y2="28" stroke="currentColor" />
      <line x1="0" y1="14" x2="4" y2="14" stroke="currentColor" />
      <line x1="24" y1="14" x2="28" y2="14" stroke="currentColor" />
    </svg>
  );
}

export function EyeDots({ eye, dot = 11 }: { eye: 'L' | 'R' | null; dot?: number }) {
  const d = (on: boolean) => <span className="eye-dot" style={{ width: dot, height: dot, background: on ? 'var(--ink)' : 'transparent' }} />;
  return (
    <span className="eye-dots" aria-label={eye === 'L' ? 'left eye' : eye === 'R' ? 'right eye' : 'eye not recorded'}>
      L{d(eye === 'L')}{d(eye === 'R')}R
    </span>
  );
}
