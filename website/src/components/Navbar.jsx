import React from 'react';
import { PanelsTopLeft, ScatterChart, Globe2, List, Sparkles, Scale, BookOpen, Database, SlidersHorizontal, Compass } from 'lucide-react';
import { fmt } from '../utils/formatters';
import { IndexSwitch } from './IndexSwitch';

export function Navbar({ index, setIndex, view, setView, companiesCount, plumesCount, assistantOpen, setAssistantOpen, onTabChange, onQuiz }) {
  function handleSelect(tab) {
    setView(tab);
    if (onTabChange) onTabChange(tab);
  }

  return (
    <header className="greenrank-nav">
      <div className="brand-group">
        <img className="brand-mark" src="greenrank-mark.png" alt="" width="30" height="30" />
        <div className="brand-text">
          <span className="brand-name">GreenRank</span>
          <span className="brand-tag">S&P 500 & Plume Evidence</span>
        </div>
      </div>

      <nav className="nav-tabs" role="tablist" aria-label="Main navigation">
        <button
          role="tab"
          aria-selected={view === 'paris'}
          className={view === 'paris' ? 'active' : ''}
          onClick={() => handleSelect('paris')}
        >
          <Scale size={16} />
          <span>Paris Index</span>
        </button>
        <button
          role="tab"
          aria-selected={view === 'explore'}
          className={view === 'explore' ? 'active' : ''}
          onClick={() => handleSelect('explore')}
        >
          <Compass size={16} />
          <span>Explore</span>
        </button>
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
        <button
          role="tab"
          aria-selected={view === 'compare'}
          className={view === 'compare' ? 'active' : ''}
          onClick={() => handleSelect('compare')}
        >
          <SlidersHorizontal size={16} />
          <span>Repricing</span>
        </button>
        <button
          role="tab"
          aria-selected={view === 'methods'}
          className={view === 'methods' ? 'active' : ''}
          onClick={() => handleSelect('methods')}
        >
          <BookOpen size={16} />
          <span>Methods</span>
        </button>
        <button
          role="tab"
          aria-selected={view === 'sources'}
          className={view === 'sources' ? 'active' : ''}
          onClick={() => handleSelect('sources')}
        >
          <Database size={16} />
          <span>Data Sources</span>
        </button>
      </nav>

      <div className="nav-actions">
        <IndexSwitch index={index} setIndex={setIndex} />
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
