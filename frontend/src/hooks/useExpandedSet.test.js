import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useExpandedSet } from './useExpandedSet';

describe('useExpandedSet', () => {
  it('starts with an empty set', () => {
    const { result } = renderHook(() => useExpandedSet());
    expect(result.current.expanded.size).toBe(0);
    expect(result.current.isOpen('a')).toBe(false);
  });

  it('toggle adds an id when closed', () => {
    const { result } = renderHook(() => useExpandedSet());
    act(() => result.current.toggle('a'));
    expect(result.current.isOpen('a')).toBe(true);
  });

  it('toggle removes an id when open', () => {
    const { result } = renderHook(() => useExpandedSet());
    act(() => result.current.toggle('a'));
    act(() => result.current.toggle('a'));
    expect(result.current.isOpen('a')).toBe(false);
  });

  it('close removes a specific id without affecting others', () => {
    const { result } = renderHook(() => useExpandedSet());
    act(() => {
      result.current.toggle('a');
      result.current.toggle('b');
    });
    act(() => result.current.close('a'));
    expect(result.current.isOpen('a')).toBe(false);
    expect(result.current.isOpen('b')).toBe(true);
  });

  it('clear empties the set', () => {
    const { result } = renderHook(() => useExpandedSet());
    act(() => {
      result.current.toggle('a');
      result.current.toggle('b');
    });
    act(() => result.current.clear());
    expect(result.current.expanded.size).toBe(0);
  });
});
