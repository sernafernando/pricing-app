import { useSyncExternalStore } from 'react';

const QUERY = '(max-width: 768px)';

const subscribe = (callback) => {
  const mql = window.matchMedia(QUERY);
  mql.addEventListener('change', callback);
  return () => mql.removeEventListener('change', callback);
};

const getSnapshot = () => window.matchMedia(QUERY).matches;
const getServerSnapshot = () => false;

export default function useIsPhone() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
