import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useChat, useSendChat } from '../features/chat/api';
import { CHAT_HOURLY_LIMIT, CHAT_MAX_CHARS, type ChatMessage, type ChatSource } from '../features/chat/types';
import { apiError, apiErrorMessage, apiStatus, isOffline, parseUtc } from '../lib/api/types';
import { hhmm } from '../lib/format';
import './ChatPanel.css';

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
    return 'Sources are National Eye Institute (NEI) pages, not yet reviewed by the project’s ophthalmologist.';
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
  const logEnd = useRef<HTMLLIElement>(null);
  const ids = { heading: useId(), help: useId(), count: useId() };
  const messages = thread.data ?? [];

  useEffect(() => {
    if (pending || messages.length) logEnd.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [pending, messages.length]);

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

  return (
    <section className="chat" aria-labelledby={ids.heading}>
      <div className="chat-head">
        <h2 id={ids.heading}>Ask about your eyes</h2>
        <p className="chat-intro" id={ids.help}>
          Ask about eye diseases, symptoms, risk factors, tests and treatments, or about your own screenings and history.
        </p>
      </div>

      <div className="chat-body">
        {thread.isPending ? (
          <p className="eyebrow" role="status">LOADING CONVERSATION</p>
        ) : loadProblem ? (
          <div className="notice notice-amber" role="alert">
            <span className="label">▲ CHAT</span>
            <p>{loadProblem.text}</p>
            <button type="button" className="btn btn-sm" onClick={() => thread.refetch()}>Try again</button>
          </div>
        ) : (
          <ol className="chat-log" role="log" aria-live="polite" aria-relevant="additions" aria-label="Conversation, oldest first">
            {messages.length === 0 && !pending && (
              <li className="chat-empty mute">No questions yet. For example: “What does my result mean?”</li>
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
                  <p className="chat-text chat-dots"><span aria-hidden="true">…</span><span className="sr-only">Writing an answer</span></p>
                </li>
              </>
            )}
            <li ref={logEnd} aria-hidden="true" className="chat-end" />
          </ol>
        )}

        {problem && failed && (
          <div className={`notice ${apiStatus(failed.error) === 429 ? 'notice-amber' : 'notice-red'}`} role="alert">
            <span className="label">▲ NOT SENT</span>
            <p>{problem.text}</p>
            {problem.retry && (
              <button type="button" className="btn btn-sm" onClick={() => void ask(failed.message)} disabled={send.isPending}>
                Retry
              </button>
            )}
          </div>
        )}

        <form className="chat-form" onSubmit={submit} noValidate>
          <label htmlFor={`${ids.heading}-q`} className="label">YOUR QUESTION</label>
          <textarea
            id={`${ids.heading}-q`}
            ref={input}
            className="notes chat-input"
            rows={3}
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
          <div className="chat-actions">
            <span className="hint mono" id={ids.count}>
              {draft.length} / {CHAT_MAX_CHARS}<span className="sr-only"> characters. Enter sends, Shift+Enter adds a new line.</span>
            </span>
            <button type="submit" className="btn btn-ink" disabled={send.isPending || !draft.trim() || over || !!thread.error}>
              {send.isPending ? 'Sending…' : 'Send'}
            </button>
          </div>
          <p className="chat-disclaimer">Answers are general information, not a diagnosis. For urgent symptoms, seek care now.</p>
        </form>
      </div>
    </section>
  );
}
