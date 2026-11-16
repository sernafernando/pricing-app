/**
 * Arrow keys on a tablist (WAI-ARIA tabs pattern): Left/Right move to the previous/next enabled tab, wrapping around,
 * and select it, as a click would.
 *
 * @param {KeyboardEvent} e The keydown on the element with role="tablist".
 */
export const flechasTabs = (e) => {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  const tabs = [...e.currentTarget.querySelectorAll('[role="tab"]:not(:disabled)')];
  const i = tabs.indexOf(document.activeElement);
  if (i < 0) return;
  e.preventDefault();
  const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
  next.focus();
  next.click();
};
