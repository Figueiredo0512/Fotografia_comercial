// Update only the calendar so month navigation keeps the page in place.
(() => {
  let loading = false;
  document.addEventListener('click', async event => {
    const link = event.target.closest('.month-nav a');
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (loading) return;
    const section = link.closest('.calendar-section');
    const target = link.href;
    const label = link.getAttribute('aria-label');
    loading = true;
    section.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(target, {credentials: 'same-origin'});
      if (!response.ok) throw new Error('Calendar unavailable');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const replacement = page.querySelector('.calendar-section');
      if (!replacement) throw new Error('Calendar missing');
      const x = window.scrollX;
      const y = window.scrollY;
      section.replaceWith(replacement);
      history.replaceState(history.state, '', target);
      const nextLink = [...replacement.querySelectorAll('.month-nav a')]
        .find(item => item.getAttribute('aria-label') === label);
      nextLink?.focus({preventScroll: true});
      window.scrollTo({left: x, top: y, behavior: 'instant'});
    } catch {
      // Keep regular navigation available if the request fails.
      window.location.assign(target);
    } finally {
      loading = false;
      section.removeAttribute('aria-busy');
    }
  });
})();
