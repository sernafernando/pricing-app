import { useState } from 'react';

/** `useSearchParams` for the page-level visual tests, which mock react-router-dom (a live one pulls a second React
 * graph into browser mode): an in-memory query that starts empty and that the page's writes update. */
export function useSearchParams() {
  const [params, setParams] = useState(() => new URLSearchParams());
  return [params, (next) => setParams(new URLSearchParams(next))];
}
