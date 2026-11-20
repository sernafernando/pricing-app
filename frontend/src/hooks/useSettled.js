import { useEffect, useState } from 'react';

/**
 * What the requests are asked with while the user is still choosing (pubml-lentitud S2): `value` itself when its `key`
 * is the one already asked for (a page or sort change asks at once) or while `immediate` (the first load, a preset);
 * otherwise the last settled `{ value, key }` until `key` stops changing for `delay` ms. Three chips clicked in a row
 * ask once, with the three of them; the controls themselves keep reading the live value. Right after an `immediate`
 * phase nothing was asked with the settled value yet (the first load waits for the layer and the preset), so the next
 * value is used at once too: the first request never carries the filters a preset just replaced.
 *
 * @template T
 * @param {T} value the live value (the URL filters)
 * @param {string} key what identifies a change worth waiting for (the filter key)
 * @param {number} delay ms without a new key before it settles
 * @param {boolean} immediate settle at once (nothing was asked yet)
 * @returns {{ value: T, key: string }}
 */
export function useSettled(value, key, delay, immediate) {
  // `primed`: taken while nothing could be asked yet, so it is no answer to keep showing.
  const [settled, setSettled] = useState(() => ({ value, key, primed: true }));
  useEffect(() => {
    if (immediate) {
      setSettled({ value, key, primed: true });
      return undefined;
    }
    // The first value after the immediate phase is the one being asked now: from here on a new key waits.
    // A change under the asked key (page, sort) is asked now, so it is the settled value at once: a filter clicked
    // right after it keeps showing that page while it settles, never the page before it.
    setSettled((current) => (current.primed || current.key === key ? { value, key, primed: false } : current));
    const timer = setTimeout(() => setSettled({ value, key, primed: false }), delay);
    return () => clearTimeout(timer);
  }, [value, key, delay, immediate]);
  return immediate || settled.primed || key === settled.key ? { value, key } : { value: settled.value, key: settled.key };
}
