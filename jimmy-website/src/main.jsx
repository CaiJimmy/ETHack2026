import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import L from 'leaflet';
import Supercluster from 'supercluster';
import { ArrowUpRight, ArrowRight, ArrowDown, Search, Globe2, Building2, Sparkles, X, Plus, Minus, Focus, Layers3, ChevronRight, ExternalLink, Info, SlidersHorizontal, LoaderCircle, RotateCcw, List, ScatterChart, Crosshair, PanelsTopLeft, AlertCircle } from 'lucide-react';
import { hierarchy, treemap, treemapSquarify } from 'd3-hierarchy';
import 'leaflet/dist/leaflet.css';
import './style.css';

const fmt = (n, digits=0) => n == null ? 'Not available' : Number(n).toLocaleString('en-US',{maximumFractionDigits:digits});
const compact = n => n == null ? '—' : new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(n);
const pct = n => n == null ? '—' : `${n > 0 ? '+' : ''}${fmt(n,1)}%`;
const logoTicker = ticker => ticker?.replaceAll('.', '-');
function CompanyLogo({company,size='medium',onDark=false}) {
  const [failed,setFailed]=useState(false);
  const ticker=company?.ticker||'';
  return <span className={`company-logo ${size} ${onDark?'on-dark':''}`} style={{'--logo-sector':sectorColors[company?.gics_sector]||'#64748b'}} aria-hidden="true">
    {!failed&&ticker?<img src={`https://images.financialmodelingprep.com/symbol/${encodeURIComponent(logoTicker(ticker))}.png`} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={()=>setFailed(true)}/>:null}
    <span className={failed||!ticker?'visible':''}>{ticker.slice(0,4)}</span>
  </span>;
}
const prompts = [
  {label:'Find methane hotspots',question:'Show the five largest methane plume observations in Texas during 2025.',icon:Globe2},
  {label:'Investigate target gaps',question:'Which five utilities have the largest positive target gaps?',icon:Building2},
  {label:'Prepare company engagement',question:'Compare XOM and CVX and suggest climate engagement questions.',icon:ArrowUpRight},
];
const initialFilters = {gas:'CH4',country:'',sector:'',start:'2025-01-01',end:'2025-12-31',minRate:''};
const companyFiltersDefault = {sector:'',search:'',sort:'gap',minGap:''};

function MapView({records, onSelect, selection, fitKey}) {
  const el=useRef(null), map=useRef(null), layer=useRef(null), index=useRef(null), select=useRef(onSelect);
  const [tileError,setTileError]=useState(false);
  select.current=onSelect;
  const draw=useRef(()=>{});
  useEffect(()=>{
    map.current=L.map(el.current,{zoomControl:false,preferCanvas:true,minZoom:1,maxZoom:16,worldCopyJump:true}).setView([24,8],el.current.clientWidth<600?1:2);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',{attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',subdomains:'abcd',maxZoom:20}).on('tileerror',()=>setTileError(true)).addTo(map.current);
    layer.current=L.layerGroup().addTo(map.current);
    map.current.on('moveend zoomend',()=>draw.current());
    const observer=new ResizeObserver(()=>map.current?.invalidateSize()); observer.observe(el.current);
    return ()=>{observer.disconnect();map.current.remove();};
  },[]);
  useEffect(()=>{
    index.current=new Supercluster({radius:45,maxZoom:10}).load(records.map(r=>({type:'Feature',geometry:{type:'Point',coordinates:[r.plume_longitude,r.plume_latitude]},properties:{record:r}})));
    draw.current=()=>{
      if(!map.current||!layer.current)return;
      layer.current.clearLayers();
      // Global query also handles repeated map worlds; Leaflet clips offscreen markers.
      const features=index.current.getClusters([-180,-85,180,85],Math.min(16,Math.floor(map.current.getZoom())));
      for(const feature of features){
        const [lon,lat]=feature.geometry.coordinates,p=feature.properties;
        if(p.cluster){
          const size=p.point_count>100?44:36;
          L.marker([lat,lon],{icon:L.divIcon({className:'cluster-icon',html:`<span>${compact(p.point_count)}</span>`,iconSize:[size,size]}),keyboard:true,title:`${p.point_count} observations. Zoom in.`}).on('click',()=>map.current.flyTo([lat,lon],Math.min(index.current.getClusterExpansionZoom(p.cluster_id),16),{duration:.65})).addTo(layer.current);
        }else{
          const r=p.record,rate=r.emission_auto;
          const radius=rate==null?4:Math.min(17,3+Math.sqrt(rate)/18);
          const marker=L.circleMarker([lat,lon],{radius,color:rate==null?'#94a3b8':r.gas==='CH4'?'#d2f783':'#79caff',fillColor:r.gas==='CH4'?'#c5f36b':'#79caff',fillOpacity:rate==null?0:.65,weight:1});
          const tooltip=document.createElement('div');tooltip.textContent=`${r.place||r.region||r.country||'Observation'} · ${rate==null?'Unquantified':fmt(rate)+' kg '+r.gas+'/h'}`;
          marker.bindTooltip(tooltip).on('click',()=>select.current(r)).addTo(layer.current);
        }
      }
    };draw.current();
  },[records]);
  useEffect(()=>{
    if(!map.current)return;
    if(selection?.plume_id) map.current.flyTo([selection.plume_latitude,selection.plume_longitude],8,{duration:1});
  },[selection]);
  const fit=()=>{if(records.length){const bounds=L.latLngBounds(records.map(r=>[r.plume_latitude,r.plume_longitude]));map.current.flyToBounds(bounds,{padding:[50,50],maxZoom:8,duration:.85});}};
  useEffect(()=>{if(fitKey)fit();},[fitKey]);
  return <div className="map-shell"><div ref={el} className="map" aria-label="Global map of observed greenhouse gas plumes"/>
    <div className="map-controls"><button title="Zoom in" aria-label="Zoom in" onClick={()=>map.current.zoomIn()}><Plus size={18}/></button><button title="Zoom out" aria-label="Zoom out" onClick={()=>map.current.zoomOut()}><Minus size={18}/></button><button title="Fit results" aria-label="Fit results" onClick={fit}><Focus size={18}/></button></div>
    <div className="map-legend"><div><span className="legend-cluster">12</span> Cluster count</div><div><i className="legend-dot"/> Observed rate <span className="muted">kg/h</span></div><div><i className="legend-dot empty"/> Unquantified</div></div>
    <div className="map-note">{tileError?'Some map tiles are unavailable. Observation results remain accessible below.':'No observations does not mean no emissions.'}</div>
  </div>;
}

