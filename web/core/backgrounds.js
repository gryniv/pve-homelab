// Backgrounds: the SVG landscape scene (index.html .land) plus CSS ones from backgrounds.css.
// layer() is shared by the full screen and the mini-monitor previews in settings.
import { esc } from './ui.js';

export const SCAPES = ['mountains', 'sea', 'dunes', 'city', 'hills', 'night'];
export const FLAT = ['gradient', 'aurora', 'dots', 'grid', 'solid', 'black'];
export const LANDSCAPES = ['scene', 'still', ...SCAPES];

export const isCss = (k) => SCAPES.includes(k) || FLAT.includes(k);

export function layer(k) {
  if (!isCss(k)) return '<span class="landpv" data-land></span>';
  const scape = SCAPES.includes(k) ? ' scape' : '';
  return `<span class="bgx${scape}" data-k="${esc(k)}"><i class="stars"></i><i class="sun"></i><i class="l1"></i><i class="l2"></i><i class="l3"></i><i class="l4"></i></span>`;
}

// Full-screen background of the page.
export function apply(k) {
  const host = document.querySelector('#bgHost');
  if (!host || host.dataset.k === k) return;
  host.dataset.k = k;
  host.innerHTML = isCss(k) ? layer(k) : '';
}

// A tiny monitor: the background under a sign-in screen that turns into the dashboard.
export function mini(k, skin, clock) {
  return `<span class="mon"><span class="scrn" data-skin="${esc(skin)}">${layer(k)}<span class="mock">
    <span class="mk-login"><b class="t">${esc(clock)}</b><b class="d"></b><b class="u"><b></b><b></b><b></b></b></span>
    <span class="mk-dash"><i class="tp"></i><i class="sd"></i><i class="sy"><b></b><b></b><b></b><b></b></i><i class="gr">${'<b></b>'.repeat(10)}</i></span>
  </span></span></span>`;
}

// The SVG scene can't be drawn in CSS: previews get a copy of the live one.
export function fillLand(root) {
  const svg = document.querySelector('.land svg');
  root.querySelectorAll('[data-land]').forEach((el) => { if (svg && !el.firstChild) el.appendChild(svg.cloneNode(true)); });
}
