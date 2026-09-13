import React, { useEffect, useRef, useState, useMemo } from 'react';
import {
  Plus,
  Minus,
  Focus,
  Crosshair,
  Play,
  Pause,
  Compass,
  Map as MapIcon,
  Building2,
  Sliders,
  Sparkles,
  Maximize2,
  Minimize2,
  ChevronDown
} from 'lucide-react';
import { fmt, compact, logoTicker } from '../utils/formatters';
import { sectorColors } from '../constants';
import { CompanyLogo } from '../components/CompanyLogo';
import hqMap from '../constants/hq.json';
import worldBorders from '../constants/world_borders.json';

const logoCache = new Map();

function getCompanyLogo(ticker) {
  if (!ticker) return null;
  const key = logoTicker(ticker);
  let entry = logoCache.get(key);
  if (!entry) {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    entry = { img, loaded: false, failed: false };
    img.onload = () => {
      entry.loaded = true;
    };
    img.onerror = () => {
      entry.failed = true;
    };
    img.src = `https://images.financialmodelingprep.com/symbol/${encodeURIComponent(key)}.png`;
    logoCache.set(key, entry);
  }
  return entry;
}

function getCompanyHq(ticker) {
  if (!ticker) return null;
  const t = ticker.toUpperCase().trim();
  if (hqMap[t]) return hqMap[t];
  const tDash = t.replace(/\./g, '-');
  if (hqMap[tDash]) return hqMap[tDash];
  const tDot = t.replace(/-/g, '.');
  if (hqMap[tDot]) return hqMap[tDot];
  if (t === 'MRSH') return hqMap['MMC'];
  if (t === 'NXPI') return hqMap['NXP'];
  return null;
}

const BASINS = [
  { name: 'Permian Basin (USA)', lat: 31.8, lon: -102.3, zoomR: 240 },
  { name: 'Caspian / Central Asia', lat: 39.5, lon: 54.5, zoomR: 240 },
  { name: 'US Gulf Coast', lat: 29.8, lon: -94.5, zoomR: 250 },
  { name: 'Appalachian', lat: 40.2, lon: -80.2, zoomR: 250 }
];

// Draw vector polyline on sphere with horizon limb clipping
function drawPolyline(ctx, points, rLon, rLat, R, cx, cy) {
  let isDrawing = false;
  let prevPt = null;
  let prevCoord = null;

  for (let i = 0; i < points.length; i++) {
    const coord = points[i];
    const currPt = projectSpherical(coord[0], coord[1], rLon, rLat, R, cx, cy);

    if (i === 0) {
      if (currPt.z > 0) {
        ctx.moveTo(currPt.x, currPt.y);
        isDrawing = true;
      }
    } else {
      if (prevPt.z > 0 && currPt.z > 0) {
        if (!isDrawing) {
          ctx.moveTo(prevPt.x, prevPt.y);
          isDrawing = true;
        }
        ctx.lineTo(currPt.x, currPt.y);
      } else if (prevPt.z > 0 && currPt.z <= 0) {
        const t = prevPt.z / (prevPt.z - currPt.z);
        const latH = prevCoord[0] + (coord[0] - prevCoord[0]) * t;
        let dLon = coord[1] - prevCoord[1];
        if (dLon > 180) dLon -= 360;
        else if (dLon < -180) dLon += 360;
        const lonH = prevCoord[1] + dLon * t;
        const ptH = projectSpherical(latH, lonH, rLon, rLat, R, cx, cy);
        if (isDrawing) ctx.lineTo(ptH.x, ptH.y);
        isDrawing = false;
      } else if (prevPt.z <= 0 && currPt.z > 0) {
        const t = currPt.z / (currPt.z - prevPt.z);
        const latH = coord[0] + (prevCoord[0] - coord[0]) * t;
        let dLon = prevCoord[1] - coord[1];
        if (dLon > 180) dLon -= 360;
        else if (dLon < -180) dLon += 360;
        const lonH = coord[1] + dLon * t;
        const ptH = projectSpherical(latH, lonH, rLon, rLat, R, cx, cy);
        ctx.moveTo(ptH.x, ptH.y);
        ctx.lineTo(currPt.x, currPt.y);
        isDrawing = true;
      } else {
        isDrawing = false;
      }
    }
    prevPt = currPt;
    prevCoord = coord;
  }
}