function Field({label,children}){return <label className="field"><span>{label}</span>{children}</label>;}
function Metric({label,value,unit}){return <div className="metric"><span>{label}</span><strong>{value}<small>{unit}</small></strong></div>;}
function EvidenceDrawer({item,onClose,onAsk}){
  const dialog=useRef(),[details,setDetails]=useState(null),[error,setError]=useState('');
  const plume=Boolean(item?.plume_id);
  useEffect(()=>{dialog.current.showModal();const before=document.activeElement;return ()=>before?.focus?.();},[]);
  useEffect(()=>{
    if(plume)return;
    const controller=new AbortController();setDetails(null);setError('');
    fetch(`/api/companies/${encodeURIComponent(item.ticker)}`,{signal:controller.signal}).then(async r=>{const b=await r.json();if(!r.ok)throw Error(b.error);return b;}).then(b=>setDetails(b.data)).catch(e=>{if(e.name!=='AbortError')setError(e.message);});
    return ()=>controller.abort();
  },[item,plume]);
  const e=details?.emissions||item,a=details?.assessments||item;
  return <dialog className="evidence-dialog" ref={dialog} onCancel={onClose} onClick={event=>{if(event.target===dialog.current)onClose();}} aria-labelledby="evidence-title"><div className="drawer-content">
    <div className="drawer-top"><span className="eyebrow">{plume?'OBSERVATION RECORD':'COMPANY EVIDENCE'}</span><button className="icon-button" onClick={onClose} aria-label="Close evidence"><X/></button></div>
    <div className={`record-icon ${plume?'':'company-record-icon'}`}>{plume?<Crosshair/>:<CompanyLogo company={{...item,gics_sector:item.gics_sector||details?.listing.gics_sector}} size="large"/>}</div><h2 id="evidence-title">{plume?(item.place||item.region||'Plume observation'):item.company_name||item.ticker}</h2><p className="subtle">{plume?[item.region,item.country].filter(Boolean).join(', '):`${item.ticker} · ${item.gics_sector||details?.listing.gics_sector||''}`}</p>
    {plume?<>
      <div className="drawer-metrics"><Metric label="Estimated emission rate" value={fmt(item.emission_auto,1)} unit={item.emission_auto!=null?`kg ${item.gas}/h`:''}/><Metric label="Rate uncertainty" value={item.emission_uncertainty_auto==null?'Not available':`± ${fmt(item.emission_uncertainty_auto,1)}`} unit="kg/h"/></div>
      <h3>Observation details</h3><dl><dt>Observed</dt><dd>{new Date(item.observed_at_utc).toLocaleString('en-GB',{timeZone:'UTC'})} UTC</dd><dt>Sector</dt><dd>{item.ipcc_sector||'Not available'}</dd><dt>Platform</dt><dd>{item.platform||'Not available'}</dd><dt>Provider</dt><dd>{item.provider||'Not available'}</dd><dt>Coordinates</dt><dd>{fmt(item.plume_latitude,4)}, {fmt(item.plume_longitude,4)}</dd><dt>Company ownership</dt><dd>Not verified</dd></dl>
      <div className="notice"><Info size={17}/><p>This is an observation of a plume, not an annual total or a unique facility. Repeated observations may refer to the same source.</p></div>
      <h3>Source record</h3><code className="record-id">{item.plume_id}</code><a className="text-link" href="https://data.carbonmapper.org/" target="_blank" rel="noreferrer">Carbon Mapper data portal <ExternalLink size={14}/></a>
    </>:<>
      {error&&<div role="alert" className="notice error">{error} · Showing available screening data.</div>}
      {!details&&!error&&<p className="subtle"><LoaderCircle className="spin" size={16}/> Loading detailed evidence…</p>}
      <div className="drawer-metrics"><Metric label="Direct emissions · Scope 1" value={compact(e.scope1_t)} unit="tCO₂e"/><Metric label="Reporting year" value={e.scope1_year||'Unknown'}/></div>
      <h3>Emissions coverage</h3><dl><dt>Scope 2 · purchased energy</dt><dd>{e.scope2_market_t==null?'Not available':`${fmt(e.scope2_market_t)} tCO₂e · ${e.scope2_year||'year unknown'}`}</dd><dt>Scope 2 basis</dt><dd>{e.scope2_basis||'Not available'}</dd><dt>Scope 3 · value chain</dt><dd>{e.scope3_total_t==null?'Not available':`${fmt(e.scope3_total_t)} tCO₂e · ${e.scope3_year||'year unknown'}`}</dd></dl>
      <h3>Promises & progress</h3><div className="rate-comparison"><div><span>Promised annual change</span><strong>{pct(e.promised_pct_yr)}</strong></div><div><span>Measured annual change</span><strong>{pct(e.delivered_pct_yr)}</strong></div><div className="gap-row"><span>Annual shortfall</span><strong>{e.gap_pct_yr==null?'Unknown':`${fmt(e.gap_pct_yr,1)} pp`}</strong></div></div>
      <p className="micro">Negative change means falling emissions. Measured window: {e.delivered_year_start||'—'}–{e.delivered_year_end||'—'}. Corporate targets and US facility measurements may cover different boundaries.</p>
      <h3>Stored carbon-cost scenario</h3><Metric label="Modeled enterprise-value impact" value={a.d_ev_pct_of_ev==null?'Not available':`${fmt(a.d_ev_pct_of_ev,1)}%`}/>
      <dl><dt>Carbon price</dt><dd>{a.price_sector_usd_per_t==null?'Loading / unavailable':`$${fmt(a.price_sector_usd_per_t,2)}/t`}</dd><dt>Customer pass-through</dt><dd>{a.passthrough_pct==null?'Loading / unavailable':`${a.passthrough_pct}% (assumed)`}</dd><dt>Rank interval (5th–95th)</dt><dd>{fmt(a.rank_p05)}–{fmt(a.rank_p95)}</dd><dt>Coverage tier</dt><dd>{a.coverage_tier||'Unknown'}</dd><dt>Scope 1 basis</dt><dd>{e.scope1_basis?.replaceAll('_',' ')||'Unknown'}</dd></dl>
      <div className="notice"><Info size={17}/><p>Scenario results depend on assumptions. They are not forecasts of investment losses. Missing data is not zero emissions.</p></div>
      <button className="primary full" onClick={()=>{onClose();onAsk(`Review ${item.ticker} and propose three climate engagement questions based on its available evidence.`);}}><Sparkles size={16}/> Prepare engagement questions</button>
    </>}
  </div></dialog>;
}

