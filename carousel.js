(() => {
  const carousel = document.querySelector('.portfolio-carousel');
  if (!carousel) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let paused = reduced.matches;
  let hovered = false;
  let visible = false;
  let timer;
  const update = () => {
    clearInterval(timer);
    if (paused || hovered || !visible || document.hidden || carousel.contains(document.activeElement)) return;
    timer = setInterval(() => {
      const items = [...carousel.querySelectorAll('.carousel-item')];
      const current = carousel.scrollLeft;
      const end = carousel.scrollWidth - carousel.clientWidth;
      const first = items[0].getBoundingClientRect().left;
      const next = items.map(item => item.getBoundingClientRect().left - first)
        .find(offset => offset > current + 4);
      carousel.scrollTo({left: current >= end - 4 ? 0 : Math.min(next ?? end, end),
        behavior: reduced.matches ? 'instant' : 'smooth'});
    }, 4500);
  };
  carousel.addEventListener('mouseenter', () => { hovered = true; update(); });
  carousel.addEventListener('mouseleave', () => { hovered = false; update(); });
  carousel.addEventListener('focusin', update);
  carousel.addEventListener('focusout', () => setTimeout(update, 0));
  carousel.addEventListener('touchstart', () => { paused = true; update(); }, {passive: true});
  carousel.addEventListener('touchend', () => { paused = reduced.matches; update(); }, {passive: true});
  carousel.addEventListener('touchcancel', () => { paused = reduced.matches; update(); }, {passive: true});
  document.addEventListener('visibilitychange', update);
  reduced.addEventListener('change', () => { paused = reduced.matches; update(); });
  new IntersectionObserver(entries => { visible = entries[0].isIntersecting; update(); },
    {threshold: 0.15}).observe(carousel);
  update();
})();