// Draw land polygon ring with horizon limb clipping
function drawLandRing(ctx, ring, rLon, rLat, R, cx, cy) {
  if (!ring || ring.length < 3) return;

  let anyFront = false;
  let allFront = true;
  for (let i = 0; i < ring.length; i++) {
    const pt = projectSpherical(ring[i][0], ring[i][1], rLon, rLat, R, cx, cy);
    if (pt.z > 0) anyFront = true;
    else allFront = false;
  }
  if (!anyFront) return;

  ctx.beginPath();
  if (allFront) {
    for (let i = 0; i < ring.length; i++) {
      const pt = projectSpherical(ring[i][0], ring[i][1], rLon, rLat, R, cx, cy);
      if (i === 0) ctx.moveTo(pt.x, pt.y);
      else ctx.lineTo(pt.x, pt.y);
    }
    ctx.closePath();
    ctx.fill();
    return;
  }

  let isDrawing = false;
  let prevPt = null;
  let prevCoord = null;
  let horizonExitPt = null;

  for (let i = 0; i < ring.length; i++) {
    const coord = ring[i];
    const currPt = projectSpherical(coord[0], coord[1], rLon, rLat, R, cx, cy);

    if (i === 0) {
      if (currPt.z > 0) {
        ctx.moveTo(currPt.x, currPt.y);
        isDrawing = true;
      }
    } else {
      if (prevPt.z > 0 && currPt.z > 0) {
        if (!isDrawing) {
          ctx.moveTo(prevPt.x, prevPt.y);
          isDrawing = true;
        }
        ctx.lineTo(currPt.x, currPt.y);
      } else if (prevPt.z > 0 && currPt.z <= 0) {
        const t = prevPt.z / (prevPt.z - currPt.z);
        const latH = prevCoord[0] + (coord[0] - prevCoord[0]) * t;
        let dLon = coord[1] - prevCoord[1];
        if (dLon > 180) dLon -= 360;
        else if (dLon < -180) dLon += 360;
        const lonH = prevCoord[1] + dLon * t;
        const ptH = projectSpherical(latH, lonH, rLon, rLat, R, cx, cy);
        if (isDrawing) ctx.lineTo(ptH.x, ptH.y);
        horizonExitPt = ptH;
        isDrawing = false;
      } else if (prevPt.z <= 0 && currPt.z > 0) {
        const t = currPt.z / (currPt.z - prevPt.z);
        const latH = coord[0] + (prevCoord[0] - coord[0]) * t;
        let dLon = prevCoord[1] - coord[1];
        if (dLon > 180) dLon -= 360;
        else if (dLon < -180) dLon += 360;
        const lonH = coord[1] + dLon * t;
        const ptH = projectSpherical(latH, lonH, rLon, rLat, R, cx, cy);

        if (horizonExitPt) {
          const a1 = Math.atan2(horizonExitPt.y - cy, horizonExitPt.x - cx);
          const a2 = Math.atan2(ptH.y - cy, ptH.x - cx);
          ctx.arc(cx, cy, R, a1, a2);
          horizonExitPt = null;
        } else {
          ctx.moveTo(ptH.x, ptH.y);
        }
        ctx.lineTo(currPt.x, currPt.y);
        isDrawing = true;
      }
    }
    prevPt = currPt;
    prevCoord = coord;
  }
  ctx.closePath();
  ctx.fill();
}

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
  companies = [],
  selection,
  onSelect,
  severity,
  setSeverity,
  viewType,
  setViewType
}) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);

  const [showHqLogos, setShowHqLogos] = useState(true);
  const [topCount, setTopCount] = useState(15);
  const [hqMetric, setHqMetric] = useState('emissions'); // 'emissions' | 'market_cap'
  const [hoveredCompany, setHoveredCompany] = useState(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const toggleFullscreen = () => {
    const el = containerRef.current;
    if (!el) return;

    if (!document.fullscreenElement && !isFullscreen) {
      if (el.requestFullscreen) {
        el.requestFullscreen().catch(() => {
          setIsFullscreen(true);
        });
      } else if (el.webkitRequestFullscreen) {
        el.webkitRequestFullscreen();
      } else {
        setIsFullscreen(true);
      }
    } else {
      if (document.fullscreenElement) {
        if (document.exitFullscreen) {
          document.exitFullscreen().catch(() => {});
        } else if (document.webkitExitFullscreen) {
          document.webkitExitFullscreen();
        }
      }
      setIsFullscreen(false);
    }
  };

  useEffect(() => {
    const onFullscreenChange = () => {
      const isFs = Boolean(
        document.fullscreenElement === containerRef.current ||
        document.webkitFullscreenElement === containerRef.current
      );
      setIsFullscreen(isFs);
    };

    document.addEventListener('fullscreenchange', onFullscreenChange);
    document.addEventListener('webkitfullscreenchange', onFullscreenChange);

    const onKey = (e) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', onKey);

    return () => {
      document.removeEventListener('fullscreenchange', onFullscreenChange);
      document.removeEventListener('webkitfullscreenchange', onFullscreenChange);
      window.removeEventListener('keydown', onKey);
    };
  }, [isFullscreen]);

  // Top companies sorted by metric and geocoded with cluster dispersion
  const processedTopCompanies = useMemo(() => {
    if (!showHqLogos || !companies || companies.length === 0) return [];

    const sorted = [...companies].sort((a, b) => {
      if (hqMetric === 'emissions') {
        return (b.scope1_t ?? -Infinity) - (a.scope1_t ?? -Infinity);
      }
      return (b.market_cap_musd ?? -Infinity) - (a.market_cap_musd ?? -Infinity);
    });

    const list = [];
    const coordCounts = new Map();

    for (let i = 0; i < sorted.length; i++) {
      if (list.length >= topCount) break;
      const c = sorted[i];
      const hq = getCompanyHq(c.ticker);
      if (!hq || hq.lat == null || hq.lon == null) continue;

      // Trigger logo preload
      getCompanyLogo(c.ticker);

      const coordKey = `${hq.lat.toFixed(2)},${hq.lon.toFixed(2)}`;
      const count = coordCounts.get(coordKey) || 0;
      coordCounts.set(coordKey, count + 1);

      let dispLat = hq.lat;
      let dispLon = hq.lon;
      if (count > 0) {
        const angle = count * 2.4;
        const radius = 0.9 * Math.sqrt(count);
        dispLat += Math.sin(angle) * radius;
        dispLon += (Math.cos(angle) * radius) / Math.cos((hq.lat * Math.PI) / 180 || 1);
      }

      list.push({
        ...c,
        hq,
        lat: dispLat,
        lon: dispLon,
        baseLat: hq.lat,
        baseLon: hq.lon,
        rank: list.length + 1
      });
    }

    return list;
  }, [companies, showHqLogos, topCount, hqMetric]);

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
    height: 500,
    showHqLogos: true,
    topCompanies: [],
    hoveredCompany: null,
    hqMetric: 'emissions'
  });

  const [autoRotate, setAutoRotate] = useState(true);
  const [hovered, setHovered] = useState(null);

  stateRef.current.autoRotate = autoRotate;
  stateRef.current.showHqLogos = showHqLogos;
  stateRef.current.topCompanies = processedTopCompanies;
  stateRef.current.hoveredCompany = hoveredCompany;
  stateRef.current.hqMetric = hqMetric;

  // When external selection changes, smoothly rotate to selected plume or company
  useEffect(() => {
    if (selection?.plume_id) {
      stateRef.current.targetRotLon = selection.plume_longitude;
      stateRef.current.targetRotLat = selection.plume_latitude;
      stateRef.current.targetRadius = Math.max(stateRef.current.radius, 240);
    } else if (selection?.ticker) {
      const hq = getCompanyHq(selection.ticker);
      if (hq) {
        stateRef.current.targetRotLon = hq.lon;
        stateRef.current.targetRotLat = hq.lat;
        stateRef.current.targetRadius = Math.max(stateRef.current.radius, 240);
      }
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

      // 5. Draw Continents & Well-Defined World Boundaries
      // 5a. Continent landmass fills
      ctx.fillStyle = 'rgba(23, 38, 51, 0.88)';
      if (worldBorders && worldBorders.land) {
        for (let p = 0; p < worldBorders.land.length; p++) {
          drawLandRing(ctx, worldBorders.land[p], rLon, rLat, R, cx, cy);
        }
      }

      // 5b. Internal Country Borders (well defined diplomatic boundaries between sovereign states)
      if (worldBorders && worldBorders.borders) {
        ctx.save();
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.46)';
        ctx.lineWidth = 0.85;
        ctx.setLineDash([2, 3]);
        ctx.beginPath();
        for (let i = 0; i < worldBorders.borders.length; i++) {
          drawPolyline(ctx, worldBorders.borders[i], rLon, rLat, R, cx, cy);
        }
        ctx.stroke();
        ctx.restore();
      }

      // 5c. Continental Coastlines (well defined luminous continent perimeters & islands)
      if (worldBorders && worldBorders.coastlines) {
        ctx.save();
        ctx.strokeStyle = '#38bdf8';
        ctx.lineWidth = 1.25;
        ctx.shadowColor = 'rgba(56, 189, 248, 0.45)';
        ctx.shadowBlur = 4;
        ctx.beginPath();
        for (let i = 0; i < worldBorders.coastlines.length; i++) {
          drawPolyline(ctx, worldBorders.coastlines[i], rLon, rLat, R, cx, cy);
        }
        ctx.stroke();
        ctx.restore();
      }

      // 5d. Atmospheric Terminator & Rim Light (planetary spherical depth)
      const rimGrad = ctx.createRadialGradient(cx, cy, R * 0.86, cx, cy, R);
      rimGrad.addColorStop(0, 'rgba(56, 189, 248, 0)');
      rimGrad.addColorStop(0.85, 'rgba(56, 189, 248, 0.12)');
      rimGrad.addColorStop(1, 'rgba(56, 189, 248, 0.35)');
      ctx.fillStyle = rimGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
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

      // 9. Company HQ Logos (when enabled)
      const sHq = s.showHqLogos;
      const topComps = s.topCompanies || [];
      if (sHq && topComps.length > 0) {
        const visibleHqs = [];
        const elevatedR = R * 1.055;

        for (let i = 0; i < topComps.length; i++) {
          const c = topComps[i];
          const surfPt = projectSpherical(c.baseLat, c.baseLon, rLon, rLat, R, cx, cy);
          const pinPt = projectSpherical(c.lat, c.lon, rLon, rLat, elevatedR, cx, cy);

          // Cull backside if pin is on far side of Earth
          if (pinPt.z > 0.05) {
            visibleHqs.push({
              company: c,
              surfPt,
              pinPt,
              z: pinPt.z
            });
          }
        }

        // Sort back-to-front so closer foreground logos render over background ones
        visibleHqs.sort((a, b) => a.z - b.z);

        for (let i = 0; i < visibleHqs.length; i++) {
          const { company: c, surfPt, pinPt, z } = visibleHqs[i];
          const isHovered = s.hoveredCompany?.company?.ticker === c.ticker;
          const sectorColor = sectorColors[c.gics_sector] || '#38bdf8';
          const depthScale = Math.max(0.68, Math.min(1.22, 0.72 + z * 0.45));
          const badgeR = Math.round((isHovered ? 16 : 12.5) * depthScale);

          // 1. Surface anchor beacon dot
          ctx.beginPath();
          ctx.arc(surfPt.x, surfPt.y, 2.2 * depthScale, 0, Math.PI * 2);
          ctx.fillStyle = sectorColor;
          ctx.fill();

          // 2. Surface anchor halo ring
          ctx.beginPath();
          ctx.arc(surfPt.x, surfPt.y, 5 * depthScale, 0, Math.PI * 2);
          ctx.strokeStyle = `${sectorColor}55`;
          ctx.lineWidth = 1;
          ctx.stroke();

          // 3. Hairline stem connecting surface to floating logo badge
          ctx.beginPath();
          ctx.moveTo(surfPt.x, surfPt.y);
          ctx.lineTo(pinPt.x, pinPt.y);
          ctx.strokeStyle = isHovered ? 'rgba(56, 189, 248, 0.95)' : 'rgba(255, 255, 255, 0.45)';
          ctx.lineWidth = isHovered ? 1.8 : 1;
          ctx.stroke();

          // 4. Outer badge border with glow
          ctx.save();
          ctx.beginPath();
          ctx.arc(pinPt.x, pinPt.y, badgeR + 2, 0, Math.PI * 2);
          ctx.fillStyle = isHovered ? '#38bdf8' : sectorColor;
          ctx.shadowColor = 'rgba(0, 0, 0, 0.65)';
          ctx.shadowBlur = isHovered ? 10 : 5;
          ctx.fill();

          // 5. Inner circular white disc
          ctx.beginPath();
          ctx.arc(pinPt.x, pinPt.y, badgeR, 0, Math.PI * 2);
          ctx.fillStyle = '#ffffff';
          ctx.fill();

          // 6. Draw logo image if loaded
          const entry = getCompanyLogo(c.ticker);
          if (entry && entry.loaded && !entry.failed) {
            ctx.save();
            ctx.beginPath();
            ctx.arc(pinPt.x, pinPt.y, badgeR - 1, 0, Math.PI * 2);
            ctx.clip();
            const pad = 2;
            const logoW = (badgeR - pad) * 2;
            ctx.drawImage(entry.img, pinPt.x - badgeR + pad, pinPt.y - badgeR + pad, logoW, logoW);
            ctx.restore();
          } else {
            // Ticker monogram fallback
            ctx.fillStyle = '#0f172a';
            ctx.font = `700 ${Math.max(8, Math.round(9 * depthScale))}px var(--font-mono, monospace)`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(c.ticker.slice(0, 4), pinPt.x, pinPt.y);
          }
          ctx.restore();

          // 7. Hover ticker pill tag
          if (isHovered) {
            const label = c.ticker;
            ctx.font = '600 10px var(--font-mono, monospace)';
            const textW = ctx.measureText(label).width;
            const pillW = textW + 12;
            const pillH = 18;
            const pillY = pinPt.y + badgeR + 5;

            ctx.fillStyle = 'rgba(15, 23, 42, 0.95)';
            ctx.beginPath();
            if (ctx.roundRect) {
              ctx.roundRect(pinPt.x - pillW / 2, pillY, pillW, pillH, 4);
            } else {
              ctx.rect(pinPt.x - pillW / 2, pillY, pillW, pillH);
            }
            ctx.fill();
            ctx.strokeStyle = '#38bdf8';
            ctx.lineWidth = 1;
            ctx.stroke();

            ctx.fillStyle = '#ffffff';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, pinPt.x, pillY + pillH / 2);
          }
        }
      }

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

      // Auto-fit radius to screen with generous proportion (scales dynamically in fullscreen)
      const fitR = Math.max(180, Math.floor(Math.min(cssW, cssH) * 0.38));
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

    // 1. Company HQ logo hover detection
    if (s.showHqLogos && s.topCompanies && s.topCompanies.length > 0) {
      let closestCompany = null;
      let minCompDist = 18;
      const elevatedR = R * 1.055;

      for (let i = 0; i < s.topCompanies.length; i++) {
        const c = s.topCompanies[i];
        const pinPt = projectSpherical(c.lat, c.lon, s.rotLon, s.rotLat, elevatedR, cx, cy);
        if (pinPt.z <= 0.05) continue;

        const dist = Math.hypot(pinPt.x - mouseX, pinPt.y - mouseY);
        if (dist < minCompDist) {
          minCompDist = dist;
          closestCompany = { company: c, x: pinPt.x, y: pinPt.y, screenX: mouseX, screenY: mouseY };
        }
      }

      if (closestCompany) {
        setHoveredCompany(closestCompany);
        setHovered(null);
        canvas.style.cursor = 'pointer';
        return;
      } else {
        setHoveredCompany(null);
      }
    }

    // 2. Plume hover telemetry detection
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

  function handleMouseLeave() {
    stateRef.current.isDragging = false;
    setHovered(null);
    setHoveredCompany(null);
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

    // 1. Check click on company HQ pin first
    if (s.showHqLogos && s.topCompanies && s.topCompanies.length > 0) {
      const elevatedR = R * 1.055;
      for (let i = 0; i < s.topCompanies.length; i++) {
        const c = s.topCompanies[i];
        const pinPt = projectSpherical(c.lat, c.lon, s.rotLon, s.rotLat, elevatedR, cx, cy);
        if (pinPt.z <= 0.05) continue;

        const dist = Math.hypot(pinPt.x - mouseX, pinPt.y - mouseY);
        if (dist < 20) {
          s.targetRotLon = c.hq.lon;
          s.targetRotLat = c.hq.lat;
          s.targetRadius = Math.max(s.radius, 240);
          onSelect(c);
          return;
        }
      }
    }

    // 2. Check click on plume record
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
      const baseR = Math.max(180, Math.floor(Math.min(s.width || 800, s.height || 500) * 0.38));
      const minR = Math.max(90, Math.floor(baseR * 0.4));
      const maxR = Math.max(500, Math.floor(baseR * 2.5));

      if (e.ctrlKey || e.metaKey) {
        // Trackpad pinch-to-zoom on macOS Chrome or Firefox
        const zoomStep = -e.deltaY * 0.8;
        s.targetRadius = Math.max(minR, Math.min(maxR, s.targetRadius + zoomStep));
      } else {
        // Standard mouse wheel or two-finger trackpad scroll
        let dy = e.deltaY;
        if (e.deltaMode === 1) dy *= 20;
        else if (e.deltaMode === 2) dy *= 60;
        const zoomStep = -dy * 0.35;
        s.targetRadius = Math.max(minR, Math.min(maxR, s.targetRadius + zoomStep));
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
      const s = stateRef.current;
      const baseR = Math.max(180, Math.floor(Math.min(s.width || 800, s.height || 500) * 0.38));
      const minR = Math.max(90, Math.floor(baseR * 0.4));
      const maxR = Math.max(500, Math.floor(baseR * 2.5));
      const newR = Math.max(minR, Math.min(maxR, gestureStartRadius * e.scale));
      s.radius = newR;
      s.targetRadius = newR;
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
    <div className={`globe-shell ${isFullscreen ? 'is-fullscreen' : ''}`} ref={containerRef}>
      <canvas
        ref={canvasRef}
        className="globe-canvas"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onClick={handleClick}
      />

      {/* Basin Quick Jump Dropdown */}
      <div className="basin-jump-bar">
        <Compass size={12} className="basin-jump-icon" />
        <select
          className="basin-select"
          aria-label="Jump to emission basin"
          defaultValue=""
          onChange={e => {
            const b = BASINS.find(x => x.name === e.target.value);
            if (b) jumpToBasin(b);
            e.target.value = '';
          }}
        >
          <option value="" disabled>Basins...</option>
          {BASINS.map(b => (
            <option key={b.name} value={b.name}>
              {b.name}
            </option>
          ))}
        </select>
        <ChevronDown size={11} className="basin-chevron" />
      </div>

      {/* Top Actions: 2D Map Switcher, HQ Logos Toggle & Severity Filter */}
      <div className="map-top-actions">
        {setViewType && (
          <button
            type="button"
            className="dimension-switch-btn"
            onClick={() => setViewType('map')}
            title="Switch to 2D Flat Map"
          >
            <MapIcon size={12} />
            <span>2D Map</span>
          </button>
        )}

        <button
          type="button"
          className={`dimension-switch-btn ${showHqLogos ? 'active-logo-toggle' : ''}`}
          onClick={() => setShowHqLogos(v => !v)}
          title="Toggle Company Headquarters Logos"
        >
          <Building2 size={12} />
          <span>HQ Logos</span>
        </button>

        <div className="severity-filter" role="group" aria-label="Emission severity filter">
          <button
            type="button"
            className={severity === 'all' ? 'active' : ''}
            onClick={() => setSeverity('all')}
            title={`All ${compact(records.length)} observations`}
          >
            All
          </button>
          <button
            type="button"
            className={severity === 'severe' ? 'active' : ''}
            onClick={() => setSeverity('severe')}
            title="Filter to rates > 1,000 kg/h"
          >
            &gt; 1k
          </button>
          <button
            type="button"
            className={severity === 'super' ? 'active' : ''}
            onClick={() => setSeverity('super')}
            title="Filter to super-emitters > 2,500 kg/h"
          >
            Super
          </button>
        </div>
      </div>

      {/* Company HQ Logos Floating Control Panel */}
      {showHqLogos && (
        <div className="globe-hq-panel" aria-label="Company HQ Controls">
          <div className="hq-panel-header">
            <span className="hq-panel-title">
              <Building2 size={12} /> Top {topCount} HQs
            </span>
            <span className="hq-panel-count">
              {processedTopCompanies.length} visible
            </span>
          </div>

          <div className="hq-slider-group">
            <div className="hq-slider-labels">
              <span>Show Top</span>
              <strong>{topCount} companies</strong>
            </div>
            <input
              type="range"
              min="5"
              max="50"
              step="5"
              value={topCount}
              onChange={e => setTopCount(Number(e.target.value))}
              aria-label="Number of top companies to show"
            />
            <div className="hq-preset-pills">
              {[5, 10, 20, 30, 50].map(n => (
                <button
                  key={n}
                  type="button"
                  className={topCount === n ? 'active' : ''}
                  onClick={() => setTopCount(n)}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          <div className="hq-metric-toggle" role="group" aria-label="Rank companies by">
            <button
              type="button"
              className={hqMetric === 'emissions' ? 'active' : ''}
              onClick={() => setHqMetric('emissions')}
              title="Rank by Scope 1 Direct Emissions"
            >
              Emissions
            </button>
            <button
              type="button"
              className={hqMetric === 'market_cap' ? 'active' : ''}
              onClick={() => setHqMetric('market_cap')}
              title="Rank by Market Capitalization"
            >
              Market Cap
            </button>
          </div>
        </div>
      )}

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
        <button
          type="button"
          title={isFullscreen ? 'Exit Full Screen' : 'Full Screen'}
          aria-label={isFullscreen ? 'Exit Full Screen' : 'Full Screen'}
          onClick={toggleFullscreen}
        >
          {isFullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
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

      {/* Company HQ Tooltip */}
      {hoveredCompany && (
        <div
          className="globe-company-tooltip"
          style={{
            left: `${Math.min(hoveredCompany.x + 16, (containerRef.current?.clientWidth || 800) - 270)}px`,
            top: `${Math.max(14, Math.min(hoveredCompany.y - 48, (containerRef.current?.clientHeight || 500) - 160))}px`
          }}
        >
          <div className="company-tooltip-header">
            <CompanyLogo company={hoveredCompany.company} size="small" onDark />
            <div className="company-tooltip-names">
              <span className="company-tooltip-title">{hoveredCompany.company.company_name}</span>
              <span className="company-tooltip-ticker">{hoveredCompany.company.ticker}</span>
            </div>
          </div>

          <div className="company-tooltip-meta">
            <span
              className="sector-pill"
              style={{
                color: sectorColors[hoveredCompany.company.gics_sector] || '#38bdf8'
              }}
            >
              {hoveredCompany.company.gics_sector}
            </span>
            <span className="location-pill">
              {hoveredCompany.company.hq.city}
              {hoveredCompany.company.hq.state ? `, ${hoveredCompany.company.hq.state}` : ''}
              {hoveredCompany.company.hq.country && hoveredCompany.company.hq.country !== 'United States'
                ? `, ${hoveredCompany.company.hq.country}`
                : ''}
            </span>
          </div>

          <div className="company-tooltip-stat">
            <span className="stat-label">
              {hqMetric === 'emissions' ? 'Scope 1 Emissions' : 'Market Cap'}
            </span>
            <strong className="stat-value">
              {hqMetric === 'emissions'
                ? hoveredCompany.company.scope1_t != null
                  ? `${compact(hoveredCompany.company.scope1_t)} tCO2`
                  : 'Unmeasured'
                : hoveredCompany.company.market_cap_musd != null
                ? `$${compact(hoveredCompany.company.market_cap_musd * 1000000)}`
                : 'N/A'}
            </strong>
          </div>

          <div className="company-tooltip-hint">Click to inspect company dossier</div>
        </div>
      )}

      {/* 3D Globe Legend */}
      <div className="map-legend">
        {showHqLogos && (
          <div className="legend-item">
            <i className="dot-hq" />
            <span>Company HQ ({topCount} displayed)</span>
          </div>
        )}
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
        <div className="legend-hint">Drag to orbit Earth · Scroll to zoom · Click pin to inspect</div>
      </div>
    </div>
  );
}
