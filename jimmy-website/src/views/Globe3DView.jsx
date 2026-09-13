import React, { useEffect, useRef, useState, useMemo } from 'react';
import {
  Plus,
  Minus,
  Focus,
  Crosshair,
  Play,
  Pause,
  Compass,
  Map
} from 'lucide-react';
import { fmt, compact } from '../utils/formatters';

const BASINS = [
  { name: 'Permian Basin (USA)', lat: 31.8, lon: -102.3, zoomR: 240 },
  { name: 'Caspian / Central Asia', lat: 39.5, lon: 54.5, zoomR: 240 },
  { name: 'US Gulf Coast', lat: 29.8, lon: -94.5, zoomR: 250 },
  { name: 'Appalachian', lat: 40.2, lon: -80.2, zoomR: 250 }
];

// Simplified continent boundary polygons [longitude, latitude]
const CONTINENT_POLYGONS = [
  // North America
  [[-168,66],[-165,60],[-150,59],[-136,56],[-124,49],[-123,38],[-117,32],[-106,23],[-97,16],[-83,9],[-77,8],[-80,18],[-82,23],[-80,25],[-75,35],[-71,43],[-60,46],[-65,58],[-76,63],[-85,68],[-95,70],[-120,70],[-140,70],[-168,66]],
  // Mexico & Gulf Coast
  [[-97,18],[-90,20],[-88,21],[-82,25],[-80,28],[-81,31],[-85,30],[-90,30],[-95,29],[-97,26],[-97,18]],
  // South America
  [[-77,8],[-75,12],[-60,9],[-50,0],[-35,-5],[-35,-10],[-40,-22],[-50,-30],[-55,-40],[-65,-55],[-75,-50],[-72,-40],[-70,-30],[-75,-15],[-80,-2],[-77,8]],
  // Europe
  [[-10,36],[-9,43],[0,44],[5,44],[10,55],[8,58],[15,56],[22,60],[28,71],[20,70],[15,65],[12,61],[5,62],[5,53],[0,49],[-5,48],[-10,36]],
  // Scandinavia
  [[5,58],[10,58],[18,60],[25,65],[30,71],[25,71],[15,68],[10,63],[5,58]],
  // Eurasia
  [[25,70],[40,68],[60,70],[80,72],[100,75],[120,74],[140,70],[170,68],[180,65],[170,60],[140,50],[130,42],[122,30],[115,22],[105,10],[100,3],[98,10],[80,15],[70,22],[60,25],[50,28],[45,15],[35,32],[28,40],[25,45],[30,55],[25,70]],
  // India
  [[68,24],[73,18],[78,8],[80,13],[88,21],[88,26],[78,28],[68,24]],
  // Africa
  [[-17,15],[-17,21],[-5,36],[10,37],[25,32],[32,30],[42,12],[51,10],[45,-12],[35,-25],[28,-34],[18,-34],[12,-15],[8,4],[-12,6],[-17,15]],
  // Australia
  [[114,-22],[120,-34],[135,-35],[145,-38],[152,-28],[148,-18],[140,-12],[130,-14],[120,-16],[114,-22]],
  // Greenland
  [[-50,60],[-40,60],[-25,70],[-20,80],[-40,83],[-55,75],[-50,60]],
  // British Isles
  [[-5,50],[2,51],[0,58],[-4,58],[-5,50]],
  // Japan
  [[130,32],[135,35],[141,43],[140,36],[130,32]]
];

// Project spherical lat/lon to 2D screen coordinate with rotation
function projectSpherical(lat, lon, rotLon, rotLat, R, cx, cy) {
  const rad = Math.PI / 180;
  const phi = lat * rad;
  const lambda = lon * rad;
  const lambda0 = rotLon * rad;
  const phi0 = rotLat * rad;

  // Y-axis rotation (longitude)
  const x0 = Math.cos(phi) * Math.sin(lambda - lambda0);
  const y0 = Math.sin(phi);
  const z0 = Math.cos(phi) * Math.cos(lambda - lambda0);

  // X-axis rotation (latitude tilt)
  const x1 = x0;
  const y1 = y0 * Math.cos(phi0) - z0 * Math.sin(phi0);
  const z1 = y0 * Math.sin(phi0) + z0 * Math.cos(phi0);

  return {
    x: cx + x1 * R,
    y: cy - y1 * R,
    z: z1,
    visible: z1 > 0
  };
}

