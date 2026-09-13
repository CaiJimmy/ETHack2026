import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import Supercluster from 'supercluster';
import { Plus, Minus, Focus, Crosshair, ArrowDown, Search, ChevronRight } from 'lucide-react';
import { Metric } from '../components/Metric';
import { fmt, compact } from '../utils/formatters';

export function MapView({ records, onSelect, selection, fitKey }) {
  const el = useRef(null),
    map = useRef(null),
    layer = useRef(null),
    index = useRef(null),
    select = useRef(onSelect);
  const [tileError, setTileError] = useState(false);
  select.current = onSelect;
  const draw = useRef(() => {});

  useEffect(() => {
    map.current = L.map(el.current, {
      zoomControl: false,
      preferCanvas: true,
      minZoom: 1,
      maxZoom: 16,
      worldCopyJump: true
    }).setView([24, 8], el.current.clientWidth < 600 ? 1 : 2);

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20
    })
      .on('tileerror', () => setTileError(true))
      .addTo(map.current);

    layer.current = L.layerGroup().addTo(map.current);
    map.current.on('moveend zoomend', () => draw.current());

    const observer = new ResizeObserver(() => map.current?.invalidateSize());
    observer.observe(el.current);

    return () => {
      observer.disconnect();
      map.current?.remove();
    };
  }, []);

  useEffect(() => {
    index.current = new Supercluster({ radius: 45, maxZoom: 10 }).load(
      records.map(r => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [r.plume_longitude, r.plume_latitude] },
        properties: { record: r }
      }))
    );

    draw.current = () => {
      if (!map.current || !layer.current) return;
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
    };
    draw.current();
  }, [records]);

  useEffect(() => {
    if (!map.current) return;
    if (selection?.plume_id)
      map.current.flyTo([selection.plume_latitude, selection.plume_longitude], 8, { duration: 1 });
  }, [selection]);

  const fit = () => {
    if (records.length) {
      const bounds = L.latLngBounds(records.map(r => [r.plume_latitude, r.plume_longitude]));
      map.current.flyToBounds(bounds, { padding: [50, 50], maxZoom: 8, duration: 0.85 });
    }
  };

  useEffect(() => {
    if (fitKey) fit();
  }, [fitKey]);

  return (
    <div className="map-shell">
      <div ref={el} className="map" aria-label="Global map of observed greenhouse gas plumes" />
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
      <div className="map-legend">
        <div>
          <span className="legend-cluster">12</span> Cluster count
        </div>
        <div>
          <i className="legend-dot" /> Observed rate <span className="muted">kg/h</span>
        </div>
        <div>
          <i className="legend-dot empty" /> Unquantified
        </div>
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