function CompanyChart({rows,onSelect}){
  const plotted=rows.filter(r=>r.promised_pct_yr!=null&&r.delivered_pct_yr!=null&&r.gap_pct_yr!=null);
  const points=plotted.map(r=>({...r,promisedCut:-r.promised_pct_yr,measuredCut:-r.delivered_pct_yr}));
  const xMin=0,xMax=Math.max(30,...points.map(r=>r.promisedCut))+2,yMin=Math.min(-12,...points.map(r=>r.measuredCut))-2,yMax=Math.max(30,...points.map(r=>r.measuredCut))+2;
  const symlog=v=>Math.sign(v)*Math.log1p(Math.abs(v)/2),xTransform=v=>Math.log1p(Math.max(0,v)/2);
  const x=v=>72+xTransform(v)/xTransform(xMax)*650,y=v=>338-(symlog(v)-symlog(yMin))/(symlog(yMax)-symlog(yMin))*286;
  const ticks=[-40,-20,-10,-5,0,5,10,20,40].filter(v=>v>=yMin&&v<=yMax);
  const xTicks=[0,2,5,10,20,30].filter(v=>v<=xMax);
  const equalityMax=Math.min(xMax,yMax),equalityPath=Array.from({length:41},(_,i)=>{const v=equalityMax*i/40;return`${i?'L':'M'}${x(v)},${y(v)}`;}).join(' ');
  const emissionLogs=points.map(r=>Math.log10(Math.max(1,r.scope1_t||1))),logMin=Math.min(...emissionLogs),logMax=Math.max(...emissionLogs);
  const displayPoints=points.map((r,i)=>{const radius=5.5+(emissionLogs[i]-logMin)/Math.max(1,logMax-logMin)*3;return{...r,ax:x(r.promisedCut),ay:y(r.measuredCut),cx:x(r.promisedCut)+(i%7-3)*.25,cy:y(r.measuredCut)+(i%5-2)*.25,radius};});
  for(let iteration=0;iteration<180;iteration++){
    for(let i=0;i<displayPoints.length;i++)for(let j=i+1;j<displayPoints.length;j++){
      const a=displayPoints[i],b=displayPoints[j],dx=b.cx-a.cx,dy=b.cy-a.cy,d=Math.hypot(dx,dy)||.01,minD=a.radius+b.radius+2;
      if(d<minD){const push=(minD-d)*.28,nx=dx/d,ny=dy/d;a.cx-=nx*push;a.cy-=ny*push;b.cx+=nx*push;b.cy+=ny*push;}
    }
    for(const p of displayPoints){p.cx+=(p.ax-p.cx)*.006;p.cy+=(p.ay-p.cy)*.006;p.cx=Math.max(74+p.radius,Math.min(720-p.radius,p.cx));p.cy=Math.max(44+p.radius,Math.min(336-p.radius,p.cy));}
  }
  return <div className="scatter-wrap"><div className="section-heading"><div><h3>Are companies cutting emissions as fast as promised?</h3><p className="subtle">Both axes show reduction rates. Higher means a faster annual emissions cut.</p></div><span>{plotted.length} comparable records</span></div>
    <div className="progress-legend"><span className="ahead"><i/>Ahead of promise</span><span className="behind"><i/>Behind promise</span><span><b>0%</b> = no change · below 0% = emissions rising</span></div>
    <svg viewBox="0 0 790 410" role="img" aria-label="Company promised emissions reduction versus measured emissions reduction">
      <rect x="72" y="42" width="650" height={y(0)-42} fill="#eef6f0"/><rect x="72" y={y(0)} width="650" height={338-y(0)} fill="#fcf2ec"/>
      {xTicks.map(v=><g key={`x${v}`}><line x1={x(v)} y1="42" x2={x(v)} y2="338" stroke="#dfe7e3"/><text x={x(v)} y="361" textAnchor="middle">{v}%</text></g>)}
      {ticks.map(v=><g key={`y${v}`}><line x1="72" y1={y(v)} x2="722" y2={y(v)} stroke={v===0?'#9aaaa5':'#dfe7e3'} strokeWidth={v===0?1.5:1}/><text x="58" y={y(v)+4} textAnchor="end">{v}%</text></g>)}
      <path d={equalityPath} fill="none" stroke="#60756d" strokeWidth="1.5" strokeDasharray="6 5"/>
      <text className="zone-label ahead" x="105" y="60">FASTER REDUCTIONS</text><text className="zone-label behind" x="530" y="324">EMISSIONS INCREASING</text>
      {displayPoints.map(r=>{const clip=`logo-${r.ticker.replace(/[^a-zA-Z0-9]/g,'')}`,shift=Math.hypot(r.cx-r.ax,r.cy-r.ay),inner=r.radius*2-3;return <g className="company-point" key={r.ticker} tabIndex="0" role="button" aria-label={`Inspect ${r.company_name}. Promised reduction ${fmt(r.promisedCut,1)} percent per year; measured reduction ${fmt(r.measuredCut,1)} percent per year.`} onClick={()=>onSelect(r)} onKeyDown={ev=>{if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();onSelect(r);}}}>
        {shift>3&&<line className="point-leader" x1={r.ax} y1={r.ay} x2={r.cx} y2={r.cy}/>}<circle className="true-position" cx={r.ax} cy={r.ay} r="1.7"/><defs><clipPath id={clip}><circle cx={r.cx} cy={r.cy} r={r.radius-1}/></clipPath></defs><circle className={r.gap_pct_yr>0?'point-ring behind':'point-ring ahead'} cx={r.cx} cy={r.cy} r={r.radius+1.5}/><circle cx={r.cx} cy={r.cy} r={r.radius-1} fill="#fff"/><text className="point-fallback" x={r.cx} y={r.cy+2.5} textAnchor="middle">{r.ticker.slice(0,3)}</text><image href={`https://images.financialmodelingprep.com/symbol/${encodeURIComponent(logoTicker(r.ticker))}.png`} x={r.cx-(r.radius-1)} y={r.cy-(r.radius-1)} width={inner} height={inner} preserveAspectRatio="xMidYMid meet" clipPath={`url(#${clip})`} onError={ev=>ev.currentTarget.style.display='none'}/><title>{r.company_name}: promised cut {fmt(r.promisedCut,1)}%/yr; measured cut {fmt(r.measuredCut,1)}%/yr; {r.gap_pct_yr>0?`${fmt(r.gap_pct_yr,1)} pp/yr behind`:`${fmt(Math.abs(r.gap_pct_yr),1)} pp/yr ahead`}. Logo size reflects available Scope 1 emissions.</title>
      </g>;})}
      <text x="397" y="398" textAnchor="middle">Promised emissions reduction (% per year)</text><text transform="translate(18 190) rotate(-90)" textAnchor="middle">Measured emissions reduction (% per year)</text>
    </svg><p className="scale-note"><Info size={13}/><span><strong>Expanded scale:</strong> spacing is nonlinear to separate the crowded low-rate range. Axis labels remain actual annual percentages.</span></p><p className="micro">Logo size reflects available Scope 1 emissions. Faint lines connect displaced logos to their exact values. The curved dashed line is the promised pace: above it is ahead; below it is behind.</p></div>;
}

