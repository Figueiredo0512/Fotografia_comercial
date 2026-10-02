(() => {
  const dialog = document.querySelector('.photo-dialog');
  if (dialog) {
    dialog.removeAttribute('open');
    dialog.showModal();
    const closeLink = dialog.querySelector('.photo-dialog-close');
    const close = () => { window.location.href = closeLink.href; };
    const photos = [...document.querySelectorAll('.public-gallery figure')];
    let current = photos.findIndex(photo => '#' + photo.id === new URL(closeLink.href).hash);
    const navigate = direction => {
      if (photos.length < 2 || current < 0) return;
      current = (current + direction + photos.length) % photos.length;
      const photo = photos[current];
      const source = photo.querySelector('img');
      const image = dialog.querySelector('.photo-dialog-viewer img');
      image.src = source.src;
      image.alt = source.alt;
      dialog.querySelector('h2').textContent = photo.querySelector('h2').textContent;
      let description = dialog.querySelector('.photo-dialog-description');
      const text = photo.querySelector('figcaption p')?.textContent;
      if (text) {
        if (!description) {
          description = document.createElement('p');
          description.className = 'photo-dialog-description';
          dialog.append(description);
        }
        description.textContent = text;
      } else description?.remove();
      closeLink.href = '/portfolio#' + photo.id;
      history.replaceState(null, '', photo.querySelector('a').href);
    };
    dialog.querySelector('.photo-arrow-prev').addEventListener('click', () => navigate(-1));
    dialog.querySelector('.photo-arrow-next').addEventListener('click', () => navigate(1));
    dialog.addEventListener('keydown', event => {
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        navigate(event.key === 'ArrowLeft' ? -1 : 1);
      }
    });
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.addEventListener('click', event => { if (event.target === dialog) close(); });
  }
  const carousel = document.querySelector('.portfolio-carousel');
  if (!carousel) return;
  const track = carousel.querySelector('.gallery-carousel');
  const originals = [...track.children];
  if (originals.length < 2) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  // Repete a seleção visualmente para atravessar a última foto sem salto.
  for (const item of originals) {
    const clone = item.cloneNode(true);
    clone.setAttribute('aria-hidden', 'true');
    clone.dataset.clone = 'true';
    clone.querySelectorAll('a').forEach(link => { link.tabIndex = -1; });
    track.append(clone);
  }
  const firstClone = track.children[originals.length];
  let span = 0;
  let position = carousel.scrollLeft;
  let previous = null;
  let hovered = carousel.matches(':hover');
  let touching = false;
  const keyboardFocus = () => carousel.matches(':focus-visible') || Boolean(carousel.querySelector(':focus-visible'));
  const measure = () => {
    span = firstClone.getBoundingClientRect().left - originals[0].getBoundingClientRect().left;
    position = carousel.scrollLeft;
  };
  new ResizeObserver(measure).observe(carousel);
  measure();
  carousel.addEventListener('mouseenter', () => { hovered = true; });
  carousel.addEventListener('mouseleave', () => { hovered = false; });
  carousel.addEventListener('touchstart', () => { touching = true; }, {passive: true});
  for (const type of ['touchend', 'touchcancel']) {
    carousel.addEventListener(type, () => { touching = false; position = carousel.scrollLeft; }, {passive: true});
  }
  carousel.addEventListener('scroll', () => {
    if (hovered || touching || reduced.matches || keyboardFocus()) position = carousel.scrollLeft;
  }, {passive: true});
  const animate = timestamp => {
    const elapsed = previous === null ? 0 : Math.min(timestamp - previous, 50);
    previous = timestamp;
    if (span > 0 && !hovered && !touching && !keyboardFocus() && !reduced.matches && !document.hidden) {
      position = (position + elapsed * 0.035) % span;
      carousel.scrollLeft = position;
    }
    requestAnimationFrame(animate);
  };
  requestAnimationFrame(animate);
})();
