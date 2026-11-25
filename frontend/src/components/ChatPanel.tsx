import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useChat, useSendChat } from '../features/chat/api';
import { CHAT_HOURLY_LIMIT, CHAT_MAX_CHARS, type ChatMessage, type ChatSource } from '../features/chat/types';
import { apiError, apiErrorMessage, apiStatus, isOffline, parseUtc } from '../lib/api/types';
import { hhmm } from '../lib/format';
import './ChatPanel.css';

const SUGGESTIONS = ['What does my result mean?', 'What should I do next?', 'How reliable is this screening?'];
const UNAVAILABLE = 'The assistant is unavailable right now. Your screening result above is still available.';

/** Plain-language text for a failed send or load; `retry` says whether trying again can help. */
function describe(err: unknown): { text: string; retry: boolean } {
  if (isOffline(err)) return { text: apiErrorMessage(err), retry: true }; // the app's offline wording
  const status = apiStatus(err);
  if (status === 503) return { text: UNAVAILABLE, retry: true };
  if (status === 429) {
    return { text: `You can ask up to ${CHAT_HOURLY_LIMIT} questions about each screening per hour. Please try again later.`, retry: false };
  }
  const fields = apiError(err)?.fields;
  if (status === 400 && fields) return { text: Object.values(fields).flat().join(' '), retry: false };
  return { text: apiErrorMessage(err), retry: true };
}

function reviewNote(sources: ChatSource[]) {
  const statuses = [...new Set(sources.map((s) => s.review_status))];
  if (statuses.every((s) => s.startsWith('not reviewed'))) {
    return 'Sources are patient pages from the National Eye Institute (NEI).';
  }
  return `Sources are National Eye Institute (NEI) pages · ${statuses.join(' · ')}.`;
}

function Sources({ sources }: { sources: ChatSource[] }) {
  if (!sources.length) return null;
  return (
    <div className="chat-sources">
      <span className="label">SOURCES</span>
      <ol>
        {sources.map((src) => (
          <li key={src.id}>
            <span className="mono chat-sid">{src.id}</span>
            <a href={src.url} target="_blank" rel="noopener noreferrer">
              {src.title}
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
            <span className="chat-src-meta">{src.section.replace(`${src.title} > `, '')} · updated {src.version}</span>
          </li>
        ))}
      </ol>
      <p className="chat-src-note">{reviewNote(sources)}</p>
    </div>
  );
}

function Message({ m }: { m: ChatMessage }) {
  const mine = m.role === 'user';
  return (
    <li className={`chat-msg ${mine ? 'chat-me' : 'chat-ai'}`}>
      <span className="chat-who">
        <span className="label">{mine ? 'YOU' : 'ASSISTANT'}</span>
        <span className="mono mute">{hhmm(parseUtc(m.created_at))}</span>
      </span>
      <p className="chat-text">{m.content}</p>
      {!mine && <Sources sources={m.sources} />}
    </li>
  );
}

