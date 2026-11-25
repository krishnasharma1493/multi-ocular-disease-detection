
import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useScreenings } from '../features/screenings/api';
import type { Screening } from '../lib/api/types';
import {
  STATUS_LABEL,
  dayStamp,
  eyeCode,
  eyeWord,
  summarize,
  type Summary,
} from '../lib/format';
import { EyeDots, Lens } from '../components/Lens';
import { Loading, QueryError, useFocusHeading } from '../components/States';

const PAGE_SIZE = 5;

type Item = {
  s: Screening;
  m: Summary;
};

function getStatusDetails(s: Screening) {
  if (s.status === 'pending') {
    if (!s.has_image) {
      return {
        label: 'Add a photo',
        to: `/screenings/${s.id}`,
        actionText: 'Add a photo',
        cls: 'mute',
      };
    }

    return {
      label: 'Waiting for analysis',
      to: `/screenings/${s.id}/scan`,
      actionText: 'View screening',
      cls: 'c-rev',
    };
  }

  return {
    label: 'Result ready',
    to: `/screenings/${s.id}`,
    actionText: 'View result',
    cls: 'c-clr',
  };
}

function ItemRow({ s, m }: Item) {
  const statusInfo = getStatusDetails(s);
  const g = STATUS_LABEL[m.status];

  const eye = eyeCode(s.eye);
  const eyeDirection = eyeWord(s.eye);

  const eyeLabel =
    eyeDirection === 'left'
      ? 'Left eye'
      : eyeDirection === 'right'
        ? 'Right eye'
        : 'Eye unrecorded';

  const dateFormatted = dayStamp(m.created);

  return (
    <Link viewTransition
      className="item"
      to={statusInfo.to}
      aria-label={`Screening from ${dateFormatted}, ${eyeLabel}. Status: ${statusInfo.label}. ${m.verdict}. ${statusInfo.actionText}.`}
    >
      <span className="hole" aria-hidden="true" />

      <span className="lens-thumb" aria-hidden="true">
        {m.status === 'pending' ? (
          <Lens size={72} state="empty" />
        ) : (
          <Lens
            size={72}
            values={m.vals}
            thresholds={m.ths}
            eye={eye ?? 'R'}
          />
        )}
      </span>

      <span className="who" aria-hidden="true">
        <span
          className="ref"
          style={{
            font: '600 15px/1.2 var(--sans)',
            letterSpacing: '0.02em',
          }}
        >
          {dateFormatted}
        </span>

        <span
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          <EyeDots eye={eye} dot={9} />

          <span className="mono mute" style={{ fontSize: 11 }}>
            {eyeLabel.toUpperCase()}
          </span>
        </span>
      </span>

      <span className="what" aria-hidden="true">
        <b>{m.verdict}</b>
        <span>{m.sub}</span>
      </span>

      <span
        className={`state ${
          m.status === 'pending' ? statusInfo.cls : g.cls
        }`}
        aria-hidden="true"
      >
        <span>{statusInfo.label}</span>

        {s.latest_review === 'disagree' ? (
          <span className="stamp-sm">✕ REVIEW DIFFERED</span>
        ) : s.status === 'reviewed' ? (
          <span className="mute" style={{ fontSize: 10 }}>
            ✓ REVIEWED
          </span>
        ) : null}

        <span
          className="link"
          style={{
            fontSize: 12,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          {statusInfo.actionText} →
        </span>
      </span>
    </Link>
  );
}

export function LedgerPage() {
  const list = useScreenings({
    page: 1,
    limit: PAGE_SIZE,
  });

  const h = useFocusHeading<HTMLHeadingElement>(!!list.data);

  useEffect(() => {
    document.title = 'My screenings · RetinaScreen';
  }, []);

  if (list.isPending) {
    return <Loading label="Loading your screenings" />;
  }

  if (list.error) {
    return (
      <QueryError
        error={list.error}
        path="/"
        onRetry={() => list.refetch()}
      />
    );
  }

  const data = list.data;

  const items: Item[] = (data?.data ?? []).map((s) => ({
    s,
    m: summarize(s),
  }));

  const total = data?.pagination.total ?? 0;

  const hasMore =
    total > items.length ||
    (data?.pagination.total_pages ?? 1) > 1;

  return (
    <main id="main">
      <div className="page-head">
        <div className="titles">
          <h1 ref={h} tabIndex={-1}>
            Your eye screenings
          </h1>

          <p className="mute" style={{ fontSize: 16 }}>
            View your previous screening results or start a new eye screening.
          </p>
        </div>
      </div>

      <div className="list-wrap">
        {/* Start a screening */}
        <section
          aria-labelledby="start-h"
          className="tag"
          style={{
            clipPath: 'none',
            border: '1px solid var(--ink)',
            padding: '24px 28px',
          }}
        >
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 12,
            }}
          >
            <h2
              id="start-h"
              style={{
                font: '500 28px/1.1 var(--serif)',
                letterSpacing: '-0.015em',
              }}
            >
              Start a screening
            </h2>

            <p
              style={{
                color: 'var(--body)',
                fontSize: 15,
                lineHeight: 1.5,
                maxWidth: 680,
              }}
            >
              Upload a fundus photo taken at an eye clinic or using a
              compatible phone attachment with a 20D lens. We will first
              check the photo quality and then screen for four eye diseases.
            </p>

            <div style={{ marginTop: 4 }}>
              <Link viewTransition
                to="/screenings/new"
                className="btn-primary"
                style={{
                  display: 'inline-flex',
                  width: 'auto',
                  padding: '0 24px',
                  height: 48,
                  fontSize: 15,
                }}
              >
                <span>Start a screening</span>
                <span className="glyph" aria-hidden="true">
                  →
                </span>
              </Link>
            </div>
          </div>
        </section>

        {/* Previous screening results */}
        <section
          aria-labelledby="results-h"
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 16,
            marginTop: 8,
          }}
        >
          <div className="section-head">
            <h2 id="results-h">Your results</h2>
          </div>

          {!items.length ? (
            <div className="empty-list" style={{ padding: '24px 0' }}>
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 12,
                }}
              >
                <h3
                  style={{
                    font: '500 28px/1.2 var(--serif)',
                    margin: 0,
                  }}
                >
                  No screenings yet
                </h3>

                <p
                  style={{
                    color: 'var(--graphite)',
                    fontSize: 15,
                    margin: 0,
                    maxWidth: 540,
                  }}
                >
                  Your previous screening results will appear here. Start
                  your first screening to get started.
                </p>

                <div style={{ marginTop: 8 }}>
                  <Link viewTransition
                    to="/screenings/new"
                    className="btn-primary"
                    style={{
                      display: 'inline-flex',
                      width: 'auto',
                      padding: '0 22px',
                      height: 48,
                      fontSize: 15,
                    }}
                  >
                    <span>Start a screening</span>
                    <span className="glyph" aria-hidden="true">
                      →
                    </span>
                  </Link>
                </div>
              </div>
            </div>
          ) : (
            <div className="rows">
              {items.map((item) => (
                <ItemRow key={item.s.id} {...item} />
              ))}

              {hasMore && (
                <div style={{ marginTop: 14 }}>
                  <Link viewTransition className="link" to="/screenings">
                    See all results →
                  </Link>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
