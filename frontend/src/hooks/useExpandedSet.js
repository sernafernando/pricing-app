import { useState, useCallback } from 'react';

/**
 * Manages a Set of expanded row ids.
 * Reusable primitive for expand/collapse UI state (product rows, MLA rows, etc).
 *
 * @returns {{ expanded: Set, isOpen: (id: any) => boolean, toggle: (id: any) => void, close: (id: any) => void, clear: () => void }}
 */
export function useExpandedSet() {
  const [expanded, setExpanded] = useState(() => new Set());

  const isOpen = useCallback((id) => expanded.has(id), [expanded]);

  const toggle = useCallback((id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const close = useCallback((id) => {
    setExpanded((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setExpanded(new Set());
  }, []);

  return { expanded, isOpen, toggle, close, clear };
}

export default useExpandedSet;
