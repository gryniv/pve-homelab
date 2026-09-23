// Horizontal rail for the systems row: arrows, dimmed edges and a "+N" counter
// for cards that are still off to the right.
import { t } from './ui.js';

export function rail(root) {
  const track = root.querySelector('.systems');
  const more = root.querySelector('.more');
  const next = root.querySelector('.rail-btn.next');
  const cards = () => [...track.querySelectorAll('.sys')];

  function update() {
    const list = cards();
    track.classList.toggle('many', list.length > 4);
    const max = track.scrollWidth - track.clientWidth;
    root.classList.toggle('more-l', track.scrollLeft > 4);
    root.classList.toggle('more-r', max - track.scrollLeft > 4);
    const edge = track.getBoundingClientRect().right - 8;
    const hidden = list.filter((c) => c.getBoundingClientRect().right > edge).length;
    more.textContent = hidden ? '+' + hidden : '';
    next.title = hidden ? t('sys.more', { n: hidden }) : t('sys.next');
  }

  // One click pages by the number of fully visible cards.
  function page(dir) {
    const list = cards();
    if (!list.length) return;
    const step = list[0].offsetWidth + parseFloat(getComputedStyle(track).columnGap || 0);
    const per = Math.max(1, Math.floor((track.clientWidth + 8) / step));
    track.scrollBy({ left: dir * per * step, behavior: 'smooth' });
  }

  root.querySelectorAll('[data-rail]').forEach((b) => (b.onclick = () => page(+b.dataset.rail)));
  track.addEventListener('scroll', update, { passive: true });
  // A plain mouse wheel scrolls the rail sideways, but only when there is somewhere to go.
  track.addEventListener('wheel', (e) => {
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY) || track.scrollWidth <= track.clientWidth) return;
    const max = track.scrollWidth - track.clientWidth;
    if ((e.deltaY < 0 && track.scrollLeft <= 0) || (e.deltaY > 0 && track.scrollLeft >= max)) return;
    e.preventDefault();
    track.scrollBy({ left: e.deltaY * 1.5 });
  }, { passive: false });
  new ResizeObserver(update).observe(track);
  return update;
}