/** Eye-health chat under a screening result. Answers come from the server; the API key never reaches the browser. */
export function ChatPanel({ screeningId }: { screeningId: number }) {
  const thread = useChat(screeningId);
  const send = useSendChat(screeningId);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState<string | null>(null); // optimistic question while waiting
  const [failed, setFailed] = useState<{ message: string; error: unknown } | null>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLOListElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const heroRef = useRef<HTMLParagraphElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const ids = { heading: useId(), help: useId(), count: useId() };
  const messages = thread.data ?? [];

  // Keep the newest message in view inside the panel (scrollIntoView would also move the page)
  useEffect(() => {
    const el = log.current;
    if (el && (pending || messages.length)) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, [pending, messages.length]);

  // Scroll sequence (see ChatPanel.css). u = how far the stage has come up, in screen heights:
  // the screen darkens, the title rises and grows, then settles into the header as the chat appears.
  useEffect(() => {
    const el = stage.current;
    const hero = heroRef.current;
    const title = titleRef.current;
    if (!el || !hero || !title) return;
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    el.dataset.still = String(still);
    let frame = 0;
    const clamp = (v: number) => Math.min(1, Math.max(0, v));
    const ease = (t: number) => t * t * (3 - 2 * t);
    const seg = (u: number, a: number, b: number) => clamp((u - a) / (b - a));
    const set = (vars: Record<string, number | string>) => {
      for (const [k, v] of Object.entries(vars)) el.style.setProperty(k, typeof v === 'number' ? v.toFixed(4) : v);
    };
    const update = () => {
      frame = 0;
      if (still) {
        set({ '--dim': 0, '--panel': 1, '--hero-o': 0, '--title-o': 1, '--reveal': 1 });
        el.dataset.ready = 'true';
        return;
      }
      const vh = window.innerHeight;
      const r = el.getBoundingClientRect();
      const box = el.querySelector('.chat')!.getBoundingClientRect();
      const t = title.getBoundingClientRect();
      const s0 = parseFloat(getComputedStyle(title).fontSize) / parseFloat(getComputedStyle(hero).fontSize);
      const dx = t.left + t.width / 2 - (box.left + box.width / 2);
      const dy = t.top + t.height / 2 - (box.top + box.height / 2);
      const u = (vh - r.top) / vh;
      const dim = ease(seg(u, 0.3, 0.95));
      const grow = ease(seg(u, 0.4, 1.2));
      const settle = ease(seg(u, 1.25, 1.65));
      const scale = settle > 0 ? 1 + (s0 - 1) * settle : s0 + (1 - s0) * grow;
      const reveal = ease(seg(u, 1.62, 1.95));
      const pinned = r.top <= 0.5;
      set({
        '--dim': pinned ? 1 : dim, '--panel': pinned ? 1 : 0, '--ink-mix': `${(dim * 100).toFixed(1)}%`,
        '--hero-s': scale, '--hero-x': `${(dx * settle).toFixed(1)}px`, '--hero-y': `${(dy * settle).toFixed(1)}px`,
        '--hero-o': 1 - seg(u, 1.62, 1.7), '--title-o': seg(u, 1.62, 1.7), '--reveal': reveal,
      });
      el.dataset.ready = String(reveal > 0.6);
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(update); };
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      cancelAnimationFrame(frame);
    };
  }, []);

  // Keyboard users who tab into the chat skip the animation and land on the finished panel
  const onFocusIn = () => {
    const el = stage.current;
    if (!el || el.dataset.ready === 'true') return;
    window.scrollTo({ top: window.scrollY + el.getBoundingClientRect().top + window.innerHeight, behavior: 'auto' });
  };

  const ask = async (text: string) => {
    const message = text.trim();
    if (!message || send.isPending) return;
    setFailed(null);
    setPending(message);
    setDraft('');
    try {
      await send.mutateAsync(message);
    } catch (error) {
      setFailed({ message, error });
      setDraft((d) => d || message); // give the question back so nothing typed is lost
    } finally {
      setPending(null);
      input.current?.focus();
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(draft);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void ask(draft);
    }
  };

  const problem = failed ? describe(failed.error) : null;
  const loadProblem = thread.error ? describe(thread.error) : null;
  const over = draft.length > CHAT_MAX_CHARS;
  const fit = (el: HTMLTextAreaElement) => {
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  };
  useEffect(() => {
    if (input.current) fit(input.current);
  }, [draft]);

  return (
    <div className="chat-stage" ref={stage} onFocus={onFocusIn}>
      <div className="chat-dim" aria-hidden="true" />
      <section className="chat" aria-labelledby={ids.heading}>
        <p className="chat-hero" ref={heroRef} aria-hidden="true">Ask about your eyes</p>
        <div className="chat-inner">
          <header className="chat-head">
            <div>
              <span className="label chat-kicker">EYE-HEALTH ASSISTANT</span>
              <h2 id={ids.heading} ref={titleRef}>Ask about your eyes</h2>
            </div>
            <button type="button" className="chat-back" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
              <span aria-hidden="true">↑</span><span className="chat-back-text"> Back to result</span>
            </button>
            <p className="chat-intro" id={ids.help}>
              Ask about eye diseases, symptoms, risk factors, tests and treatments, or about your own screenings and history.
            </p>
          </header>

          {thread.isPending ? (
            <p className="label chat-status chat-rise" role="status">LOADING CONVERSATION</p>
          ) : loadProblem ? (
            <div className="notice notice-amber chat-rise" role="alert">
              <span className="label">▲ CHAT</span>
              <p>{loadProblem.text}</p>
              <button type="button" className="btn btn-sm" onClick={() => thread.refetch()}>Try again</button>
            </div>
          ) : (
            <ol ref={log} className="chat-log chat-rise" role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation, oldest first">
              {messages.length === 0 && !pending && (
                <li className="chat-empty">
                  <p>Not sure where to start? Try one of these:</p>
                  <div className="chat-chips">
                    {SUGGESTIONS.map((q) => (
                      <button key={q} type="button" className="chat-chip" onClick={() => void ask(q)} disabled={send.isPending}>
                        {q}
                      </button>
                    ))}
                  </div>
                </li>
              )}
              {messages.map((m) => <Message key={m.id} m={m} />)}
              {pending && (
                <>
                  <li className="chat-msg chat-me chat-pending">
                    <span className="chat-who"><span className="label">YOU</span></span>
                    <p className="chat-text">{pending}</p>
                  </li>
                  <li className="chat-msg chat-ai chat-pending">
                    <span className="chat-who"><span className="label">ASSISTANT</span></span>
                    <p className="chat-text chat-dots"><i /><i /><i /><span className="sr-only">Writing an answer</span></p>
                  </li>
                </>
              )}
            </ol>
          )}

          {problem && failed && (
            <div className={`notice chat-rise ${apiStatus(failed.error) === 429 ? 'notice-amber' : 'notice-red'}`} role="alert">
              <span className="label">▲ NOT SENT</span>
              <p>{problem.text}</p>
              {problem.retry && (
                <button type="button" className="btn btn-sm" onClick={() => void ask(failed.message)} disabled={send.isPending}>
                  Retry
                </button>
              )}
            </div>
          )}

          <form className="chat-form chat-rise" onSubmit={submit} noValidate>
            <label htmlFor={`${ids.heading}-q`} className="sr-only">Your question</label>
            <div className="chat-bar">
              <textarea
                id={`${ids.heading}-q`}
                ref={input}
                className="chat-input"
                rows={1}
                value={draft}
                maxLength={CHAT_MAX_CHARS}
                readOnly={send.isPending}
                aria-disabled={send.isPending}
                aria-describedby={`${ids.help} ${ids.count}`}
                aria-invalid={over}
                placeholder="Type a question about your eyes"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKey}
              />
              <button type="submit" className="chat-send" disabled={send.isPending || !draft.trim() || over || !!thread.error}
                aria-label={send.isPending ? 'Sending' : 'Send'}>
                <span aria-hidden="true">{send.isPending ? '…' : '↑'}</span>
              </button>
            </div>
            <div className="chat-foot">
              <span>Answers are general information, not a diagnosis. For urgent symptoms, seek care now.</span>
              <span className="mono" id={ids.count} aria-hidden={draft.length < CHAT_MAX_CHARS * 0.8}>
                {draft.length >= CHAT_MAX_CHARS * 0.8 ? `${draft.length} / ${CHAT_MAX_CHARS}` : ''}
                <span className="sr-only"> Enter sends, Shift+Enter adds a new line.</span>
              </span>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
