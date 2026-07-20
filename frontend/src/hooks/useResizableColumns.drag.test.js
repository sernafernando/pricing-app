import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useResizableColumns } from './useResizableColumns';

describe('useResizableColumns DRAG path (mouse)', () => {
  beforeEach(() => localStorage.clear());

  const cols = [{ id: 'a', label: 'A', resizable: true, min: 100, max: 600, defaultWidth: 220 }];

  it('onMouseDown then document mousemove updates colWidth', () => {
    const { result } = renderHook(() => useResizableColumns({ storageKey: 'k', columns: cols }));

    const handleProps = result.current.getHandleProps('a');
    expect(typeof handleProps.onMouseDown).toBe('function');

    let prevented = false;
    act(() => {
      // jsdom: th.offsetWidth is 0 -> hook should fall back to defaultWidth (220)
      handleProps.onMouseDown({
        target: { closest: () => ({ offsetWidth: 0 }) },
        clientX: 500,
        preventDefault: () => { prevented = true; },
      });
    });

    // Must suppress native text selection so real-browser drag isn't swallowed.
    expect(prevented).toBe(true);
    expect(document.body.style.userSelect).toBe('none');

    act(() => {
      document.dispatchEvent(new MouseEvent('mousemove', { clientX: 560, bubbles: true }));
    });

    // baseWidth 220 + dx 60 = 280
    expect(result.current.isResized('a')).toBe(true);
    expect(result.current.colWidth('a')).toBe(280);
  });

  it('mousemove after mouseup does nothing (listeners removed)', () => {
    const { result } = renderHook(() => useResizableColumns({ storageKey: 'k', columns: cols }));
    const handleProps = result.current.getHandleProps('a');

    act(() => handleProps.onMouseDown({ target: { closest: () => ({ offsetWidth: 0 }) }, clientX: 500 }));
    act(() => document.dispatchEvent(new MouseEvent('mousemove', { clientX: 560 })));
    const afterDrag = result.current.colWidth('a');
    act(() => document.dispatchEvent(new MouseEvent('mouseup', {})));
    act(() => document.dispatchEvent(new MouseEvent('mousemove', { clientX: 900 })));

    expect(result.current.colWidth('a')).toBe(afterDrag);
  });
});
