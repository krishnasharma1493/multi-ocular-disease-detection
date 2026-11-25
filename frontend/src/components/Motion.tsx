import { useEffect, useRef } from 'react';
import { onArrive, reducedMotion } from '../lib/motion';

const easeOut = (t: number) => (t === 1 ? 1 : 1 - 2 ** (-10 * t)); // exponential: fast start, slow settle

/**
 * A number that ticks up to its value like an instrument readout. It writes to the DOM directly
 * (no re-render per frame) and starts when it scrolls into view. Screen readers get the final value only.
 */
export function CountUp({ value, format, duration = 1000, delay = 0 }: {
  value: number; format: (v: number) => string; duration?: number; delay?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reducedMotion()) { el.textContent = format(value); return; }
    let frame = 0;
    el.textContent = format(0);
    const stop = onArrive(el, () => {
      const start = performance.now() + delay;
      const tick = (now: number) => {
        const t = Math.min(1, Math.max(0, (now - start) / duration));
        el.textContent = format(value * easeOut(t));
        if (t < 1) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    });
    return () => { stop(); cancelAnimationFrame(frame); };
  }, [value, format, duration, delay]);
  return (
    <>
      <span ref={ref} aria-hidden="true">{format(value)}</span>
      <span className="sr-only">{format(value)}</span>
    </>
  );
}
