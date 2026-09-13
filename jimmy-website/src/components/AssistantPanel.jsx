import React, { useEffect } from 'react';
import {
  Sparkles,
  X,
  LoaderCircle,
  AlertCircle,
  RotateCcw,
  ArrowUpRight,
  ArrowRight,
  Info
} from 'lucide-react';

export function AssistantPanel({
  assistantOpen,
  setAssistantOpen,
  busy,
  askError,
  answer,
  question,
  setQuestion,
  ask,
  selectEvidence,
  input,
  prompts
}) {
  if (!assistantOpen) return null;

  useEffect(() => {
    if (input?.current) {
      input.current.style.height = 'auto';
      input.current.style.height = `${Math.min(input.current.scrollHeight, 160)}px`;
    }
  }, [question, assistantOpen, input]);

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!busy && question.trim()) {
        ask(question);
      }
    }
  }

  function renderAnswerText(text = answer?.answer) {
    if (!text) return null;
    const ids = new Map((answer?.evidence || []).map(e => [e.id, e]));
    return text.split(/(\[[^\]]+\])/g).map((part, i) => {
      const e = ids.get(part.slice(1, -1));
      return e ? (
        <button key={i} className="citation" onClick={() => selectEvidence(e)}>
          {e.data.place || e.data.company_name || e.data.listing?.ticker || e.id}
          <ArrowUpRight size={11} />
        </button>
      ) : (
        <React.Fragment key={i}>{part}</React.Fragment>
      );
    });
  }

  return (
    <aside className="insight-panel" aria-label="Dataset query assistant">
      <div className="panel-heading">
        <div className="assistant-title">
          <span className="assistant-status">
            <Sparkles size={16} />
          </span>
          <span>
            Data Query Assistant
            <small>Natural-language query</small>
          </span>
        </div>
        <button
          className="icon-button"
          onClick={() => setAssistantOpen(false)}
          aria-label="Close assistant"
        >
          <X size={16} />
        </button>
      </div>

      <div className="panel-body" aria-live="polite">
            {busy ? (
              <div className="working-timeline">
                <div className="timeline-header">
                  <LoaderCircle className="spin" size={14} />
                  <span>Running analytical query</span>
                </div>
                <div className="timeline-stages">
                  <div className="timeline-stage active">
                    <span className="stage-pill thinking">Thinking</span>
                    <span className="stage-text">Parsing intent and spatial parameters</span>
                  </div>
                  <div className="timeline-stage">
                    <span className="stage-pill grep">Grepping</span>
                    <span className="stage-text">Scanning 500 companies and 12,936 plumes</span>
                  </div>
                  <div className="timeline-stage">
                    <span className="stage-pill read">Reading</span>
                    <span className="stage-text">Cross-referencing SEC disclosures and EPA GHGRP</span>
                  </div>
                  <div className="timeline-stage">
                    <span className="stage-pill edit">Auditing</span>
                    <span className="stage-text">Verifying target gaps and rank intervals</span>
                  </div>
                </div>
              </div>
            ) : askError ? (
              <div className="assistant-error">
                <AlertCircle size={24} />
                <h3>Query could not be completed</h3>
                <p>{askError}</p>
                <button className="secondary" onClick={() => ask(question)}>
                  <RotateCcw size={14} />
                  Try again
                </button>
              </div>
            ) : answer ? (
              <div className="answer-content">
                <div className="answer-header">
                  <span className="stage-pill done">Done</span>
                  <span className="eyebrow">
                    {answer.status === 'needs_clarification'
                      ? 'MORE CONTEXT NEEDED'
                      : answer.status === 'data_only'
                      ? 'RECORDS RETRIEVED'
                      : 'DECISION BRIEF'}
                  </span>
                </div>
                <h3>
                  {answer.brief?.headline ||
                    (answer.status === 'no_results'
                      ? 'No matching evidence'
                      : answer.status === 'needs_clarification'
                      ? 'A limit in the evidence'
                      : `${answer.evidence?.length || 0} records retrieved`)}
                </h3>
                {answer.brief && (
                  <>
                    <div className="brief-meta">
                      <span className={`confidence ${answer.brief.confidence}`}>
                        {answer.brief.confidence} confidence
                      </span>
                      {answer.tool_calls?.length > 0 && (
                        <span>{answer.tool_calls.length} analyses</span>
                      )}
                    </div>
                    <h4>Key findings</h4>
                    <ul className="brief-list">
                      {answer.brief.findings.map((finding, i) => (
                        <li key={i}>{renderAnswerText(finding)}</li>
                      ))}
                    </ul>
                    <h4>Recommended actions</h4>
                    <ol className="brief-list actions">
                      {answer.brief.recommended_actions.map((action, i) => (
                        <li key={i}>{action}</li>
                      ))}
                    </ol>
                  </>
                )}
                <div className="answer-text">{renderAnswerText()}</div>
                {answer.web_research && <section aria-label="Web research">
                  <h4>Web research · external sources</h4>
                  <p className="answer-text">{answer.web_research.answer}</p>
                  {answer.web_research.supports?.map((support, i) => <p key={i}><small>{support.segment?.text} {support.groundingChunkIndices?.map(index => {
                    const source = answer.web_research.sources.find(s => s.id === index + 1);
                    return source ? <a key={index} href={source.url} target="_blank" rel="noreferrer"> [{source.id}]</a> : null;
                  })}</small></p>)}
                  <ul>{answer.web_research.sources?.map(source => <li key={source.id}><a href={source.url} target="_blank" rel="noreferrer">[{source.id}] {source.title}</a></li>)}</ul>
                  {answer.web_research.retrieved_at && <small>Retrieved {new Date(answer.web_research.retrieved_at).toLocaleString()}. Web findings do not change company scores.</small>}
                  {answer.web_research.search_suggestions && <iframe title="Google Search suggestions" sandbox="allow-popups allow-popups-to-escape-sandbox" referrerPolicy="no-referrer" srcDoc={answer.web_research.search_suggestions} style={{width:'100%',border:0}} />}
                </section>}
                {answer.evidence?.length > 0 && (
                  <>
                    <h4>Supporting evidence</h4>
                    <div className="evidence-links">
                      {answer.evidence.map(e => (
                        <button key={e.id} onClick={() => selectEvidence(e)}>
                          <span>
                            {e.data.place || e.data.company_name || e.data.listing?.company_name || e.id}
                          </span>
                          <ArrowUpRight size={15} />
                        </button>
                      ))}
                    </div>
                  </>
                )}
                {answer.limitations?.length > 0 && (
                  <details className="limitations">
                    <summary>
                      <Info size={14} />
                      Limits of this conclusion
                    </summary>
                    <ul>
                      {answer.limitations.map(n => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  </details>
                )}
                {answer.brief?.follow_up_questions?.length > 0 && (
                  <div className="follow-ups">
                    <h4>Continue investigating</h4>
                    {answer.brief.follow_up_questions.map(q => (
                      <button key={q} onClick={() => ask(q)}>
                        {q}
                        <ArrowRight size={13} />
                      </button>
                    ))}
                  </div>
                )}
                <button
                  className="text-link"
                  onClick={() => {
                    setQuestion('');
                    input.current?.focus();
                  }}
                >
                  Ask another question <ArrowRight size={14} />
                </button>
              </div>
            ) : (
              <div className="assistant-idle">
                <span className="idle-badge">LIVE QUERY</span>
                <h3>Ask the Dataset</h3>
                <p className="subtle">
                  Ask natural language questions to query 500 S&P companies and 12,936 Carbon Mapper plumes. Answers filter the view and cite auditable records.
                </p>
                <div className="prompt-label">SAMPLE INVESTIGATIONS</div>
                <div className="idle-prompts">
                  {prompts.map(({ label, question: q }) => (
                    <button key={label} onClick={() => ask(q)}>
                      <Sparkles size={13} />
                      <span>{q}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <form
            className="assistant-input"
            onSubmit={e => {
              e.preventDefault();
              ask(question);
            }}
          >
            <label className="sr-only" htmlFor="assistant-question">
              Ask the climate data
            </label>
            <textarea
              ref={input}
              id="assistant-question"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="e.g. Largest methane plumes in Texas, or utility target gaps..."
              maxLength={1000}
              disabled={busy}
              rows={1}
            />
            <button
              className="primary"
              aria-label={busy ? 'Querying' : 'Ask the data'}
              disabled={busy || !question.trim()}
            >
              {busy ? <LoaderCircle className="spin" size={17} /> : <ArrowUpRight size={17} />}
            </button>
          </form>
    </aside>
  );
}
