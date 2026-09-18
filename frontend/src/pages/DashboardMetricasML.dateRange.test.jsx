/**
 * Wiring test for the shared date filter INSIDE DashboardMetricasML.
 *
 * `DateRangeFilter` was extracted OUT of this page so the ML sales view
 * could share it. For this page that extraction is a refactor, and the
 * acceptance bar was "métricas behaves identically" -- a bar nothing was
 * checking, because this page had no test file at all. The shared
 * component's own suite pins the preset arithmetic; what this file pins is
 * that THIS page still passes its dates in and still acts on the change.
 *
 * Deliberately narrow: this is not an attempt to cover the dashboard, it
 * covers the seam the refactor moved.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import DashboardMetricasML from './DashboardMetricasML';
import api from '../services/api';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

describe('DashboardMetricasML — shared date filter wiring', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date(2026, 8, 17, 12, 0, 0)); // 2026-09-17, local
    api.get.mockReset();
    // Every endpoint answers with an empty-but-VALID shape. The list
    // endpoints must return arrays: the page calls `.filter` on them, and
    // a bare `{}` crashes the render before the filter bar exists -- which
    // would make this test fail for a reason that has nothing to do with
    // the seam it is about.
    api.get.mockImplementation((url) => {
      // Anything the page iterates must be an array; everything else can
      // be an empty object. A bare `{}` everywhere crashes the render
      // before the filter bar exists, which would fail this test for a
      // reason that has nothing to do with the seam it is about.
      if (url.includes('disponibles') || url.includes('/usuarios/pms')) {
        return Promise.resolve({ data: [] });
      }
      if (url.includes('por-') || url.includes('top-productos')) {
        return Promise.resolve({ data: [] });
      }
      return Promise.resolve({ data: {} });
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('asks the API for the preset window when a preset is clicked', async () => {
    await renderWithRouter(<DashboardMetricasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalled();
    });

    await userEvent.click(screen.getByRole('button', { name: '7d' }));

    await waitFor(() => {
      // `fecha_desde`/`fecha_hasta` are THIS page's param names -- the ML
      // sales view sends the same window as `date_from`/`date_to`. The
      // shared component reports a range; each page names it for its own
      // endpoint, which is why the component owns no query-param logic.
      const conRango = api.get.mock.calls.filter(
        ([, config]) =>
          config?.params?.fecha_desde === '2026-09-11' && config?.params?.fecha_hasta === '2026-09-17'
      );
      expect(conRango.length).toBeGreaterThan(0);
    });
  });
});
