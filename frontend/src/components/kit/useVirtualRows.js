/**
 * useVirtualRows — the one row virtualization of the kit tables (TableShell, Métricas ML's board): past
 * `virtualizeFrom` rows only the rows in view (and `OVERSCAN` around them) are in the DOM, as Envíos Flex does. Each
 * row is its own `<tbody>` (the row and its sub-rows, measured together through `measureElement`, so a row of any
 * height or an expanded one keeps its place) between two spacers `before` / `after` px high.
 *
 * The scroller is `scrollerRef`'s element (TableShell and Métricas ML's board own a bounded one). Without it the
 * page itself scrolls (unit mounts): then `listRef` is the table, whose distance from the top of the page is the
 * virtualizer's scroll margin.
 *
 * `onEndReached` is called when the last rows come into view (the last rendered row within `OVERSCAN` of the end),
 * once per `rows`: a page that loads its list in parts asks the next one. A table that renders every row never calls it.
 */
import { useEffect, useRef } from 'react';
import { observeWindowOffset, observeWindowRect, useVirtualizer, windowScroll } from '@tanstack/react-virtual';

// A first guess at a row's height (each row is measured once in view) and the rows kept beyond the view on each side,
// more than PageUp/PageDown's ten so the keyboard always lands on a row in the DOM.
export const ESTIMATED_ROW_HEIGHT = 56;
export const OVERSCAN = 15;

const windowOptions = (listRef) => ({
  getScrollElement: () => window,
  observeElementRect: observeWindowRect,
  observeElementOffset: observeWindowOffset,
  scrollToFn: windowScroll,
  initialOffset: () => window.scrollY,
  scrollMargin: listRef?.current ? listRef.current.getBoundingClientRect().top + window.scrollY : 0,
});

export function useVirtualRows({ rows, getRowKey, virtualizeFrom, onEndReached, scrollerRef, listRef }) {
  const virtual = virtualizeFrom != null && rows.length > virtualizeFrom;
  const virtualizer = useVirtualizer({
    count: virtual ? rows.length : 0,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: OVERSCAN,
    getItemKey: (index) => getRowKey(rows[index]),
    ...(scrollerRef ? { getScrollElement: () => scrollerRef.current } : windowOptions(listRef)),
  });
  const items = virtualizer.getVirtualItems();
  const lastInView = items.length > 0 ? items[items.length - 1].index : -1;
  // The `rows` the end was last reached for: the same rows never ask twice (the page's part is in flight or there is
  // none left), new rows -- a part appended, another list -- ask again when their end is in view.
  const endReachedFor = useRef(null);
  useEffect(() => {
    if (!virtual || !onEndReached || lastInView < rows.length - 1 - OVERSCAN) return;
    if (endReachedFor.current === rows) return;
    endReachedFor.current = rows;
    onEndReached();
  }, [virtual, onEndReached, lastInView, rows]);

  // The items' offsets count the scroll margin (the page above a window-scrolled table); the spacers do not.
  const margin = virtualizer.options?.scrollMargin ?? 0;
  const before = items.length > 0 ? items[0].start - margin : 0;
  const after = items.length > 0 ? virtualizer.getTotalSize() - (items[items.length - 1].end - margin) : 0;
  return { virtual, items, before, after, measureElement: virtualizer.measureElement };
}