const sectorColors={'Information Technology':'#487e85','Financials':'#718359','Communication Services':'#666a97','Consumer Discretionary':'#a67b53','Health Care':'#648eaa','Industrials':'#8b9672','Consumer Staples':'#b68c6a','Energy':'#c57b47','Utilities':'#719d78','Materials':'#a0a563','Real Estate':'#9382a0'};
function CompanyTreemap({rows,onSelect,onSector}){
  const [metric,setMetric]=useState('market_cap_musd'),[width,setWidth]=useState(800),[hover,setHover]=useState(null);
  const container=useRef(null);
  useEffect(()=>{const o=new ResizeObserver(entries=>setWidth(entries[0].contentRect.width));o.observe(container.current);return()=>o.disconnect();},[]);
  const height=width<500?570:510;
  const known=rows.filter(r=>r[metric]!=null&&r[metric]>0),missing=rows.filter(r=>r[metric]==null),zero=rows.filter(r=>r[metric]===0);
  const total=known.reduce((s,r)=>s+r[metric],0);
  const root=useMemo(()=>{
    const groups=new Map();
    for(const r of rows){if(r[metric]==null||r[metric]<=0)continue;const sector=r.gics_sector||'Other';if(!groups.has(sector))groups.set(sector,[]);groups.get(sector).push(r);}
    const tree=hierarchy({children:[...groups].map(([name,children])=>({name,children}))}).sum(d=>d[metric]||0).sort((a,b)=>b.value-a.value);
    return treemap().tile(treemapSquarify).size([Math.max(1,width),height]).paddingOuter(3).paddingInner(2).paddingTop(d=>d.depth===1?23:2).round(true)(tree);
  },[rows,metric,width,height]);
  const value=r=>metric==='market_cap_musd'?`$${compact(r[metric]*1e6)}`:`${compact(r[metric])} tCO₂e`;
  return <div className="treemap-section"><div className="treemap-toolbar"><div className="metric-toggle" role="group" aria-label="Treemap tile size"><button className={metric==='market_cap_musd'?'active':''} onClick={()=>{setMetric('market_cap_musd');setHover(null);}}>Market value</button><button className={metric==='scope1_t'?'active':''} onClick={()=>{setMetric('scope1_t');setHover(null);}}>Direct emissions</button></div><span>{known.length} companies shown</span></div>
    <p className="treemap-explanation">{metric==='market_cap_musd'?'Tile area represents company market capitalization.':'Tile area represents available Scope 1 emissions, combining different years and reporting boundaries.'} Color identifies sector.</p>
    <div ref={container} className="treemap" style={{height}} aria-label={`Company treemap sized by ${metric==='market_cap_musd'?'market value':'direct emissions'}`}>
      {!known.length?<div className="empty-state"><Info/><h3>No values to size these tiles</h3><p>Try another metric or clear your filters.</p></div>:<>
      {root.children?.map(g=><div className="sector-frame" key={g.data.name} style={{left:g.x0,top:g.y0,width:Math.max(0,g.x1-g.x0),height:Math.max(0,g.y1-g.y0),background:sectorColors[g.data.name]||'#64748b'}}>{g.x1-g.x0>85&&g.y1-g.y0>35&&<span>{g.data.name.toUpperCase()}</span>}</div>)}
      {root.leaves().map(leaf=>{const r=leaf.data,w=leaf.x1-leaf.x0,h=leaf.y1-leaf.y0;if(w<1||h<1)return null;return <button className="company-tile" key={r.ticker} style={{left:leaf.x0,top:leaf.y0,width:w,height:h,background:sectorColors[r.gics_sector]||'#64748b'}} onMouseEnter={()=>setHover(r)} onMouseLeave={()=>setHover(null)} onFocus={()=>setHover(r)} onBlur={()=>setHover(null)} onClick={()=>onSelect(r)} title={`${r.company_name} (${r.ticker}) · ${value(r)} · ${fmt(r[metric]/total*100,2)}% of shown total`} aria-label={`Inspect ${r.company_name}, ${value(r)}`}>
        {w>44&&h>38&&<CompanyLogo company={r} size={w>105&&h>85?'tile-large':'tile-small'} onDark/>}{w>34&&h>23&&<strong style={{fontSize:Math.min(26,Math.max(12,Math.min(w/4,h/3)))}}>{r.ticker}</strong>}{w>75&&h>62&&<small>{value(r)}</small>}{w>160&&h>120&&<span>{r.company_name}</span>}
      </button>;})}</>}
    </div>
      <div className="treemap-hover" aria-live="polite">{hover?<><CompanyLogo company={hover} size="small"/><strong>{hover.company_name}</strong><span>{value(hover)} · {fmt(hover[metric]/total*100,2)}% of shown total{metric==='scope1_t'?` · ${hover.scope1_year||'Unknown year'}`:''}</span><span>Click to inspect <ArrowUpRight size={13}/></span></>:<><Crosshair size={16}/><span>Hover to compare. Select any tile to inspect its evidence.</span></>}</div>
    <div className="sector-legend">{root.children?.map(g=><button key={g.data.name} onClick={()=>onSector(g.data.name)} title={`Filter to ${g.data.name}`}><i style={{background:sectorColors[g.data.name]}}/>{g.data.name}<span>{fmt(g.value/total*100,1)}%</span></button>)}</div>
    <div className="notice"><Info size={16}/><p>{missing.length} {metric==='scope1_t'?'companies have no available Scope 1 value':'companies have no market-cap value'}{zero.length?`; ${zero.length} have a recorded zero`:''}. These companies have no area in the treemap. {metric==='scope1_t'?'Missing emissions are unknown, not zero.':'Market capitalization reflects the stored company snapshot.'} Shares refer to the current selection, not a portfolio allocation.</p></div>
  </div>;
}

