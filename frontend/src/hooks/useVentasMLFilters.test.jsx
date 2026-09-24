/**
 * Tests for useVentasMLFilters.js (ventas-ml-rediseno PR13, PANEL R19).
 *
 * Scope for PR13: the `orden` URL param drives row selection, consistent
 * with this screen's other URL-driven filters (`useQueryFilters`).
 */

import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { useVentasMLFilters } from './useVentasMLFilters';

function wrapper({ children, initialEntries = ['/'] }) {
  return <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>;
}

describe('selectedOrderId', () => {
  it('is null when the URL carries no `orden` param', () => {
    const { result } = renderHook(() => useVentasMLFilters(), {
      wrapper: (props) => wrapper({ ...props, initialEntries: ['/'] }),
    });
    expect(result.current.selectedOrderId).toBeNull();
  });

  it('reads the numeric order id from the `orden` URL param', () => {
    const { result } = renderHook(() => useVentasMLFilters(), {
      wrapper: (props) => wrapper({ ...props, initialEntries: ['/?orden=1001'] }),
    });
    expect(result.current.selectedOrderId).toBe(1001);
  });
});

describe('selectOrder', () => {
  it('sets the `orden` URL param, driving selectedOrderId on the next render', () => {
    const { result } = renderHook(() => useVentasMLFilters(), {
      wrapper: (props) => wrapper({ ...props, initialEntries: ['/'] }),
    });

    act(() => result.current.selectOrder(2002));

    expect(result.current.selectedOrderId).toBe(2002);
  });
});

describe('clearSelection', () => {
  it('removes the `orden` URL param', () => {
    const { result } = renderHook(() => useVentasMLFilters(), {
      wrapper: (props) => wrapper({ ...props, initialEntries: ['/?orden=1001'] }),
    });
    expect(result.current.selectedOrderId).toBe(1001);

    act(() => result.current.clearSelection());

    expect(result.current.selectedOrderId).toBeNull();
  });
});
