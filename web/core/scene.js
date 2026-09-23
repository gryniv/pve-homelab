// Landscape (time of day), weather look and the canvas weather effects.

import { $ } from './ui.js';

const root = document.body;
const NS = 'http://www.w3.org/2000/svg';
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const CEL = { night: [1180, 190, 34, 1], dawn: [1220, 560, 62, 0], day: [1150, 170, 46, 0], dusk: [380, 560, 66, 0] };
const CLOUDY = ['overcast', 'rain', 'thunder', 'snow', 'fog'];

const state = { kind: 'partly', react: true, byTime: true, fx: true, running: false };

export function isNight() {
  return ['night', 'dusk'].includes(root.dataset.tod);
}

function currentTod() {
  if (!state.byTime) return 'night';
  const h = new Date().getHours();
  return h < 5 || h >= 21 ? 'night' : h < 9 ? 'dawn' : h < 18 ? 'day' : 'dusk';
}

export function refreshSky() {
  const tod = currentTod();
  root.dataset.tod = tod;
  const [cx, cy, r, starsOn] = CEL[tod];
  $('#cel').setAttribute('cx', cx); $('#cel').setAttribute('cy', cy); $('#cel').setAttribute('r', r);
  $('#celglow').setAttribute('cx', cx); $('#celglow').setAttribute('cy', cy); $('#celglow').setAttribute('r', r * 3.8);
  const cloudy = CLOUDY.includes(root.dataset.wx);
  $('#stars').style.opacity = cloudy ? 0 : starsOn ? 1 : tod === 'dusk' ? 0.35 : 0;
}

export function configure({ kind, react, byTime, fx }) {
  if (kind !== undefined) state.kind = kind;
  if (react !== undefined) state.react = react;
  if (byTime !== undefined) state.byTime = byTime;
  if (fx !== undefined) state.fx = fx;
  const shown = state.react ? state.kind : 'partly';
  const changed = root.dataset.wx !== shown;
  root.dataset.wx = shown;
  refreshSky();
  if (changed && state.running) restart();
}

function build() {
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const stars = $('#stars');
  for (let i = 0; i < 120; i++) {
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', (rnd() * 1600).toFixed(0)); c.setAttribute('cy', (rnd() * 520).toFixed(0));
    c.setAttribute('r', (rnd() * 1.4 + 0.4).toFixed(1)); c.setAttribute('fill', '#fff');
    c.setAttribute('class', 'star'); c.style.animationDelay = (-rnd() * 4).toFixed(1) + 's';
    stars.appendChild(c);
  }
  let d = '';
  for (let x = 0; x < 1600; x += 14 + rnd() * 22) {
    const base = 800 + Math.sin(x / 140) * 18 + rnd() * 14, h = 30 + rnd() * 55, w = h * 0.32;
    d += `M${x.toFixed(0)} ${base.toFixed(0)} L${(x + w).toFixed(0)} ${(base - h).toFixed(0)} L${(x + 2 * w).toFixed(0)} ${base.toFixed(0)}Z `;
  }
  const p = document.createElementNS(NS, 'path');
  p.setAttribute('d', d);
  $('#trees').appendChild(p);
}

/* ---------- canvas weather effects ---------- */
const cv = $('#fx'), ctx = cv.getContext('2d'), flash = $('#flash');
let raf = 0, parts = [], W = 0, H = 0, last = 0, nextBolt = 0, bolt = null;