function App(){
  const [snapshot,setSnapshot]=useState(null),[loadError,setLoadError]=useState('');
  const [view,setView]=useState('treemap'),[filters,setFilters]=useState(initialFilters),[cf,setCf]=useState(companyFiltersDefault);
  const [selected,setSelected]=useState(null),[fitKey,setFitKey]=useState(0),[assistantOpen,setAssistantOpen]=useState(false);
  const [question,setQuestion]=useState(''),[busy,setBusy]=useState(false),[answer,setAnswer]=useState(null),[askError,setAskError]=useState(''),[activeResult,setActiveResult]=useState(null),[visibleCount,setVisibleCount]=useState(30),[history,setHistory]=useState([]);
  const input=useRef(), requestNumber=useRef(0);

  useEffect(()=>{fetch('/data/snapshot.json').then(r=>{if(!r.ok)throw Error('Could not load the browse dataset.');return r.json();}).then(setSnapshot).catch(e=>setLoadError(e.message));},[]);

  const plumes=useMemo(()=>{
    if(activeResult?.type==='map')return activeResult.rows;
    return(snapshot?.plumes||[]).filter(r=>r.gas===filters.gas&&(!filters.country||r.country===filters.country)&&(!filters.sector||r.ipcc_sector===filters.sector)&&(!filters.start||r.observed_at_utc.slice(0,10)>=filters.start)&&(!filters.end||r.observed_at_utc.slice(0,10)<=filters.end)&&(filters.minRate===''||(r.emission_auto!=null&&r.emission_auto>=Number(filters.minRate))));
  },[snapshot,filters,activeResult]);

  const companies=useMemo(()=>{
    if(activeResult?.type==='company_table')return activeResult.rows;
    let rows=(snapshot?.companies||[]).filter(r=>(!cf.sector||r.gics_sector===cf.sector)&&(!cf.search||`${r.ticker} ${r.company_name}`.toLowerCase().includes(cf.search.toLowerCase()))&&(cf.minGap===''||(r.gap_pct_yr!=null&&r.gap_pct_yr>=Number(cf.minGap))));
    const key={gap:'gap_pct_yr',emissions:'scope1_t',risk:'d_ev_pct_of_ev'}[cf.sort];
    return [...rows].sort((a,b)=>key?(b[key]??-Infinity)-(a[key]??-Infinity):a.company_name.localeCompare(b.company_name));
  },[snapshot,cf,activeResult]);

  const rankedPlumes=useMemo(()=>[...plumes].sort((a,b)=>(b.emission_auto??-Infinity)-(a.emission_auto??-Infinity)),[plumes]);
  const countries=useMemo(()=>[...new Set((snapshot?.plumes||[]).map(r=>r.country).filter(Boolean))].sort(),[snapshot]);
  const sectors=useMemo(()=>[...new Set((snapshot?.plumes||[]).map(r=>r.ipcc_sector).filter(Boolean))].sort(),[snapshot]);
  const companySectors=useMemo(()=>[...new Set((snapshot?.companies||[]).map(r=>r.gics_sector))].sort(),[snapshot]);

  function updateFilter(k,v){setActiveResult(null);setFilters(f=>({...f,[k]:v}));setVisibleCount(30);}
  function updateCompany(k,v){setActiveResult(null);setCf(f=>({...f,[k]:v}));setVisibleCount(30);}
  function selectEvidence(e){const d=e.data;setSelected(d.listing?{...d.listing,...d.emissions,...d.assessments}:d);}

  async function ask(text){
    if(busy||!text.trim())return;
    const current=++requestNumber.current;setQuestion(text);setBusy(true);setAskError('');setAnswer(null);setAssistantOpen(true);
    try{
      const context={view:view==='map'?'map':'companies',filters:view==='map'?filters:cf,selected_tickers:selected?.ticker?[selected.ticker]:[],selected_observation:selected?.plume_id||null};
      let response=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:text,context,history:history.slice(-6)}),signal:AbortSignal.timeout(65000)});
      let body=await response.json();
      if(response.status===400&&body.error?.includes('Provide only a question')){response=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:text}),signal:AbortSignal.timeout(65000)});body=await response.json();}
      if(!response.ok)throw Error(body.error||'The question could not be answered.');
      if(current!==requestNumber.current)return;
      setAnswer(body);setHistory(h=>[...h,{role:'user',text},{role:'assistant',text:body.answer}].slice(-6));
      const visualEvidence=body.evidence.filter(e=>body.visualization?.record_ids?.includes(e.id));
      if(body.visualization?.type==='map'){
        setView('map');setActiveResult({type:'map',rows:visualEvidence.map(e=>e.data),filters:body.visualization.filters});setFitKey(k=>k+1);
      }else if(body.visualization?.type==='company_table'){
        setView('table');setActiveResult({type:'company_table',rows:visualEvidence.map(e=>e.data),filters:body.visualization.filters});
      }else if(body.visualization?.type==='company_details'){
        setView('table');setActiveResult({type:'company_table',rows:visualEvidence.map(e=>({...e.data.listing,...e.data.emissions,...e.data.assessments})),filters:{tickers:visualEvidence.map(e=>e.id).join(', ')}});
      }
    }catch(e){setAskError(e.name==='TimeoutError'?'The answer took too long. Try again or explore the data using filters.':e.message);}
    finally{if(current===requestNumber.current)setBusy(false);}
  }

  function answerText(text=answer.answer){
    const ids=new Map((answer.evidence||[]).map(e=>[e.id,e]));
    return text.split(/(\[[^\]]+\])/g).map((part,i)=>{const e=ids.get(part.slice(1,-1));return e?<button key={i} className="citation" onClick={()=>selectEvidence(e)}>{e.data.place||e.data.company_name||e.data.listing?.ticker||e.id}<ArrowUpRight size={11}/></button>:<React.Fragment key={i}>{part}</React.Fragment>;});
  }

  return <div className="app">
    <header className="greenrank-nav">
      <div className="brand-group">
        <span className="brand-mark">GR</span>
        <div className="brand-text">
          <span className="brand-name">GreenRank</span>
          <span className="brand-tag">S&P 500 & Plume Evidence</span>
        </div>
      </div>

      <nav className="nav-tabs" role="tablist" aria-label="Main navigation">
        <button role="tab" aria-selected={view==='treemap'} className={view==='treemap'?'active':''} onClick={()=>{setView('treemap');setVisibleCount(30);}}>
          <PanelsTopLeft size={16}/><span>Concentration Treemap</span>
        </button>
        <button role="tab" aria-selected={view==='chart'} className={view==='chart'?'active':''} onClick={()=>{setView('chart');setVisibleCount(30);}}>
          <ScatterChart size={16}/><span>Promises vs Reality</span>
        </button>
        <button role="tab" aria-selected={view==='map'} className={view==='map'?'active':''} onClick={()=>{setView('map');setVisibleCount(30);}}>
          <Globe2 size={16}/><span>Plume Atlas</span>
        </button>
        <button role="tab" aria-selected={view==='table'} className={view==='table'?'active':''} onClick={()=>{setView('table');setVisibleCount(30);}}>
          <List size={16}/><span>Company Screener</span>
        </button>
      </nav>

      <div className="nav-actions">
        <div className="data-counts">
          <span><strong>{fmt(companies.length)}</strong> companies</span>
          <span className="sep">·</span>
          <span><strong>{fmt(plumes.length)}</strong> plumes</span>
        </div>
        <button className={`assistant-btn ${assistantOpen?'active':''}`} onClick={()=>setAssistantOpen(v=>!v)} title="Query dataset with AI">
          <Sparkles size={15}/><span>Ask Data</span>
        </button>
      </div>
    </header>

    <main className="workspace">
      <section className="explorer" aria-label="Data explorer">
        {view==='treemap'&&<div className="finding-banner">
          <div className="finding-main">
            <span className="finding-badge">CONCENTRATION FINDING</span>
            <p><strong>The 85/5 Concentration Paradox:</strong> 30 companies account for <strong>85%</strong> of S&P 500 direct Scope 1 emissions, but only <strong>5.1%</strong> of index market value. Toggle sizing below to see Big Tech collapse and Utilities dominate the index footprint.</p>
          </div>
          <div className="finding-metrics">
            <div className="finding-stat"><span>Top 10 Emitters</span><strong>49% <small>of emissions</small></strong></div>
            <div className="finding-stat"><span>Top 30 Emitters</span><strong>85% <small>of emissions</small></strong></div>
            <div className="finding-stat highlight"><span>Top 30 Market Weight</span><strong>5.1% <small>of index cap</small></strong></div>
          </div>
        </div>}

        {view==='chart'&&<div className="finding-banner">
          <div className="finding-main">
            <span className="finding-badge">TARGET AUDIT</span>
            <p><strong>Promises vs Measured Pace:</strong> 108 companies have both a usable reduction target and a measured Scope 1 trend. Above the dashed line means emissions are falling faster than promised; below it means the company is behind its promised pace. Below 0% means measured emissions increased.</p>
          </div>
          <div className="finding-metrics">
            <div className="finding-stat"><span>Audited With Targets</span><strong>108 <small>companies</small></strong></div>
            <div className="finding-stat alert"><span>Lagging Promised Pace</span><strong>78% <small>84 of 108</small></strong></div>
            <div className="finding-stat"><span>Average Shortfall</span><strong>3.0 <small>pp / year</small></strong></div>
          </div>
        </div>}

        {view==='map'&&<div className="finding-banner">
          <div className="finding-main">
            <span className="finding-badge">POINT-SOURCE EVIDENCE</span>
            <p><strong>12,936 Satellite-Detected Super-Emitters:</strong> High-resolution plume observations from Carbon Mapper satellites. Quantified point-source rates identify localized methane leaks, pipeline venting, and landfill plumes.</p>
          </div>
          <div className="finding-metrics">
            <div className="finding-stat"><span>Total Plumes</span><strong>{fmt(plumes.length)}</strong></div>
            <div className="finding-stat"><span>Methane (CH₄)</span><strong>{fmt(plumes.filter(r=>r.gas==='CH4').length)}</strong></div>
            <div className="finding-stat highlight"><span>Quantified Rates</span><strong>{fmt(plumes.filter(r=>r.emission_auto!=null).length)}</strong></div>
          </div>
        </div>}

        {view==='table'&&<div className="finding-banner">
          <div className="finding-main">
            <span className="finding-badge">COMPANY SCREENER</span>
            <p><strong>S&P 500 Emissions & Carbon Shadow-Price Screener:</strong> Auditable corporate emissions cross-referenced with EPA GHGRP facility data, SEC 10-K filings, and modeled carbon cost scenarios at $150/t.</p>
          </div>
          <div className="finding-metrics">
            <div className="finding-stat"><span>Universe</span><strong>500 <small>companies</small></strong></div>
            <div className="finding-stat"><span>Scope 1 Reported</span><strong>{companies.filter(c=>c.scope1_t!=null).length} <small>audited</small></strong></div>
            <div className="finding-stat alert"><span>With Target Gaps</span><strong>{companies.filter(c=>c.gap_pct_yr!=null).length} <small>tracked</small></strong></div>
          </div>
        </div>}

        {activeResult&&((view==='map')===(activeResult.type==='map'))?<div className="result-filter"><Sparkles size={15}/><span>AI query · {Object.entries(activeResult.filters||{}).map(([k,v])=>`${k}: ${v}`).join(' · ')}</span><button onClick={()=>setActiveResult(null)}><X size={14}/>Clear</button></div>:<div className="filters">
          {view==='map'?<><Field label="Gas"><select value={filters.gas} onChange={e=>updateFilter('gas',e.target.value)}><option value="CH4">Methane · CH₄</option><option value="CO2">Carbon dioxide · CO₂</option></select></Field><Field label="Location"><select value={filters.country} onChange={e=>updateFilter('country',e.target.value)}><option value="">Worldwide</option>{countries.map(c=><option key={c}>{c}</option>)}</select></Field><Field label="Sector"><select value={filters.sector} onChange={e=>updateFilter('sector',e.target.value)}><option value="">All sectors</option>{sectors.map(s=><option key={s}>{s}</option>)}</select></Field><details className="more-filters"><summary><SlidersHorizontal size={16}/><span>More</span></summary><div><Field label="From (inclusive)"><input type="date" value={filters.start} onChange={e=>updateFilter('start',e.target.value)}/></Field><Field label="To (inclusive)"><input type="date" value={filters.end} onChange={e=>updateFilter('end',e.target.value)}/></Field><Field label="Minimum rate · kg/h"><input type="number" min="0" value={filters.minRate} placeholder="Any rate" onChange={e=>updateFilter('minRate',e.target.value)}/></Field></div></details></>:<><Field label="Sector"><select value={cf.sector} onChange={e=>updateCompany('sector',e.target.value)}><option value="">All sectors</option>{companySectors.map(s=><option key={s}>{s}</option>)}</select></Field><Field label="Company"><input placeholder="Name or ticker" value={cf.search} onChange={e=>updateCompany('search',e.target.value)}/></Field><Field label="Sort by"><select value={cf.sort} onChange={e=>updateCompany('sort',e.target.value)}><option value="gap">Largest target gap</option><option value="emissions">Largest Scope 1</option><option value="risk">Scenario impact</option><option value="name">Company name</option></select></Field><Field label="Minimum gap · pp/yr"><input type="number" placeholder="Any gap" value={cf.minGap} onChange={e=>updateCompany('minGap',e.target.value)}/></Field></>}
        </div>}

        {loadError?<div className="empty-state" role="alert"><AlertCircle/><h3>Could not load the dataset</h3><p>{loadError}</p><button className="secondary" onClick={()=>window.location.reload()}>Try again</button></div>:!snapshot?<div className="empty-state"><LoaderCircle className="spin"/><h3>Loading GreenRank database</h3><p>Preparing 500 company records and 12,936 satellite plume observations…</p></div>:view==='map'?<>
          <MapView records={plumes} onSelect={setSelected} selection={selected} fitKey={fitKey}/>
          <div className="map-stats"><Metric label="Observations in selection" value={fmt(plumes.length)}/><Metric label="With a quantified rate" value={fmt(plumes.filter(r=>r.emission_auto!=null).length)}/><Metric label="Countries represented" value={new Set(plumes.map(r=>r.country).filter(Boolean)).size}/></div>
          <div className="observation-list"><div className="section-heading"><h3>Ranked Point-Source Observations</h3><span>Largest rates first <ArrowDown size={13}/></span></div>{!plumes.length?<div className="empty-state"><Search/><h3>No matching observations</h3><p>Try a wider date range or another location.</p></div>:rankedPlumes.slice(0,visibleCount).map((r,i)=><button className="observation-row" key={r.plume_id} onClick={()=>setSelected(r)}><span className="row-number">{String(i+1).padStart(2,'0')}</span><span className="location-icon"><Crosshair size={17}/></span><span className="row-main"><strong>{r.place||r.region||'Observation'}</strong><small>{r.country||'Unknown location'} · {r.ipcc_sector||'Sector unknown'}</small></span><span className="row-date">{r.observed_at_utc.slice(0,10)}</span><span className="row-rate"><strong>{r.emission_auto==null?'Unquantified':fmt(r.emission_auto)}</strong><small>kg {r.gas}/h</small></span><ChevronRight size={16}/></button>)}{plumes.length>visibleCount&&<button className="load-more" onClick={()=>setVisibleCount(n=>n+30)}>Show 30 more observations <Plus size={14}/></button>}</div>
        </>:view==='treemap'?<div className="company-surface">
          <CompanyTreemap rows={companies.map(r=>({...snapshot.companies.find(s=>s.ticker===r.ticker),...r}))} onSelect={setSelected} onSector={sector=>updateCompany('sector',sector)}/>
        </div>:view==='chart'?<div className="company-surface">
          <CompanyChart rows={companies} onSelect={setSelected}/>
          <div className="notice"><Info size={16}/><p>Dots represent companies with verified targets and historical reporting windows. A positive gap indicates annual progress is trailing the pledged target rate.</p></div>
        </div>:<div className="company-surface">
          <div className="table-scroll"><table><thead><tr><th>Company</th><th>Scope 1 <small>tCO₂e · year</small></th><th>Promised <small>% / year</small></th><th>Measured <small>% / year</small></th><th>Gap <small>pp / year</small></th><th>Coverage</th></tr></thead><tbody>{companies.slice(0,visibleCount).map(r=><tr key={r.ticker} onClick={()=>setSelected(r)}><td><button className="company-name" onClick={ev=>{ev.stopPropagation();setSelected(r);}}><CompanyLogo company={r}/><span><strong>{r.company_name}</strong><small>{r.ticker} · {r.gics_sector}</small></span></button></td><td>{compact(r.scope1_t)}<small>{r.scope1_year||'Unknown year'}</small></td><td>{pct(r.promised_pct_yr)}</td><td>{pct(r.delivered_pct_yr)}</td><td><span className={r.gap_pct_yr==null?'':r.gap_pct_yr>0?'gap-badge':'gap-badge good'}>{r.gap_pct_yr==null?'—':`${r.gap_pct_yr>0?'+':''}${fmt(r.gap_pct_yr,1)}`}</span></td><td><span className={`coverage ${r.coverage_tier}`}>{r.coverage_tier}</span></td></tr>)}</tbody></table></div>{!companies.length&&<div className="empty-state"><Search/><h3>No matching companies</h3><p>Adjust the search or sector filter.</p></div>}{companies.length>visibleCount&&<button className="load-more" onClick={()=>setVisibleCount(n=>n+30)}>Show 30 more companies <Plus size={14}/></button>}
          <div className="notice"><Info size={16}/><p>A positive gap means slower reductions than promised. Reporting periods and boundaries vary; missing figures remain unknown.</p></div>
        </div>}

        <div className="data-footer">
          <span><strong>GreenRank</strong> · Auditable Climate Intelligence</span>
          <span>Sources: EPA GHGRP (2023), Carbon Mapper (2025), SEC 10-K Filings</span>
          <span>Snapshot: September 2026</span>
        </div>
      </section>
    </main>

    <aside className={`insight-panel ${assistantOpen?'open':'collapsed'}`} aria-label="Dataset query assistant">
      <div className="panel-heading">
        <button className="assistant-title" onClick={()=>setAssistantOpen(v=>!v)} aria-expanded={assistantOpen}>
          <span className="assistant-status"><Sparkles size={16}/></span>
          <span>Data Query Assistant<small>Natural-language query</small></span>
        </button>
        <button className="icon-button assistant-toggle" onClick={()=>setAssistantOpen(v=>!v)} aria-label={assistantOpen?'Minimize assistant':'Open assistant'}>
          {assistantOpen?<Minus size={16}/>:<Sparkles size={16}/>}
        </button>
      </div>

      {assistantOpen&&<>
        <div className="panel-body" aria-live="polite">
          {busy?<div className="working-state"><LoaderCircle className="spin" size={26}/><p>Querying dataset & cross-referencing records…</p></div>:askError?<div className="assistant-error"><AlertCircle size={24}/><h3>Query could not be completed</h3><p>{askError}</p><button className="secondary" onClick={()=>ask(question)}><RotateCcw size={14}/>Try again</button></div>:answer?<div className="answer-content">
            <div className="eyebrow">{answer.status==='needs_clarification'?'MORE CONTEXT NEEDED':answer.status==='data_only'?'RECORDS RETRIEVED':'DECISION BRIEF'}</div>
            <h3>{answer.brief?.headline|| (answer.status==='no_results'?'No matching evidence':answer.status==='needs_clarification'?'A limit in the evidence':`${answer.evidence.length} records retrieved`)}</h3>
            {answer.brief&&<><div className="brief-meta"><span className={`confidence ${answer.brief.confidence}`}>{answer.brief.confidence} confidence</span>{answer.tool_calls?.length>0&&<span>{answer.tool_calls.length} analyses</span>}</div><h4>Key findings</h4><ul className="brief-list">{answer.brief.findings.map((finding,i)=><li key={i}>{answerText(finding)}</li>)}</ul><h4>Recommended actions</h4><ol className="brief-list actions">{answer.brief.recommended_actions.map((action,i)=><li key={i}>{action}</li>)}</ol></>}
            <div className="answer-text">{answerText()}</div>
            {answer.evidence.length>0&&<><h4>Supporting evidence</h4><div className="evidence-links">{answer.evidence.map(e=><button key={e.id} onClick={()=>selectEvidence(e)}><span>{e.data.place||e.data.company_name||e.data.listing?.company_name||e.id}</span><ArrowUpRight size={15}/></button>)}</div></>}
            {answer.limitations?.length>0&&<details className="limitations"><summary><Info size={14}/>Limits of this conclusion</summary><ul>{answer.limitations.map(n=><li key={n}>{n}</li>)}</ul></details>}
            {answer.brief?.follow_up_questions?.length>0&&<div className="follow-ups"><h4>Continue investigating</h4>{answer.brief.follow_up_questions.map(q=><button key={q} onClick={()=>ask(q)}>{q}<ArrowRight size={13}/></button>)}</div>}
            <button className="text-link" onClick={()=>{setQuestion('');setAnswer(null);input.current?.focus();}}>Ask another question <ArrowRight size={14}/></button>
          </div>:<div className="assistant-idle">
            <span className="idle-badge">LIVE QUERY</span>
            <h3>Ask the Dataset</h3>
            <p className="subtle">Ask natural language questions to query 500 S&P companies and 12,936 Carbon Mapper plumes. Answers filter the view and cite auditable records.</p>
            <div className="prompt-label">SAMPLE INVESTIGATIONS</div>
            <div className="idle-prompts">
              {prompts.map(({label,question:q})=><button key={label} onClick={()=>ask(q)}><Sparkles size={13}/><span>{q}</span></button>)}
            </div>
          </div>}
        </div>

        <form className="assistant-input" onSubmit={e=>{e.preventDefault();ask(question);}}>
          <label className="sr-only" htmlFor="assistant-question">Ask the climate data</label>
          <textarea ref={input} id="assistant-question" value={question} onChange={e=>setQuestion(e.target.value)} placeholder="e.g. Largest methane plumes in Texas, or utility target gaps…" maxLength={1000} disabled={busy} rows="2"/>
          <button className="primary" aria-label={busy?'Querying':'Ask the data'} disabled={busy||!question.trim()}>{busy?<LoaderCircle className="spin" size={17}/>:<ArrowUpRight size={17}/>}</button>
        </form>
      </>}
    </aside>

    {selected&&<EvidenceDrawer key={selected.plume_id||selected.ticker} item={selected} onClose={()=>setSelected(null)} onAsk={ask}/>}
  </div>;
}
createRoot(document.getElementById('root')).render(<App/>);
