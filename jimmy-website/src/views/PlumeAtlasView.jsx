import React, { useEffect, useRef, useState, useMemo } from 'react';
import L from 'leaflet';
import Supercluster from 'supercluster';
import {
  Plus,
  Minus,
  Focus,
  Crosshair,
  ArrowDown,
  Search,
  ChevronRight,
  Radio,
  Layers,
  Compass
} from 'lucide-react';
import { Metric } from '../components/Metric';
import { fmt, compact } from '../utils/formatters';

const BASINS = [
  { name: 'Permian Basin (USA)', lat: 31.8, lon: -102.3, zoom: 7 },
  { name: 'Caspian / Central Asia', lat: 39.5, lon: 54.5, zoom: 6 },
  { name: 'US Gulf Coast', lat: 29.8, lon: -94.5, zoom: 7 },
  { name: 'Appalachian', lat: 40.2, lon: -80.2, zoom: 7 }
];

export function MapView({ records, onSelect, selection, fitKey }) {
  const el = useRef(null),
    map = useRef(null),
    layer = useRef(null),
    scatterCanvas = useRef(null),
    index = useRef(null),
    select = useRef(onSelect);
  const [tileError, setTileError] = useState(false);
  const [mode, setMode] = useState('telemetry'); // 'telemetry' | 'cluster'
  const [severity, setSeverity] = useState('all'); // 'all' | 'severe' | 'super'
  const [hovered, setHovered] = useState(null);
  select.current = onSelect;

  // Filter records based on selected severity threshold
  const activeRecords = useMemo(() => {
    if (severity === 'super') {
      return records.filter(r => r.emission_auto != null && r.emission_auto >= 2500);
    }
    if (severity === 'severe') {
      return records.filter(r => r.emission_auto != null && r.emission_auto >= 1000);
    }
    return records;
  }, [records, severity]);

  useEffect(() => {
    map.current = L.map(el.current, {
      zoomControl: false,
      preferCanvas: true,
      minZoom: 1,
      maxZoom: 16,
      worldCopyJump: true
    }).setView([24, 8], el.current.clientWidth < 600 ? 1 : 2);

    // Esri World Dark Gray Canvas: free, zero-key, high-contrast dark basemap with zero watermarks
    L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
      {
        attribution:
          '&copy; <a href="https://www.esri.com/">Esri</a> &copy; OpenStreetMap contributors',
        maxZoom: 16
      }
    )
      .on('tileerror', () => setTileError(true))
      .addTo(map.current);

    // Subtle country and state boundary reference labels
    L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
      {
        attribution: '',
        maxZoom: 16,
        pane: 'tilePane'
      }
    ).addTo(map.current);

    // Canvas layer for luminous telemetry micro-scatter
    const canvas = L.DomUtil.create('canvas', 'leaflet-scatter-canvas');
    canvas.style.position = 'absolute';
    canvas.style.pointerEvents = 'none';
    map.current.getPanes().overlayPane.appendChild(canvas);
    scatterCanvas.current = canvas;

    layer.current = L.layerGroup().addTo(map.current);

    const onZoomAnim = e => {
      if (!map.current || !scatterCanvas.current) return;
      const scale = map.current.getZoomScale(e.zoom);
      const offset = map.current._latLngBoundsToNewLayerBounds(map.current.getBounds(), e.zoom, e.center).min;
      L.DomUtil.setTransform(scatterCanvas.current, offset, scale);
    };
    map.current.on('zoomanim', onZoomAnim);

    const observer = new ResizeObserver(() => map.current?.invalidateSize());
    observer.observe(el.current);

    return () => {
      observer.disconnect();
      if (scatterCanvas.current && scatterCanvas.current.parentNode) {
        scatterCanvas.current.parentNode.removeChild(scatterCanvas.current);
      }
      map.current?.remove();
    };
  }, []);

  // Update supercluster index for cluster mode
  useEffect(() => {
    index.current = new Supercluster({ radius: 45, maxZoom: 10 }).load(
      activeRecords.map(r => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [r.plume_longitude, r.plume_latitude] },
        properties: { record: r }
      }))
    );
  }, [activeRecords]);

  // Main rendering logic
  useEffect(() => {
    if (!map.current) return;

    function drawClusters() {
      if (!map.current || !layer.current || !index.current) return;
      layer.current.clearLayers();
      const features = index.current.getClusters(
        [-180, -85, 180, 85],
        Math.min(16, Math.floor(map.current.getZoom()))
      );
      for (const feature of features) {
        const [lon, lat] = feature.geometry.coordinates,
          p = feature.properties;
        if (p.cluster) {
          const size = p.point_count > 100 ? 44 : 36;
          L.marker([lat, lon], {
            icon: L.divIcon({
              className: 'cluster-icon',
              html: `<span>${compact(p.point_count)}</span>`,
              iconSize: [size, size]
            }),
            keyboard: true,
            title: `${p.point_count} observations. Zoom in.`
          })
            .on('click', () =>
              map.current.flyTo(
                [lat, lon],
                Math.min(index.current.getClusterExpansionZoom(p.cluster_id), 16),
                { duration: 0.65 }
              )
            )
            .addTo(layer.current);
        } else {
          const r = p.record,
            rate = r.emission_auto;
          const radius = rate == null ? 4 : Math.min(17, 3 + Math.sqrt(rate) / 18);
          const marker = L.circleMarker([lat, lon], {
            radius,
            color: rate == null ? '#94a3b8' : r.gas === 'CH4' ? '#d2f783' : '#79caff',
            fillColor: r.gas === 'CH4' ? '#c5f36b' : '#79caff',
            fillOpacity: rate == null ? 0 : 0.65,
            weight: 1
          });
          const tooltip = document.createElement('div');
          tooltip.textContent = `${r.place || r.region || r.country || 'Observation'} · ${rate == null ? 'Unquantified' : fmt(rate) + ' kg ' + r.gas + '/h'}`;
          marker.bindTooltip(tooltip).on('click', () => select.current(r)).addTo(layer.current);
        }
      }
    }

    function drawScatter() {
      if (!map.current || !scatterCanvas.current) return;
      const canvas = scatterCanvas.current;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const size = map.current.getSize();
      if (canvas.width !== size.x || canvas.height !== size.y) {
        canvas.width = size.x;
        canvas.height = size.y;
        canvas.style.width = `${size.x}px`;
        canvas.style.height = `${size.y}px`;
      }

      const topLeft = map.current.containerPointToLayerPoint([0, 0]);
      L.DomUtil.setPosition(canvas, topLeft);
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      if (!activeRecords.length) return;

      const zoom = map.current.getZoom();
      const width = canvas.width;
      const height = canvas.height;

      // Tight, crisp base radius that scales subtly with zoom
      const baseR = zoom <= 2 ? 1.6 : zoom <= 4 ? 2.1 : zoom <= 7 ? 2.8 : 3.8;

      // Tier 1: Low / Moderate Baseline (< 500 kg/h or unquantified)
      // Crisp electric cyan pinpoints
      ctx.fillStyle = 'rgba(56, 189, 248, 0.45)';
      ctx.beginPath();
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const rate = r.emission_auto;
        if (rate != null && rate >= 500) continue;
        const pt = map.current.latLngToContainerPoint([r.plume_latitude, r.plume_longitude]);
        if (pt.x < -10 || pt.x > width + 10 || pt.y < -10 || pt.y > height + 10) continue;
        ctx.moveTo(pt.x + baseR, pt.y);
        ctx.arc(pt.x, pt.y, baseR, 0, Math.PI * 2);
      }
      ctx.fill();

      // Tier 2: Moderate Leaks (500 - 2,500 kg/h)
      // Warm amber yellow dots
      const tier2R = baseR + 0.6;
      ctx.fillStyle = 'rgba(250, 204, 21, 0.72)';
      ctx.beginPath();
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const rate = r.emission_auto;
        if (rate == null || rate < 500 || rate >= 2500) continue;
        const pt = map.current.latLngToContainerPoint([r.plume_latitude, r.plume_longitude]);
        if (pt.x < -10 || pt.x > width + 10 || pt.y < -10 || pt.y > height + 10) continue;
        ctx.moveTo(pt.x + tier2R, pt.y);
        ctx.arc(pt.x, pt.y, tier2R, 0, Math.PI * 2);
      }
      ctx.fill();

      // Tier 3: Super-Emitters (> 2,500 kg/h)
      // Halos first
      const tier3R = baseR + 1.4;
      ctx.fillStyle = 'rgba(245, 78, 0, 0.22)';
      ctx.beginPath();
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const rate = r.emission_auto;
        if (rate == null || rate < 2500) continue;
        const pt = map.current.latLngToContainerPoint([r.plume_latitude, r.plume_longitude]);
        if (pt.x < -20 || pt.x > width + 20 || pt.y < -20 || pt.y > height + 20) continue;
        ctx.moveTo(pt.x + tier3R * 2.4, pt.y);
        ctx.arc(pt.x, pt.y, tier3R * 2.4, 0, Math.PI * 2);
      }
      ctx.fill();

      // Tier 3 Core: Cursor Orange luminous dots
      ctx.fillStyle = '#f54e00';
      ctx.beginPath();
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const rate = r.emission_auto;
        if (rate == null || rate < 2500) continue;
        const pt = map.current.latLngToContainerPoint([r.plume_latitude, r.plume_longitude]);
        if (pt.x < -10 || pt.x > width + 10 || pt.y < -10 || pt.y > height + 10) continue;
        ctx.moveTo(pt.x + tier3R, pt.y);
        ctx.arc(pt.x, pt.y, tier3R, 0, Math.PI * 2);
      }
      ctx.fill();

      // Highlight selected plume with targeting crosshair
      layer.current.clearLayers();
      if (selection?.plume_id) {
        const sPt = [selection.plume_latitude, selection.plume_longitude];
        L.circleMarker(sPt, {
          radius: 13,
          color: '#f54e00',
          weight: 1.5,
          fillColor: 'transparent',
          dashArray: '3, 3'
        }).addTo(layer.current);

        L.circleMarker(sPt, {
          radius: 4,
          color: '#ffffff',
          weight: 1.5,
          fillColor: '#f54e00',
          fillOpacity: 1
        })
          .bindTooltip(
            `${selection.place || selection.region || 'Selected observation'} · ${selection.emission_auto ? fmt(selection.emission_auto) + ' kg/h' : 'Unquantified'}`
          )
          .addTo(layer.current);
      }
    }

    function renderCurrentView() {
      if (mode === 'telemetry') {
        if (scatterCanvas.current) scatterCanvas.current.style.display = 'block';
        drawScatter();
      } else {
        if (scatterCanvas.current) {
          scatterCanvas.current.style.display = 'none';
          const ctx = scatterCanvas.current.getContext('2d');
          if (ctx) ctx.clearRect(0, 0, scatterCanvas.current.width, scatterCanvas.current.height);
        }
        drawClusters();
      }
    }

    renderCurrentView();

    const onMove = () => renderCurrentView();
    map.current.on('moveend zoomend viewreset resize', onMove);

    return () => {
      map.current?.off('moveend zoomend viewreset resize', onMove);
    };
  }, [activeRecords, mode, selection]);

  // Click & hover telemetry detection
  useEffect(() => {
    if (!map.current) return;

    const onClick = e => {
      if (mode !== 'telemetry') return;
      const clickPt = e.containerPoint;
      let closest = null;
      let minDist = 24;
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const pt = map.current.latLngToContainerPoint([r.plume_latitude, r.plume_longitude]);
        const dx = pt.x - clickPt.x;
        const dy = pt.y - clickPt.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < minDist) {
          minDist = dist;
          closest = r;
        }
      }
      if (closest) {
        select.current(closest);
      }
    };

    const onMouseMove = e => {
      if (mode !== 'telemetry' || !map.current) {
        setHovered(null);
        return;
      }
      const mousePt = e.containerPoint;
      let closest = null;
      let minDist = 18;
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const pt = map.current.latLngToContainerPoint([r.plume_latitude, r.plume_longitude]);
        const dx = pt.x - mousePt.x;
        const dy = pt.y - mousePt.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < minDist) {
          minDist = dist;
          closest = { record: r, x: mousePt.x, y: mousePt.y };
        }
      }

      setHovered(closest);
      map.current.getContainer().style.cursor = closest ? 'crosshair' : '';
    };

    const onMouseLeave = () => setHovered(null);

    map.current.on('click', onClick);
    map.current.on('mousemove', onMouseMove);
    map.current.getContainer().addEventListener('mouseleave', onMouseLeave);

    return () => {
      map.current?.off('click', onClick);
      map.current?.off('mousemove', onMouseMove);
      map.current?.getContainer().removeEventListener('mouseleave', onMouseLeave);
    };
  }, [mode, activeRecords]);

  useEffect(() => {
    if (!map.current) return;
    if (selection?.plume_id)
      map.current.flyTo([selection.plume_latitude, selection.plume_longitude], 8, { duration: 1 });
  }, [selection]);

  const fit = () => {
    if (activeRecords.length) {
      const bounds = L.latLngBounds(activeRecords.map(r => [r.plume_latitude, r.plume_longitude]));
      map.current.flyToBounds(bounds, { padding: [50, 50], maxZoom: 8, duration: 0.85 });
    }
  };

  useEffect(() => {
    if (fitKey) fit();
  }, [fitKey]);

  return (
    <div className="map-shell">
      <div ref={el} className="map" aria-label="Global map of observed greenhouse gas plumes" />

      {/* Basin Jump Pills */}
      <div className="basin-jump-bar" aria-label="Quick jump to key emission basins">
        <span className="basin-jump-label">
          <Compass size={11} /> Basins:
        </span>
        {BASINS.map(b => (
          <button
            key={b.name}
            type="button"
            className="basin-jump-btn"
            onClick={() => map.current?.flyTo([b.lat, b.lon], b.zoom, { duration: 1 })}
          >
            {b.name}
          </button>
        ))}
      </div>

      {/* Severity Filter & Mode Switcher */}
      <div className="map-top-actions">
        <div className="severity-filter" role="group" aria-label="Emission severity filter">
          <button
            type="button"
            className={severity === 'all' ? 'active' : ''}
            onClick={() => setSeverity('all')}
            title="Show all observations"
          >
            All ({compact(records.length)})
          </button>
          <button
            type="button"
            className={severity === 'severe' ? 'active' : ''}
            onClick={() => setSeverity('severe')}
            title="Filter to rates > 1,000 kg/h"
          >
            &gt; 1k kg/h
          </button>
          <button
            type="button"
            className={severity === 'super' ? 'active' : ''}
            onClick={() => setSeverity('super')}
            title="Filter to super-emitters > 2,500 kg/h"
          >
            Super-Emitters
          </button>
        </div>

        <div className="map-mode-toggle" role="group" aria-label="Map display mode">
          <button
            type="button"
            className={mode === 'telemetry' ? 'active' : ''}
            onClick={() => setMode('telemetry')}
            title="Luminous micro-scatter telemetry"
          >
            <Radio size={12} />
            <span>Telemetry</span>
          </button>
          <button
            type="button"
            className={mode === 'cluster' ? 'active' : ''}
            onClick={() => setMode('cluster')}
            title="Observation count clusters"
          >
            <Layers size={12} />
            <span>Clusters</span>
          </button>
        </div>
      </div>

      {/* Map Zoom & Fit Controls */}
      <div className="map-controls">
        <button title="Zoom in" aria-label="Zoom in" onClick={() => map.current.zoomIn()}>
          <Plus size={18} />
        </button>
        <button title="Zoom out" aria-label="Zoom out" onClick={() => map.current.zoomOut()}>
          <Minus size={18} />
        </button>
        <button title="Fit results" aria-label="Fit results" onClick={fit}>
          <Focus size={18} />
        </button>
      </div>

      {/* Telemetry Hover Tooltip Badge */}
      {hovered && (
        <div
          className="map-telemetry-tooltip"
          style={{
            left: `${Math.min(hovered.x + 12, (el.current?.clientWidth || 800) - 220)}px`,
            top: `${Math.max(12, hovered.y - 48)}px`
          }}
        >
          <div className="tooltip-title">
            <Crosshair size={11} />
            <span>{hovered.record.place || hovered.record.region || 'Point-source observation'}</span>
          </div>
          <div className="tooltip-meta">
            <strong>
              {hovered.record.emission_auto != null
                ? `${fmt(hovered.record.emission_auto)} kg ${hovered.record.gas}/h`
                : 'Unquantified rate'}
            </strong>
            <small>{hovered.record.country || 'Global location'} · Click to inspect</small>
          </div>
        </div>
      )}

      {/* Map Legend */}
      <div className="map-legend">
        {mode === 'telemetry' ? (
          <>
            <div className="legend-item">
              <i className="dot-cyan" />
              <span>&lt; 500 kg/h</span>
            </div>
            <div className="legend-item">
              <i className="dot-amber" />
              <span>500 to 2,500 kg/h</span>
            </div>
            <div className="legend-item">
              <i className="dot-orange" />
              <span>&gt; 2,500 kg/h Super-Emitter</span>
            </div>
            <div className="legend-hint">Overlap forms luminous clusters · Click to inspect</div>
          </>
        ) : (
          <>
            <div>
              <span className="legend-cluster">12</span> Cluster count
            </div>
            <div>
              <i className="legend-dot" /> Observed rate <span className="muted">kg/h</span>
            </div>
            <div>
              <i className="legend-dot empty" /> Unquantified
            </div>
          </>
        )}
      </div>

      <div className="map-note">
        {tileError
          ? 'Some map tiles are unavailable. Observation results remain accessible below.'
          : 'No observations does not mean no emissions.'}
      </div>
    </div>
  );
}

