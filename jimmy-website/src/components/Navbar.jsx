import React from 'react';
import { PanelsTopLeft, ScatterChart, Globe2, List, Sparkles } from 'lucide-react';
import { fmt } from '../utils/formatters';

export function Navbar({ view, setView, companiesCount, plumesCount, assistantOpen, setAssistantOpen, onTabChange, onQuiz }) {
  function handleSelect(tab) {
    setView(tab);
    if (onTabChange) onTabChange(tab);
  }

  return (
    <header className="greenrank-nav">
      <div className="brand-group">
        <span className="brand-mark">GR</span>
        <div className="brand-text">
          <span className="brand-name">GreenRank</span>
          <span className="brand-tag">S&P 500 & Plume Evidence</span>
        </div>
      </div>

      <nav className="nav-tabs" role="tablist" aria-label="Main navigation">
        <button
          role="tab"
          aria-selected={view === 'treemap'}
          className={view === 'treemap' ? 'active' : ''}
          onClick={() => handleSelect('treemap')}
        >
          <PanelsTopLeft size={16} />
          <span>Concentration Treemap</span>
        </button>
        <button
          role="tab"
          aria-selected={view === 'chart'}
          className={view === 'chart' ? 'active' : ''}
          onClick={() => handleSelect('chart')}
        >
          <ScatterChart size={16} />
          <span>Promises vs Reality</span>
        </button>
        <button
          role="tab"
          aria-selected={view === 'map'}
          className={view === 'map' ? 'active' : ''}
          onClick={() => handleSelect('map')}
        >
          <Globe2 size={16} />
          <span>Plume Atlas</span>
        </button>
        <button
          role="tab"
          aria-selected={view === 'table'}
          className={view === 'table' ? 'active' : ''}
          onClick={() => handleSelect('table')}
        >
          <List size={16} />
          <span>Company Screener</span>
        </button>
      </nav>

      <div className="nav-actions">
        <button className="assistant-btn" onClick={onQuiz}>Test your climate intuition</button>
        <div className="data-counts">
          <span><strong>{fmt(companiesCount)}</strong> companies</span>
          <span className="sep">·</span>
          <span><strong>{fmt(plumesCount)}</strong> plumes</span>
        </div>
        <button
          className={`assistant-btn ${assistantOpen ? 'active' : ''}`}
          onClick={() => setAssistantOpen(v => !v)}
          title="Query dataset with AI"
        >
          <Sparkles size={15} />
          <span>Ask Data</span>
        </button>
      </div>
    </header>
  );
}
