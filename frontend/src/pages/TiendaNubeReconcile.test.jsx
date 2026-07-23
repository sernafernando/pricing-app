/**
 * Tests for TiendaNubeReconcile.jsx (Slice 1 — read-only reconciliation view).
 *
 * Scope:
 *   - Permission gating (usePermisos)
 *   - Column resize persist/reset (reuses MLQuestions.test.jsx's
 *     TanStack column-sizing pattern, own localStorage key)
 *   - MAL_PUBLICADO and DUPLICADO surfaced as dedicated, clearly labeled views
 *   - DUPLICADO groups never pre-select/highlight/recommend a row
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import TiendaNubeReconcile, { COLUMN_SIZING_STORAGE_KEY } from './TiendaNubeReconcile';
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

const REPORTE = [
  { ean: '111', verdict: 'FALTA_PUBLICAR', despublicar: false, gbp_row: { Código: '111' }, tn_matches: [] },
  {
    ean: '222',
    verdict: 'MAL_PUBLICADO',
    despublicar: false,
    gbp_row: { Código: '222' },
    tn_matches: [{ product_id: 1, variant_id: 1, variant_sku: '999', activo: true }],
  },
  {
    ean: '333',
    verdict: 'DUPLICADO',
    despublicar: false,
    gbp_row: { Código: '333' },
    tn_matches: [
      { product_id: 10, variant_id: 1, variant_sku: '333', activo: true },
      { product_id: 11, variant_id: 1, variant_sku: '333', activo: true },
    ],
  },
];

function setupApiMocks() {
  api.get.mockImplementation((url) => {
    if (url === '/tienda-nube-reconcile/reporte') return Promise.resolve({ data: REPORTE });
    return Promise.resolve({ data: [] });
  });
}

beforeEach(() => {
  localStorage.clear();
  mockTienePermiso.mockReset();
  mockTienePermiso.mockImplementation(() => true);
  setupApiMocks();
});

describe('Permission gating', () => {
  it('renders nothing when admin.ver_tn_reconciliacion is not granted', async () => {
    mockTienePermiso.mockImplementation(() => false);

    const { container } = await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(container.textContent).not.toMatch(/Reconciliación/i);
    });
  });

  it('fetches the report when permission is granted', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/tienda-nube-reconcile/reporte');
    });
  });
});

describe('Anomaly sub-tabs', () => {
  it('shows a dedicated MAL_PUBLICADO sub-tab', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Mal publicado/i })).toBeInTheDocument();
    });
  });

  it('shows a dedicated DUPLICADO sub-tab labeled as human review, not error', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    const dupTab = await screen.findByRole('button', { name: /Duplicado/i });
    expect(dupTab).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(dupTab);

    await waitFor(() => {
      expect(screen.getByText(/revisión humana/i)).toBeInTheDocument();
    });
    // Never suggests which row to delete
    expect(screen.queryByText(/recomendad/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/sugerid/i)).not.toBeInTheDocument();
  });

  it('shows all conflicting TN rows in a DUPLICADO group without any pre-selection', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    const user = userEvent.setup();
    const dupTab = await screen.findByRole('button', { name: /Duplicado/i });
    await user.click(dupTab);

    await waitFor(() => {
      expect(screen.getByText(/product_id: 10/i)).toBeInTheDocument();
      expect(screen.getByText(/product_id: 11/i)).toBeInTheDocument();
    });
    // No row carries a "selected"/"checked"/pre-highlighted affordance
    expect(document.querySelector('input[type="radio"]')).toBeNull();
    expect(document.querySelector('input[type="checkbox"]')).toBeNull();
  });
});

describe('Column resize persist/reset', () => {
  it('loads persisted column sizing from localStorage on mount', async () => {
    localStorage.setItem(COLUMN_SIZING_STORAGE_KEY, JSON.stringify({ ean: 250 }));

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalled();
    });
    // Component didn't throw and rendered the table — persisted sizing was
    // accepted without crashing (fail-safe parse mirrors MLQuestions').
    expect(screen.getAllByRole('table').length).toBeGreaterThan(0);
  });

  it('never throws on corrupt localStorage — falls back to defaults', async () => {
    localStorage.setItem(COLUMN_SIZING_STORAGE_KEY, '{not-json');

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getAllByRole('table').length).toBeGreaterThan(0);
    });
  });
});