export function PlumeAtlasView({
  plumes,
  rankedPlumes,
  selected,
  onSelect,
  fitKey,
  visibleCount,
  setVisibleCount
}) {
  const uniqueCountries = new Set(plumes.map(r => r.country).filter(Boolean)).size;

  return (
    <>
      <div className="finding-banner">
        <div className="finding-main">
          <span className="finding-badge">POINT-SOURCE EVIDENCE</span>
          <p>
            <strong>12,936 Satellite-Detected Super-Emitters:</strong> High-resolution plume observations from Carbon Mapper satellites. Quantified point-source rates identify localized methane leaks, pipeline venting, and landfill plumes.
          </p>
        </div>
        <div className="finding-metrics">
          <div className="finding-stat">
            <span>Total Plumes</span>
            <strong>{fmt(plumes.length)}</strong>
          </div>
          <div className="finding-stat">
            <span>Methane (CH₄)</span>
            <strong>{fmt(plumes.filter(r => r.gas === 'CH4').length)}</strong>
          </div>
          <div className="finding-stat highlight">
            <span>Quantified Rates</span>
            <strong>{fmt(plumes.filter(r => r.emission_auto != null).length)}</strong>
          </div>
        </div>
      </div>

      <MapView records={plumes} onSelect={onSelect} selection={selected} fitKey={fitKey} />

      <div className="map-stats">
        <Metric label="Observations in selection" value={fmt(plumes.length)} />
        <Metric
          label="With a quantified rate"
          value={fmt(plumes.filter(r => r.emission_auto != null).length)}
        />
        <Metric label="Countries represented" value={uniqueCountries} />
      </div>

      <div className="observation-list">
        <div className="section-heading">
          <h3>Ranked Point-Source Observations</h3>
          <span>
            Largest rates first <ArrowDown size={13} />
          </span>
        </div>
        {!plumes.length ? (
          <div className="empty-state">
            <Search />
            <h3>No matching observations</h3>
            <p>Try a wider date range or another location.</p>
          </div>
        ) : (
          rankedPlumes.slice(0, visibleCount).map((r, i) => (
            <button
              className="observation-row"
              key={r.plume_id}
              onClick={() => onSelect(r)}
            >
              <span className="row-number">{String(i + 1).padStart(2, '0')}</span>
              <span className="location-icon">
                <Crosshair size={17} />
              </span>
              <span className="row-main">
                <strong>{r.place || r.region || 'Observation'}</strong>
                <small>
                  {r.country || 'Unknown location'} · {r.ipcc_sector || 'Sector unknown'}
                </small>
              </span>
              <span className="row-date">{r.observed_at_utc.slice(0, 10)}</span>
              <span className="row-rate">
                <strong>{r.emission_auto == null ? 'Unquantified' : fmt(r.emission_auto)}</strong>
                <small>kg {r.gas}/h</small>
              </span>
              <ChevronRight size={16} />
            </button>
          ))
        )}
        {plumes.length > visibleCount && (
          <button className="load-more" onClick={() => setVisibleCount(n => n + 30)}>
            Show 30 more observations <Plus size={14} />
          </button>
        )}
      </div>
    </>
  );
}
