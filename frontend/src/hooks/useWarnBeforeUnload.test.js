/**
 * useWarnBeforeUnload: while `active`, reloading or closing the tab asks the browser's own "leave site?" question;
 * otherwise it leaves the page alone.
 */
import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import useWarnBeforeUnload from './useWarnBeforeUnload';

const unload = () => {
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  return event;
};

describe('useWarnBeforeUnload', () => {
  it('asks before unloading while active, and stops asking when it turns off or unmounts', () => {
    const { rerender, unmount } = renderHook(({ active }) => useWarnBeforeUnload(active), { initialProps: { active: true } });
    expect(unload().defaultPrevented).toBe(true);

    rerender({ active: false });
    expect(unload().defaultPrevented).toBe(false);

    rerender({ active: true });
    unmount();
    expect(unload().defaultPrevented).toBe(false);
  });
});
