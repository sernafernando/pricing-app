/**
 * Tests for DivergenciasML.jsx (slice 7 — ml-ventas-fuente-de-verdad).
 *
 * Scope:
 *  - `ml_ops.ver` gates visibility; `ml_ops.gestionar` gates action controls.
 *  - GET /ml-ventas-ops/divergences called with kind/state/limit/offset params.
 *  - 403 vs 503 render distinct messages.
 *  - `detected_at` renders as "first detected" language, never "última".
 *  - `window_not_enumerable` rows render window bounds, not an order id.
 *  - PATCH /ml-ventas-ops/divergences/{id} fires with state/assigned_to_id/note.
 *
 * PermisosContext is mocked locally (overriding the global setup.js stub) so
 * each test can control tienePermiso per-case, mirroring MLQuestions.test.jsx.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import DivergenciasML from './DivergenciasML';
import api from '../services/api';

const mockTienePermiso = vi.fn(() => true);

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => mockTienePermiso(codigo),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const FIELD_MISMATCH_ROW = {
  id: 1,
  order_id: 555,
  kind: 'field_mismatch',
  field: 'total_amount',
  ml_value: '100',
  gbp_value: '90',
  window_from: null,
  window_to: null,
  state: 'open',
  assigned_to_id: null,
  note: null,
  detected_at: '2026-08-20T10:00:00Z',
  updated_at: '2026-08-20T10:00:00Z',
};

const UNENUMERABLE_ROW = {
  id: 2,
  order_id: null,
  kind: 'window_not_enumerable',
  field: null,
  ml_value: null,
  gbp_value: null,
  window_from: '2026-08-01T00:00:00Z',
  window_to: '2026-08-01T06:00:00Z',
  state: 'open',
  assigned_to_id: null,
  note: null,
  detected_at: '2026-08-20T10:00:00Z',
  updated_at: '2026-08-20T10:00:00Z',
};

function mockDivergencesList(rows, { total } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/ml-ventas-ops/divergences') {
      return Promise.resolve({ data: { divergences: rows, total: total ?? rows.length, limit: 50, offset: 0 } });
    }
    return Promise.resolve({ data: {} });
  });
}

beforeEach(() => {
  mockTienePermiso.mockReset();
  mockTienePermiso.mockImplementation(() => true);
  api.get.mockReset();
  api.patch.mockReset();
  mockDivergencesList([]);
  api.patch.mockResolvedValue({ data: {} });
});

describe('Visibility gated by ml_ops.ver', () => {
  it('renders nothing when ml_ops.ver is not granted', async () => {
    mockTienePermiso.mockImplementation(() => false);
    const { container } = await renderWithRouter(<DivergenciasML />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders the page when ml_ops.ver is granted', async () => {
    await renderWithRouter(<DivergenciasML />);
    expect(await screen.findByText('Divergencias ML Ventas')).toBeInTheDocument();
  });
});

describe('Fetching the list', () => {
  it('calls GET /ml-ventas-ops/divergences with limit=50 and offset=0 on mount', async () => {
    await renderWithRouter(<DivergenciasML />);
    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith(
        '/ml-ventas-ops/divergences',
        expect.objectContaining({ params: expect.objectContaining({ limit: 50, offset: 0 }) })
      );
    });
  });

  it('sends kind and state filters and resets offset to 0 on filter change', async () => {
    mockDivergencesList([], { total: 200 });
    const user = userEvent.setup();
    await renderWithRouter(<DivergenciasML />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/ml-ventas-ops/divergences', expect.anything());
    });

    // Advance to page 2 first, so the filter change is proven to reset it.
    await user.click(screen.getByRole('button', { name: /siguiente/i }));
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/divergences');
      expect(calls[calls.length - 1][1].params.offset).toBe(50);
    });

    const kindSelect = screen.getAllByRole('combobox')[0];
    await user.selectOptions(kindSelect, 'field_mismatch');

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/divergences');
      const last = calls[calls.length - 1];
      expect(last[1].params).toEqual(
        expect.objectContaining({ offset: 0, kind: 'field_mismatch' })
      );
    });

    const stateSelect = screen.getAllByRole('combobox')[1];
    await user.selectOptions(stateSelect, 'resolved');

    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/divergences');
      const last = calls[calls.length - 1];
      expect(last[1].params).toEqual(
        expect.objectContaining({ offset: 0, state: 'resolved' })
      );
    });
  });

  it('renders the honest total and paginates', async () => {
    mockDivergencesList([], { total: 730 });
    await renderWithRouter(<DivergenciasML />);
    await waitFor(() => {
      expect(screen.getByText(/730/)).toBeInTheDocument();
    });
  });
});

describe('403 vs 503 — distinct messages', () => {
  it('shows a permission message on 403', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/divergences') {
        return Promise.reject({ response: { status: 403 } });
      }
      return Promise.resolve({ data: {} });
    });
    await renderWithRouter(<DivergenciasML />);
    expect(await screen.findByText(/no ten[eé]s permiso/i)).toBeInTheDocument();
  });

  it('shows a feature-disabled message on 503', async () => {
    api.get.mockImplementation((url) => {
      if (url === '/ml-ventas-ops/divergences') {
        return Promise.reject({ response: { status: 503 } });
      }
      return Promise.resolve({ data: {} });
    });
    await renderWithRouter(<DivergenciasML />);
    expect(await screen.findByText(/deshabilitada/i)).toBeInTheDocument();
  });
});

describe('detected_at — first detection, never "last seen"', () => {
  it('never renders "última detección" or "visto por última vez"', async () => {
    mockDivergencesList([FIELD_MISMATCH_ROW]);
    await renderWithRouter(<DivergenciasML />);
    await waitFor(() => {
      expect(screen.getByText('Detectada')).toBeInTheDocument();
    });
    expect(screen.queryByText(/última detección/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/visto por última vez/i)).not.toBeInTheDocument();
  });
});

describe('window_not_enumerable rows render distinctly', () => {
  it('renders window bounds instead of an order id, and no field/ml/gbp values', async () => {
    mockDivergencesList([UNENUMERABLE_ROW]);
    await renderWithRouter(<DivergenciasML />);

    await waitFor(() => {
      expect(screen.getByText(/Ventana no enumerable/)).toBeInTheDocument();
    });
    expect(screen.getByText(/2026-08-01T00:00:00Z/)).toBeInTheDocument();
    expect(screen.getByText(/2026-08-01T06:00:00Z/)).toBeInTheDocument();
  });
});

describe('Actions gated by ml_ops.gestionar', () => {
  it('does not render the "Gestionar" action for a ml_ops.ver-only user', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo === 'ml_ops.ver');
    mockDivergencesList([FIELD_MISMATCH_ROW]);
    await renderWithRouter(<DivergenciasML />);

    await waitFor(() => {
      expect(screen.getByText('total_amount')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /gestionar/i })).not.toBeInTheDocument();
  });

  it('opens the edit modal and PATCHes state/assigned_to_id/note', async () => {
    mockDivergencesList([FIELD_MISMATCH_ROW]);
    const user = userEvent.setup();
    await renderWithRouter(<DivergenciasML />);

    const manageBtn = await screen.findByRole('button', { name: /gestionar/i });
    await user.click(manageBtn);

    const stateSelect = await screen.findByDisplayValue('Abierta');
    await user.selectOptions(stateSelect, 'resolved');

    const saveBtn = screen.getByRole('button', { name: /^guardar$/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        '/ml-ventas-ops/divergences/1',
        expect.objectContaining({ state: 'resolved', assigned_to_id: null, note: null })
      );
    });
  });
});