function size() {
  const r = cv.getBoundingClientRect(), dpr = Math.min(2, devicePixelRatio || 1);
  W = r.width; H = r.height; cv.width = W * dpr; cv.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function seed() {
  const kind = root.dataset.wx;
  parts = [];
  const n = { rain: 260, thunder: 320, snow: 190, fog: 7, clear: 40, partly: 26 }[kind] || 0;
  for (let i = 0; i < n; i++) {
    if (kind === 'rain' || kind === 'thunder') parts.push({ x: Math.random() * W * 1.2, y: Math.random() * H, l: 10 + Math.random() * 18, v: (700 + Math.random() * 500) * (W / 1200), a: 0.35 + Math.random() * 0.4 });
    else if (kind === 'snow') parts.push({ x: Math.random() * W, y: Math.random() * H, r: 1.2 + Math.random() * 3, v: 20 + Math.random() * 45, ph: Math.random() * 6.28, a: 0.5 + Math.random() * 0.5 });
    else if (kind === 'fog') parts.push({ x: Math.random() * W, y: H * (0.45 + Math.random() * 0.45), r: W * (0.25 + Math.random() * 0.25), v: 6 + Math.random() * 14, a: 0.06 + Math.random() * 0.08 });
    else parts.push({ x: Math.random() * W, y: H * (0.35 + Math.random() * 0.6), r: 1 + Math.random() * 1.8, vx: (Math.random() - 0.5) * 14, vy: (Math.random() - 0.5) * 10, ph: Math.random() * 6.28 });
  }
  nextBolt = performance.now() + 1500;
}

function mkBolt() {
  let x = W * (0.2 + Math.random() * 0.6), y = 0;
  const p = [[x, y]];
  while (y < H * 0.62) { y += H * (0.04 + Math.random() * 0.05); x += (Math.random() - 0.5) * W * 0.05; p.push([x, y]); }
  return p;
}

function frame(t) {
  const dt = Math.min(0.05, (t - last) / 1000 || 0);
  last = t;
  ctx.clearRect(0, 0, W, H);
  const kind = root.dataset.wx;
  if (state.fx) {
    if (kind === 'rain' || kind === 'thunder') {
      ctx.lineCap = 'round'; ctx.lineWidth = 1.5;
      for (const p of parts) {
        p.y += p.v * dt; p.x -= p.v * dt * 0.18;
        if (p.y > H) { p.y = -20; p.x = Math.random() * W * 1.2; }
        ctx.strokeStyle = `rgba(200,215,235,${p.a})`;
        ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x + p.l * 0.18, p.y - p.l); ctx.stroke();
      }
      if (kind === 'thunder' && t > nextBolt) {
        bolt = { t, pts: mkBolt() };
        nextBolt = t + 3500 + Math.random() * 5000;
        if (!reduce) {
          flash.style.transition = 'none'; flash.style.opacity = 0.55;
          requestAnimationFrame(() => { flash.style.transition = 'opacity .9s'; flash.style.opacity = 0; });
        }
      }
      if (bolt && t - bolt.t < 260) {
        ctx.strokeStyle = `rgba(235,240,255,${1 - (t - bolt.t) / 260})`;
        ctx.lineWidth = 2.2; ctx.shadowColor = '#bcd0ff'; ctx.shadowBlur = 18;
        ctx.beginPath(); bolt.pts.forEach((q, i) => (i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]))); ctx.stroke();
        ctx.shadowBlur = 0;
      }
    } else if (kind === 'snow') {
      for (const p of parts) {
        p.y += p.v * dt; p.ph += dt; p.x += Math.sin(p.ph) * 18 * dt;
        if (p.y > H) { p.y = -5; p.x = Math.random() * W; }
        ctx.fillStyle = `rgba(255,255,255,${p.a})`;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill();
      }
    } else if (kind === 'fog') {
      for (const p of parts) {
        if (!(p.r > 0)) continue;   // particles of the previous weather, until they're rebuilt
        p.x += p.v * dt;
        if (p.x - p.r > W) p.x = -p.r;
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r);
        g.addColorStop(0, `rgba(225,230,238,${p.a})`); g.addColorStop(1, 'rgba(225,230,238,0)');
        ctx.fillStyle = g; ctx.fillRect(p.x - p.r, p.y - p.r, p.r * 2, p.r * 2);
      }
    } else if (kind === 'clear' || kind === 'partly') {
      const night = isNight();
      for (const p of parts) {
        p.ph += dt * 1.5; p.x += p.vx * dt; p.y += p.vy * dt + Math.sin(p.ph) * 4 * dt;
        if (p.x < 0) p.x = W; if (p.x > W) p.x = 0; if (p.y < H * 0.3) p.y = H * 0.95; if (p.y > H) p.y = H * 0.35;
        const a = (Math.sin(p.ph) + 1) / 2;
        if (night) {
          ctx.fillStyle = `rgba(255,226,120,${0.25 + a * 0.6})`; ctx.shadowColor = '#ffd65c'; ctx.shadowBlur = 10;
          ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, 6.283); ctx.fill(); ctx.shadowBlur = 0;
        } else {
          ctx.fillStyle = `rgba(255,250,230,${0.12 + a * 0.25})`;
          ctx.beginPath(); ctx.arc(p.x, p.y, p.r * 0.8, 0, 6.283); ctx.fill();
        }
      }
    }
  }
  raf = reduce ? 0 : requestAnimationFrame(frame);
}

function restart() {
  cancelAnimationFrame(raf);
  size(); seed();
  last = performance.now() - 16;
  frame(performance.now());
}

export function fxRun(on) {
  if (on && !state.running) { state.running = true; restart(); }
  if (!on && state.running) { state.running = false; cancelAnimationFrame(raf); raf = 0; ctx.clearRect(0, 0, W, H); flash.style.opacity = 0; }
}

export function init() {
  build();
  refreshSky();
  new ResizeObserver(() => { if (state.running) restart(); }).observe(cv);
  setInterval(refreshSky, 60000);
}
