import { useEffect } from 'react';

/**
 * While `active`, reloading or closing the tab asks the browser's own "leave site?" question (its wording is
 * the browser's, it cannot be set). For work that dies with the page, such as an export still writing a sheet.
 */
export default function useWarnBeforeUnload(active) {
  useEffect(() => {
    if (!active) return undefined;
    const warn = (event) => {
      event.preventDefault();
      event.returnValue = ''; // older Chrome and Safari still need it set
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [active]);
}
