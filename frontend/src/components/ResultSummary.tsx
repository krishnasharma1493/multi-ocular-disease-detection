import { Link } from 'react-router-dom';
import type { Screening } from '../lib/api/types';
import './ResultSummary.css';

/** The patient's plain-language reading of one screening. Every word comes from the server's `summary`,
 *  so the page, the chat and the API agree. It sits under the readings, which stay as they are. */
export function ResultSummary({ s }: { s: Screening }) {
  const sum = s.summary;
  if (!sum) return null;
  const hasResult = sum.state === 'result' || sum.state === 'experimental';
  const soon = sum.next_step.urgency === 'soon';
  return (
    <section className="rsum" aria-labelledby="rsum-h">
      <div className="rsum-head">
        <span className="eyebrow">IN PLAIN WORDS</span>
        <h2 id="rsum-h">What this means</h2>
      </div>
      <div className="rsum-body">
        {sum.state === 'experimental' && (
          <div className="rsum-block wide">
            <div className="notice notice-amber" role="note">
              <span className="label">EXPERIMENTAL RESULT</span>
              <p>{sum.headline}</p>
            </div>
          </div>
        )}
        <div className="rsum-block wide">
          <h3>WHAT THE SCREENING FOUND</h3>
          {sum.state !== 'experimental' && <p className="rsum-headline">{sum.headline}</p>}
          {sum.state === 'no_photo' && (
            <p>Add a photo to start. You can use the “Upload photo” button above.</p>
          )}
          {sum.state === 'waiting' && (
            <p><Link viewTransition className="link" to={`/screenings/${s.id}/scan`}>Run the screening →</Link></p>
          )}
          {hasResult && (
            <ul>
              {sum.findings.map((f) => (
                <li key={f.code}>
                  <span className={f.flagged ? 'rsum-flag' : undefined}>{f.plain}</span>
                  {f.borderline && <> <span className="rsum-less">LESS CERTAIN · CLOSE TO THE CUT-OFF</span></>}
                </li>
              ))}
            </ul>
          )}
        </div>
        {sum.quality && (
          <div className="rsum-block">
            <h3>PHOTO QUALITY</h3>
            <p><b>{sum.quality.label}.</b> {sum.quality.detail}</p>
          </div>
        )}
        {hasResult && (
          <div className="rsum-block">
            <h3>HOW SURE IS THIS?</h3>
            {sum.uncertainty.length ? <ul>{sum.uncertainty.map((u) => <li key={u}>{u}</li>)}</ul>
              : <p>Nothing here suggests the screening was unsure, but it can still be wrong.</p>}
          </div>
        )}
        <div className="rsum-block wide">
          <h3>WHAT TO DO NEXT</h3>
          <div className={`rsum-next${soon ? ' soon' : ''}`}><p>{sum.next_step.text}</p></div>
          <p className="rsum-urgent">{sum.urgent_care}</p>
        </div>
        <div className="rsum-block wide" style={{ borderBottom: 0 }}>
          <h3>GOOD TO KNOW</h3>
          <p>This is a screening, not a diagnosis. {s.result?.disclaimer ?? 'Only an eye doctor can tell you what is going on with your eyes.'}</p>
          <ul>{sum.limits.filter((l) => !/not a diagnosis/i.test(l)).map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      </div>
    </section>
  );
}
