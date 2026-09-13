import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, LoaderCircle } from 'lucide-react';

import { Navbar } from './components/Navbar';
import { ClimateQuiz } from './components/ClimateQuiz';
import { FilterBar } from './components/FilterBar';
import { EvidenceDrawer } from './components/EvidenceDrawer';
import { AssistantPanel } from './components/AssistantPanel';

import { TreemapView } from './views/TreemapView';
import { ParisView } from './views/ParisView';
import { PromisesChartView } from './views/PromisesChart';
import { PlumeAtlasView } from './views/PlumeAtlasView';
import { CompanyScreenerView } from './views/CompanyScreenerView';

import { initialFilters, companyFiltersDefault, prompts } from './constants';

export default function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [quizOpen, setQuizOpen] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [view, setView] = useState('treemap');
  const [index, setIndex] = useState('ours');
  const [filters, setFilters] = useState(initialFilters);
  const [cf, setCf] = useState(companyFiltersDefault);
  const [selected, setSelected] = useState(null);
  const [fitKey, setFitKey] = useState(0);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState(null);
  const [askError, setAskError] = useState('');
  const [activeResult, setActiveResult] = useState(null);
  const [visibleCount, setVisibleCount] = useState(30);
  const [history, setHistory] = useState([]);
  const [companyPage, setCompanyPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const input = useRef();
  const requestNumber = useRef(0);

  useEffect(() => {
    fetch('/data/snapshot.json')
      .then(r => {
        if (!r.ok) throw Error('Could not load the browse dataset.');
        return r.json();
      })
      .then(setSnapshot)
      .catch(e => setLoadError(e.message));
  }, []);

  const plumes = useMemo(() => {
    if (activeResult?.type === 'map') return activeResult.rows;
    return (snapshot?.plumes || []).filter(
      r =>
        r.gas === filters.gas &&
        (!filters.country || r.country === filters.country) &&
        (!filters.sector || r.ipcc_sector === filters.sector) &&
        (!filters.start || r.observed_at_utc.slice(0, 10) >= filters.start) &&
        (!filters.end || r.observed_at_utc.slice(0, 10) <= filters.end) &&
        (filters.minRate === '' || (r.emission_auto != null && r.emission_auto >= Number(filters.minRate)))
    );
  }, [snapshot, filters, activeResult]);

  const companies = useMemo(() => {
    if (activeResult?.type === 'company_table') return activeResult.rows;
    let rows = (snapshot?.companies || []).filter(
      r =>
        (!cf.sector || r.gics_sector === cf.sector) &&
        (!cf.search || `${r.ticker} ${r.company_name}`.toLowerCase().includes(cf.search.toLowerCase())) &&
        (cf.minGap === '' || (r.gap_pct_yr != null && r.gap_pct_yr >= Number(cf.minGap)))
    );
    const key = { gap: 'gap_pct_yr', emissions: 'scope1_t', risk: 'd_ev_pct_of_ev' }[cf.sort];
    return [...rows].sort((a, b) =>
      key ? (b[key] ?? -Infinity) - (a[key] ?? -Infinity) : a.company_name.localeCompare(b.company_name)
    );
  }, [snapshot, cf, activeResult]);

  const totalPages = Math.max(1, Math.ceil(companies.length / pageSize));
  const validPage = Math.min(companyPage, totalPages);
  const pagedCompanies = useMemo(() => {
    return companies.slice((validPage - 1) * pageSize, validPage * pageSize);
  }, [companies, validPage, pageSize]);

  const rankedPlumes = useMemo(
    () => [...plumes].sort((a, b) => (b.emission_auto ?? -Infinity) - (a.emission_auto ?? -Infinity)),
    [plumes]
  );
  const countries = useMemo(
    () => [...new Set((snapshot?.plumes || []).map(r => r.country).filter(Boolean))].sort(),
    [snapshot]
  );
  const sectors = useMemo(
    () => [...new Set((snapshot?.plumes || []).map(r => r.ipcc_sector).filter(Boolean))].sort(),
    [snapshot]
  );
  const companySectors = useMemo(
    () => [...new Set((snapshot?.companies || []).map(r => r.gics_sector))].sort(),
    [snapshot]
  );

  function updateFilter(k, v) {
    setActiveResult(null);
    setFilters(f => ({ ...f, [k]: v }));
    setVisibleCount(30);
  }

  function updateCompany(k, v) {
    setActiveResult(null);
    setCf(f => ({ ...f, [k]: v }));
    setVisibleCount(30);
    setCompanyPage(1);
  }

  function selectEvidence(e) {
    const d = e.data;
    setSelected(d.listing ? { ...d.listing, ...d.emissions, ...d.assessments } : d);
  }

  async function ask(text) {
    if (busy || !text.trim()) return;
    const current = ++requestNumber.current;
    setQuestion(text);
    setBusy(true);
    setAskError('');
    setAnswer(null);
    setAssistantOpen(true);
    try {
      const context = {
        view: view === 'map' ? 'map' : 'companies',
        filters: view === 'map' ? filters : cf,
        selected_tickers: selected?.ticker ? [selected.ticker] : [],
        selected_observation: selected?.plume_id || null
      };
      let response = await fetch('/api/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text, context, history: history.slice(-6) }),
        signal: AbortSignal.timeout(65000)
      });
      let body = await response.json();
      if (response.status === 400 && body.error?.includes('Provide only a question')) {
        response = await fetch('/api/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: text }),
          signal: AbortSignal.timeout(65000)
        });
        body = await response.json();
      }
      if (!response.ok) throw Error(body.error || 'The question could not be answered.');
      if (current !== requestNumber.current) return;
      setAnswer(body);
      setHistory(h => [...h, { role: 'user', text }, { role: 'assistant', text: body.answer }].slice(-6));
      const visualEvidence = body.evidence.filter(e => body.visualization?.record_ids?.includes(e.id));
      if (body.visualization?.type === 'map') {
        setView('map');
        setActiveResult({ type: 'map', rows: visualEvidence.map(e => e.data), filters: body.visualization.filters });
        setFitKey(k => k + 1);
      } else if (body.visualization?.type === 'company_table') {
        setView('table');
        setActiveResult({ type: 'company_table', rows: visualEvidence.map(e => e.data), filters: body.visualization.filters });
        setCompanyPage(1);
      } else if (body.visualization?.type === 'company_details') {
        setView('table');
        setActiveResult({
          type: 'company_table',
          rows: visualEvidence.map(e => ({ ...e.data.listing, ...e.data.emissions, ...e.data.assessments })),
          filters: { tickers: visualEvidence.map(e => e.id).join(', ') }
        });
        setCompanyPage(1);
      }
    } catch (e) {
      setAskError(
        e.name === 'TimeoutError'
          ? 'The answer took too long. Try again or explore the data using filters.'
          : e.message
      );
    } finally {
      if (current === requestNumber.current) setBusy(false);
    }
  }

  return (
    <div className="app">
      <Navbar
        index={index}
        setIndex={setIndex}
        view={view}
        onQuiz={() => setQuizOpen(true)}
        setView={setView}
        companiesCount={companies.length}
        plumesCount={plumes.length}
        assistantOpen={assistantOpen}
        setAssistantOpen={setAssistantOpen}
        onTabChange={tab => {
          setVisibleCount(30);
          if (tab === 'table') setCompanyPage(1);
        }}
      />

      <main
        className={`workspace ${selected ? 'has-evidence' : ''} ${
          assistantOpen ? 'has-assistant' : ''
        } ${selected || assistantOpen ? 'has-sidebar' : ''}`}
      >
        <section className="explorer" aria-label="Data explorer">
          {view !== 'paris' && <FilterBar
            view={view}
            filters={filters}
            updateFilter={updateFilter}
            cf={cf}
            updateCompany={updateCompany}
            countries={countries}
            sectors={sectors}
            companySectors={companySectors}
            activeResult={activeResult}
            onResetActiveResult={() => {
              setActiveResult(null);
              setVisibleCount(30);
            }}
          />}

          {loadError ? (
            <div className="empty-state" role="alert">
              <AlertCircle />
              <h3>Could not load the dataset</h3>
              <p>{loadError}</p>
              <button className="secondary" onClick={() => window.location.reload()}>
                Try again
              </button>
            </div>
          ) : !snapshot ? (
            <div className="empty-state">
              <LoaderCircle className="spin" />
              <h3>Loading GreenRank database</h3>
              <p>Preparing 500 company records and 12,936 satellite plume observations...</p>
            </div>
          ) : view === 'map' ? (
            <PlumeAtlasView
              plumes={plumes}
              rankedPlumes={rankedPlumes}
              selected={selected}
              onSelect={setSelected}
              fitKey={fitKey}
              visibleCount={visibleCount}
              setVisibleCount={setVisibleCount}
            />
          ) : view === 'paris' ? (
            <ParisView />
          ) : view === 'treemap' ? (
            <TreemapView
              companies={companies}
              snapshot={snapshot}
              index={index}
              onSelect={setSelected}
              onSector={sector => updateCompany('sector', sector)}
            />
          ) : view === 'chart' ? (
            <PromisesChartView companies={companies} onSelect={setSelected} />
          ) : (
            <CompanyScreenerView
              companies={companies}
              pagedCompanies={pagedCompanies}
              validPage={validPage}
              totalPages={totalPages}
              pageSize={pageSize}
              onPageChange={p => setCompanyPage(p)}
              onPageSizeChange={s => {
                setPageSize(s);
                setCompanyPage(1);
              }}
              onSelect={setSelected}
            />
          )}

          <div className="data-footer">
            <span>
              <strong>GreenRank</strong> · Auditable Climate Intelligence
            </span>
            <span>Sources: EPA GHGRP (2023), Carbon Mapper (2025), SEC 10-K Filings</span>
            <span>Snapshot: September 2026</span>
          </div>
        </section>

        {selected && (
          <EvidenceDrawer
            key={selected.plume_id || selected.ticker}
            item={selected}
            onClose={() => setSelected(null)}
            onAsk={ask}
          />
        )}

        {assistantOpen && (
          <AssistantPanel
            assistantOpen={assistantOpen}
            setAssistantOpen={setAssistantOpen}
            busy={busy}
            askError={askError}
            answer={answer}
            question={question}
            setQuestion={setQuestion}
            ask={ask}
            selectEvidence={selectEvidence}
            input={input}
            prompts={prompts}
          />
        )}
      </main>

      {quizOpen && <ClimateQuiz companies={snapshot?.companies || []} onClose={() => setQuizOpen(false)} onExplore={(nextView, company) => {setQuizOpen(false);setView(nextView);setActiveResult(null);setCf(companyFiltersDefault);setSelected(company || null);}} onAsk={text => {setQuizOpen(false);ask(text);}} />}
    </div>
  );
}