export function Globe3DView({
  records,
  selection,
  onSelect,
  severity,
  setSeverity,
  viewType,
  setViewType
}) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);

  // Refs for animation & drag interaction
  const stateRef = useRef({
    rotLon: -30,
    rotLat: 25,
    radius: 210,
    targetRotLon: -30,
    targetRotLat: 25,
    targetRadius: 210,
    isDragging: false,
    dragStart: { x: 0, y: 0 },
    dragAngles: { lon: -30, lat: 25 },
    autoRotate: true,
    hovered: null,
    dpr: 1,
    width: 800,
    height: 500
  });

  const [autoRotate, setAutoRotate] = useState(true);
  const [hovered, setHovered] = useState(null);

  stateRef.current.autoRotate = autoRotate;

  // When external selection changes, smoothly rotate to selected plume
  useEffect(() => {
    if (selection?.plume_id) {
      stateRef.current.targetRotLon = selection.plume_longitude;
      stateRef.current.targetRotLat = selection.plume_latitude;
      stateRef.current.targetRadius = Math.max(stateRef.current.radius, 240);
    }
  }, [selection]);

  // Filter records based on selected severity
  const activeRecords = useMemo(() => {
    if (severity === 'super') {
      return records.filter(r => r.emission_auto != null && r.emission_auto >= 2500);
    }
    if (severity === 'severe') {
      return records.filter(r => r.emission_auto != null && r.emission_auto >= 1000);
    }
    return records;
  }, [records, severity]);

  // Main Canvas Render & Animation Loop
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let animId = null;

    // Pre-generate stars for background space aesthetic
    const stars = Array.from({ length: 65 }, () => ({
      x: Math.random(),
      y: Math.random(),
      size: Math.random() * 1.4 + 0.4,
      alpha: Math.random() * 0.55 + 0.15
    }));

    function render() {
      const s = stateRef.current;
      const dpr = s.dpr || window.devicePixelRatio || 1;
      const cssWidth = s.width || (canvas.width / dpr);
      const cssHeight = s.height || (canvas.height / dpr);
      const cx = cssWidth / 2;
      const cy = cssHeight / 2;

      // Smooth interpolation toward target angles
      if (!s.isDragging) {
        if (s.autoRotate) {
          s.targetRotLon += 0.08;
        }
        s.rotLon += (s.targetRotLon - s.rotLon) * 0.08;
        s.rotLat += (s.targetRotLat - s.rotLat) * 0.08;
        s.radius += (s.targetRadius - s.radius) * 0.08;
      }

      const R = s.radius;
      const rLon = s.rotLon;
      const rLat = s.rotLat;

      // Clear full buffer in raw physical pixels
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = '#0a0f14';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Now scale context by DPR so all coordinates (cx, cy, R) are exact CSS pixels
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // 1. Draw subtle background starfield
      for (let i = 0; i < stars.length; i++) {
        const star = stars[i];
        ctx.fillStyle = `rgba(226, 232, 240, ${star.alpha})`;
        ctx.beginPath();
        ctx.arc(star.x * cssWidth, star.y * cssHeight, star.size, 0, Math.PI * 2);
        ctx.fill();
      }

      // 2. Atmospheric Outer Glow
      const glowGrad = ctx.createRadialGradient(cx, cy, R * 0.96, cx, cy, R * 1.18);
      glowGrad.addColorStop(0, 'rgba(56, 189, 248, 0.22)');
      glowGrad.addColorStop(0.5, 'rgba(56, 189, 248, 0.08)');
      glowGrad.addColorStop(1, 'rgba(56, 189, 248, 0)');
      ctx.fillStyle = glowGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.18, 0, Math.PI * 2);
      ctx.fill();

      // 3. Globe Base Sphere (Clipped)
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.clip();

      // Sphere internal lighting gradient
      const sphereGrad = ctx.createRadialGradient(cx - R * 0.28, cy - R * 0.28, R * 0.1, cx, cy, R);
      sphereGrad.addColorStop(0, '#13202d');
      sphereGrad.addColorStop(0.7, '#0c151e');
      sphereGrad.addColorStop(1, '#060b0f');
      ctx.fillStyle = sphereGrad;
      ctx.fill();

      // 4. Draw Graticule Coordinate Grid (Parallels & Meridians)
      ctx.lineWidth = 0.8;

      // Parallels (Latitude lines)
      const parallels = [-60, -30, 0, 30, 60];
      for (const lat of parallels) {
        ctx.beginPath();
        let started = false;
        for (let lon = -180; lon <= 180; lon += 6) {
          const pt = projectSpherical(lat, lon, rLon, rLat, R, cx, cy);
          if (pt.z > -0.15) {
            if (!started) {
              ctx.moveTo(pt.x, pt.y);
              started = true;
            } else {
              ctx.lineTo(pt.x, pt.y);
            }
          } else {
            started = false;
          }
        }
        ctx.strokeStyle = lat === 0 ? 'rgba(56, 189, 248, 0.32)' : 'rgba(74, 108, 138, 0.16)';
        ctx.stroke();
      }

      // Meridians (Longitude lines)
      for (let lon = -180; lon < 180; lon += 30) {
        ctx.beginPath();
        let started = false;
        for (let lat = -80; lat <= 80; lat += 6) {
          const pt = projectSpherical(lat, lon, rLon, rLat, R, cx, cy);
          if (pt.z > -0.15) {
            if (!started) {
              ctx.moveTo(pt.x, pt.y);
              started = true;
            } else {
              ctx.lineTo(pt.x, pt.y);
            }
          } else {
            started = false;
          }
        }
        ctx.strokeStyle = 'rgba(74, 108, 138, 0.16)';
        ctx.stroke();
      }

      // 5. Draw Continents
      ctx.fillStyle = 'rgba(25, 41, 56, 0.78)';
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.28)';
      ctx.lineWidth = 1;

      for (let p = 0; p < CONTINENT_POLYGONS.length; p++) {
        const poly = CONTINENT_POLYGONS[p];
        ctx.beginPath();
        let started = false;

        for (let i = 0; i < poly.length; i++) {
          const [lon1, lat1] = poly[i];
          const [lon2, lat2] = poly[(i + 1) % poly.length];

          // Interpolate 3 segments per edge for smooth spherical arc
          for (let step = 0; step <= 2; step++) {
            const t = step / 2;
            const curLon = lon1 + (lon2 - lon1) * t;
            const curLat = lat1 + (lat2 - lat1) * t;
            const pt = projectSpherical(curLat, curLon, rLon, rLat, R, cx, cy);

            if (pt.z > -0.2) {
              if (!started) {
                ctx.moveTo(pt.x, pt.y);
                started = true;
              } else {
                ctx.lineTo(pt.x, pt.y);
              }
            } else {
              started = false;
            }
          }
        }
        ctx.fill();
        ctx.stroke();
      }

      // Antarctica south cap
      ctx.beginPath();
      for (let lon = -180; lon <= 180; lon += 12) {
        const pt = projectSpherical(-72, lon, rLon, rLat, R, cx, cy);
        if (pt.z > -0.2) ctx.lineTo(pt.x, pt.y);
      }
      ctx.fillStyle = 'rgba(30, 48, 65, 0.7)';
      ctx.fill();

      // 6. Draw Methane Plumes (Micro-Scatter on 3D Globe)
      const baseDotR = R < 180 ? 1.5 : R < 250 ? 2.1 : 2.8;

      // Batch 1: Baseline / Low (< 500 kg/h or unquantified)
      ctx.fillStyle = 'rgba(56, 189, 248, 0.55)';
      ctx.beginPath();
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const rate = r.emission_auto;
        if (rate != null && rate >= 500) continue;
        const pt = projectSpherical(r.plume_latitude, r.plume_longitude, rLon, rLat, R, cx, cy);
        if (pt.z <= 0) continue; // Cull backside

        const depthScale = 0.7 + pt.z * 0.3;
        const rad = baseDotR * depthScale;
        ctx.moveTo(pt.x + rad, pt.y);
        ctx.arc(pt.x, pt.y, rad, 0, Math.PI * 2);
      }
      ctx.fill();

      // Batch 2: Moderate Leaks (500 - 2,500 kg/h)
      ctx.fillStyle = 'rgba(250, 204, 21, 0.78)';
      ctx.beginPath();
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const rate = r.emission_auto;
        if (rate == null || rate < 500 || rate >= 2500) continue;
        const pt = projectSpherical(r.plume_latitude, r.plume_longitude, rLon, rLat, R, cx, cy);
        if (pt.z <= 0) continue;

        const depthScale = 0.7 + pt.z * 0.3;
        const rad = (baseDotR + 0.6) * depthScale;
        ctx.moveTo(pt.x + rad, pt.y);
        ctx.arc(pt.x, pt.y, rad, 0, Math.PI * 2);
      }
      ctx.fill();

      // Batch 3: Super-Emitters (> 2,500 kg/h)
      // Halos
      ctx.fillStyle = 'rgba(245, 78, 0, 0.28)';
      ctx.beginPath();
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const rate = r.emission_auto;
        if (rate == null || rate < 2500) continue;
        const pt = projectSpherical(r.plume_latitude, r.plume_longitude, rLon, rLat, R, cx, cy);
        if (pt.z <= 0) continue;

        const rad = (baseDotR + 1.2) * 2.5;
        ctx.moveTo(pt.x + rad, pt.y);
        ctx.arc(pt.x, pt.y, rad, 0, Math.PI * 2);
      }
      ctx.fill();

      // Cores
      ctx.fillStyle = '#f54e00';
      ctx.beginPath();
      for (let i = 0; i < activeRecords.length; i++) {
        const r = activeRecords[i];
        const rate = r.emission_auto;
        if (rate == null || rate < 2500) continue;
        const pt = projectSpherical(r.plume_latitude, r.plume_longitude, rLon, rLat, R, cx, cy);
        if (pt.z <= 0) continue;

        const rad = baseDotR + 1.2;
        ctx.moveTo(pt.x + rad, pt.y);
        ctx.arc(pt.x, pt.y, rad, 0, Math.PI * 2);
      }
      ctx.fill();

      // 7. Targeting Reticle for Selected Plume
      if (selection?.plume_id) {
        const sPt = projectSpherical(
          selection.plume_latitude,
          selection.plume_longitude,
          rLon,
          rLat,
          R,
          cx,
          cy
        );
        if (sPt.z > 0) {
          // Outer animated reticle ring
          ctx.strokeStyle = '#f54e00';
          ctx.lineWidth = 1.8;
          ctx.beginPath();
          ctx.arc(sPt.x, sPt.y, 14, 0, Math.PI * 2);
          ctx.stroke();

          // 4 Crosshair notches
          ctx.beginPath();
          ctx.moveTo(sPt.x - 18, sPt.y);
          ctx.lineTo(sPt.x - 14, sPt.y);
          ctx.moveTo(sPt.x + 14, sPt.y);
          ctx.lineTo(sPt.x + 18, sPt.y);
          ctx.moveTo(sPt.x, sPt.y - 18);
          ctx.lineTo(sPt.x, sPt.y - 14);
          ctx.moveTo(sPt.x, sPt.y + 14);
          ctx.lineTo(sPt.x, sPt.y + 18);
          ctx.stroke();

          // Center solid pip
          ctx.fillStyle = '#ffffff';
          ctx.beginPath();
          ctx.arc(sPt.x, sPt.y, 3.5, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      ctx.restore();

      // 8. Globe Silhouette Edge Ring
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.42)';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.stroke();

      animId = requestAnimationFrame(render);
    }

    render();

    return () => {
      if (animId) cancelAnimationFrame(animId);
    };
  }, [activeRecords, selection]);

  // Handle Resize of canvas container
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = container.getBoundingClientRect();
      const cssW = Math.max(10, Math.floor(rect.width));
      const cssH = Math.max(10, Math.floor(rect.height));

      canvas.width = Math.floor(cssW * dpr);
      canvas.height = Math.floor(cssH * dpr);
      canvas.style.width = `${cssW}px`;
      canvas.style.height = `${cssH}px`;

      // Auto-fit radius to screen with generous proportion
      const fitR = Math.min(270, Math.max(180, Math.floor(Math.min(cssW, cssH) * 0.38)));
      stateRef.current.radius = fitR;
      stateRef.current.targetRadius = fitR;
      stateRef.current.dpr = dpr;
      stateRef.current.width = cssW;
      stateRef.current.height = cssH;
    };

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(container);
    return () => ro.disconnect();
  }, []);

  // Mouse & Touch Drag Controls
  function handleMouseDown(e) {
    const s = stateRef.current;
    s.isDragging = true;
    s.dragStart = { x: e.clientX, y: e.clientY };
    s.dragAngles = { lon: s.rotLon, lat: s.rotLat };
  }

  function handleMouseMove(e) {
    const s = stateRef.current;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    if (s.isDragging) {
      const dx = e.clientX - s.dragStart.x;
      const dy = e.clientY - s.dragStart.y;
      s.rotLon = s.dragAngles.lon - dx * 0.45;
      s.targetRotLon = s.rotLon;
      s.rotLat = Math.max(-75, Math.min(75, s.dragAngles.lat + dy * 0.45));
      s.targetRotLat = s.rotLat;
      return;
    }

    // Hover telemetry detection
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    const R = s.radius;

    let closest = null;
    let minDist = 20;

    for (let i = 0; i < activeRecords.length; i++) {
      const r = activeRecords[i];
      const pt = projectSpherical(r.plume_latitude, r.plume_longitude, s.rotLon, s.rotLat, R, cx, cy);
      if (pt.z <= 0) continue;

      const dist = Math.hypot(pt.x - mouseX, pt.y - mouseY);
      if (dist < minDist) {
        minDist = dist;
        closest = { record: r, x: mouseX, y: mouseY };
      }
    }

    setHovered(closest);
    canvas.style.cursor = closest ? 'crosshair' : 'grab';
  }

  function handleMouseUp() {
    stateRef.current.isDragging = false;
  }

  function handleClick(e) {
    const s = stateRef.current;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    const R = s.radius;

    let closest = null;
    let minDist = 22;

    for (let i = 0; i < activeRecords.length; i++) {
      const r = activeRecords[i];
      const pt = projectSpherical(r.plume_latitude, r.plume_longitude, s.rotLon, s.rotLat, R, cx, cy);
      if (pt.z <= 0) continue;

      const dist = Math.hypot(pt.x - mouseX, pt.y - mouseY);
      if (dist < minDist) {
        minDist = dist;
        closest = r;
      }
    }

    if (closest) {
      onSelect(closest);
    }
  }

  // Non-passive wheel and gesture listener to prevent browser page zooming or scrolling
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const onWheel = (e) => {
      // Unconditionally prevent default so browser does not zoom (ctrlKey / trackpad pinch) or scroll the page
      e.preventDefault();
      e.stopPropagation();

      const s = stateRef.current;
      if (e.ctrlKey || e.metaKey) {
        // Trackpad pinch-to-zoom on macOS Chrome or Firefox
        const zoomStep = -e.deltaY * 0.9;
        s.targetRadius = Math.max(140, Math.min(380, s.targetRadius + zoomStep));
      } else {
        // Standard mouse wheel or two-finger scroll
        const zoomStep = e.deltaY > 0 ? -22 : 22;
        s.targetRadius = Math.max(140, Math.min(380, s.targetRadius + zoomStep));
      }
    };

    let gestureStartRadius = 210;
    const onGestureStart = (e) => {
      e.preventDefault();
      e.stopPropagation();
      gestureStartRadius = stateRef.current.radius;
    };

    const onGestureChange = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const newR = Math.max(140, Math.min(380, gestureStartRadius * e.scale));
      stateRef.current.radius = newR;
      stateRef.current.targetRadius = newR;
    };

    const onGestureEnd = (e) => {
      e.preventDefault();
      e.stopPropagation();
    };

    let touchStartDist = 0;
    let touchStartRadius = 210;

    const onTouchStart = (e) => {
      if (e.touches.length === 2) {
        e.preventDefault();
        const t1 = e.touches[0];
        const t2 = e.touches[1];
        touchStartDist = Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY);
        touchStartRadius = stateRef.current.radius;
      }
    };

    const onTouchMove = (e) => {
      if (e.touches.length === 2 && touchStartDist > 0) {
        e.preventDefault();
        const t1 = e.touches[0];
        const t2 = e.touches[1];
        const dist = Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY);
        const scale = dist / touchStartDist;
        const newR = Math.max(140, Math.min(380, touchStartRadius * scale));
        stateRef.current.radius = newR;
        stateRef.current.targetRadius = newR;
      }
    };

    const onTouchEnd = (e) => {
      if (e.touches.length < 2) {
        touchStartDist = 0;
      }
    };

    container.addEventListener('wheel', onWheel, { passive: false, capture: true });
    container.addEventListener('gesturestart', onGestureStart, { passive: false, capture: true });
    container.addEventListener('gesturechange', onGestureChange, { passive: false, capture: true });
    container.addEventListener('gestureend', onGestureEnd, { passive: false, capture: true });
    container.addEventListener('touchstart', onTouchStart, { passive: false });
    container.addEventListener('touchmove', onTouchMove, { passive: false });
    container.addEventListener('touchend', onTouchEnd);

    return () => {
      container.removeEventListener('wheel', onWheel, { capture: true });
      container.removeEventListener('gesturestart', onGestureStart, { capture: true });
      container.removeEventListener('gesturechange', onGestureChange, { capture: true });
      container.removeEventListener('gestureend', onGestureEnd, { capture: true });
      container.removeEventListener('touchstart', onTouchStart);
      container.removeEventListener('touchmove', onTouchMove);
      container.removeEventListener('touchend', onTouchEnd);
    };
  }, []);

  // Jump to specific basin
  function jumpToBasin(basin) {
    const s = stateRef.current;
    s.targetRotLon = basin.lon;
    s.targetRotLat = basin.lat;
    s.targetRadius = basin.zoomR;
  }

  return (
    <div className="globe-shell" ref={containerRef}>
      <canvas
        ref={canvasRef}
        className="globe-canvas"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onClick={handleClick}
      />

      {/* Basin Jump Bar */}
      <div className="basin-jump-bar" aria-label="3D Globe Basin Shortcuts">
        <span className="basin-jump-label">
          <Compass size={11} /> 3D Basins:
        </span>
        {BASINS.map(b => (
          <button
            key={b.name}
            type="button"
            className="basin-jump-btn"
            onClick={() => jumpToBasin(b)}
          >
            {b.name}
          </button>
        ))}
      </div>

      {/* Top Severity Filter & 2D/3D Switcher */}
      <div className="map-top-actions">
        {setViewType && (
          <button
            type="button"
            className="dimension-switch-btn"
            onClick={() => setViewType('map')}
            title="Switch to 2D Flat Map"
          >
            <Map size={12} />
            <span>2D Map</span>
          </button>
        )}

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
      </div>

      {/* 3D Navigation Controls */}
      <div className="globe-controls">
        <button
          type="button"
          title={autoRotate ? 'Pause auto-rotation' : 'Start auto-rotation'}
          aria-label={autoRotate ? 'Pause spin' : 'Auto-rotate'}
          onClick={() => setAutoRotate(v => !v)}
        >
          {autoRotate ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <button
          type="button"
          title="Zoom In"
          aria-label="Zoom in"
          onClick={() => {
            stateRef.current.targetRadius = Math.min(340, stateRef.current.radius + 30);
          }}
        >
          <Plus size={16} />
        </button>
        <button
          type="button"
          title="Zoom Out"
          aria-label="Zoom out"
          onClick={() => {
            stateRef.current.targetRadius = Math.max(140, stateRef.current.radius - 30);
          }}
        >
          <Minus size={16} />
        </button>
        <button
          type="button"
          title="Reset 3D View"
          aria-label="Reset view"
          onClick={() => {
            const s = stateRef.current;
            s.targetRotLon = -30;
            s.targetRotLat = 25;
            s.targetRadius = 210;
          }}
        >
          <Focus size={16} />
        </button>
      </div>

      {/* Telemetry Hover Tooltip Badge */}
      {hovered && (
        <div
          className="map-telemetry-tooltip"
          style={{
            left: `${Math.min(hovered.x + 14, (containerRef.current?.clientWidth || 800) - 220)}px`,
            top: `${Math.max(14, hovered.y - 48)}px`
          }}
        >
          <div className="tooltip-title">
            <Crosshair size={11} />
            <span>{hovered.record.place || hovered.record.region || 'Satellite observation'}</span>
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

      {/* 3D Globe Legend */}
      <div className="map-legend">
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
        <div className="legend-hint">Drag to orbit Earth · Scroll to zoom · Click to inspect</div>
      </div>
    </div>
  );
}
