import React, { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { buildQuizRounds } from '../constants/quizQuestions';

export function ClimateQuiz({ companies, onClose, onExplore, onAsk }) {
  const dialog = useRef(null);
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState([]);
  useEffect(() => { const previous = document.activeElement; dialog.current.showModal(); return () => previous?.focus?.(); }, []);
  const [rounds, setRounds] = useState(buildQuizRounds);
  const round = rounds[step], done = step === rounds.length, choice = answers[step];
  const score = answers.reduce((sum, a, i) => sum + (a === rounds[i].correct ? 1 : 0), 0);
  return <dialog ref={dialog} className="climate-quiz" aria-labelledby="quiz-title" onCancel={onClose}>
    <div className="quiz-heading"><span className="eyebrow">TEST YOUR CLIMATE INTUITION</span><button className="icon-button" aria-label="Close quiz" onClick={onClose}><X size={20}/></button></div>
    {done ? <><h2 id="quiz-title">Evidence before conclusions.</h2><p>You answered {score} of {rounds.length} correctly. The most valuable habit: knowing when the evidence is insufficient.</p><ul><li>Recorded emissions need dates and boundaries.</li><li>ESG risk covers more than environmental impact.</li><li>A mismatch is a reason to investigate.</li></ul><button className="primary" onClick={() => {setStep(0);setAnswers([]);setRounds(buildQuizRounds());}}>Try again</button> <button className="secondary" onClick={() => onExplore('table')}>Explore companies</button></> : <>
      <p className="quiz-progress">Round {step+1} of {rounds.length} · Company comparisons</p><h2 id="quiz-title">{round.question}</h2>
      <div className="quiz-options">{round.options.map((option, i) => <button key={option} disabled={choice !== undefined} className={choice !== undefined && i === round.correct ? 'correct' : choice === i ? 'incorrect' : ''} onClick={() => setAnswers(a => [...a, i])}>{round.pair && <img src={`https://images.financialmodelingprep.com/symbol/${round.pair[i].ticker.replaceAll('.', '-')}.png`} alt="" onError={e => {e.currentTarget.style.display='none';}}/>}{option}</button>)}</div>
      {choice !== undefined && <div className="quiz-reveal" role="status"><strong>{choice === round.correct ? 'Exactly.' : 'Here is what the evidence tells us.'}</strong><ul>{round.values.map(value => <li key={value}>{value}</li>)}</ul><p>{round.explanation}</p><p><small>Source: {round.source.url ? <a href={round.source.url} target="_blank" rel="noreferrer">{round.source.name}</a> : round.source.name}. Historical web dataset; these are not live figures. A single metric does not establish overall sustainability.</small></p><div className="quiz-links"><button className="text-link" onClick={() => onExplore('table', companies.find(c => c.ticker === round.pair[round.correct].ticker))}>Explore the evidence →</button><button className="text-link" onClick={() => onAsk(`Explain this climate evidence lesson: ${round.question} The reviewed answer is: ${round.values.join(' ')} Source: ${round.source.name}. Explain the comparison and limitations. Treat these as historical snapshot values, and do not infer causes from the numbers alone.`)}>Ask AI why →</button></div><button className="primary" onClick={() => setStep(s => s+1)}>{step === rounds.length - 1 ? 'See takeaways' : 'Next round'}</button></div>}
    </>}
  </dialog>;
}
