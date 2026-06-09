import { useEffect, useState } from 'react';
import { useRegisterSW } from 'virtual:pwa-register/react';

// How often to poll the server for a newer build, in ms.
// A "new build available" check is a tiny conditional request (304 if nothing
// changed), so a short interval is cheap and keeps clients fresh.
const UPDATE_CHECK_INTERVAL = 5 * 60 * 1000;

/**
 * Registers the service worker and detects when a new build is available.
 *
 * With `registerType: 'prompt'` the new SW waits instead of taking over
 * silently. `needRefresh` flips to true when a new build is detected; the UI
 * shows a toast and calls `applyUpdate()` only when the user opts in — which
 * activates the new SW and reloads the page.
 *
 * @returns {{ needRefresh: boolean, applyUpdate: () => void, dismiss: () => void }}
 */
export function usePwaUpdate() {
  // Captured from onRegisteredSW so the polling/listener side effects live in a
  // useEffect that React can tear down — onRegisteredSW may fire more than once
  // (re-registration, retries), so wiring timers/listeners there would stack them.
  const [registration, setRegistration] = useState(null);

  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, swRegistration) {
      if (swRegistration) setRegistration(swRegistration);
    },
  });

  useEffect(() => {
    if (!registration) return;

    // Poll periodically — an SPA never triggers a navigation, so without this
    // a client with the tab open for days would never notice a new build.
    const intervalId = setInterval(() => registration.update(), UPDATE_CHECK_INTERVAL);

    // Also check the moment the user comes back to the tab — the most common
    // "I left it open and came back" case.
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') registration.update();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [registration]);

  return {
    needRefresh,
    applyUpdate: () => updateServiceWorker(true), // activate new SW + reload
    dismiss: () => setNeedRefresh(false),
  };
}
