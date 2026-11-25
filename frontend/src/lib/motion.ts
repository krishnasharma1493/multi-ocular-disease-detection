import { useCallback } from 'react';

export const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Calls `run` once, when a third of `el` is on screen (right away if IntersectionObserver is missing). */
export function onArrive(el: Element, run: () => void) {
  if (typeof IntersectionObserver === 'undefined') { run(); return () => {}; }
  const io = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { io.disconnect(); run(); }
  }, { threshold: 0.35 });
  io.observe(el);
  return () => io.disconnect();
}

/**
 * Callback ref that arms an element for a one-time entrance and adds `in` when it scrolls into view.
 * Without script support or with reduced motion nothing is armed, so the content simply shows.
 */
export function useArrive<T extends HTMLElement>() {
  return useCallback((el: T | null) => {
    if (!el || reducedMotion()) return;
    el.classList.add('armed');
    return onArrive(el, () => requestAnimationFrame(() => el.classList.add('in')));
  }, []);
}
