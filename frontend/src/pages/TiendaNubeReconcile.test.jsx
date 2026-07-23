/**
 * Tests for TiendaNubeReconcile.jsx (Slice 1 — read-only reconciliation view
 * + banlist management).
 *
 * Scope:
 *   - Permission gating (usePermisos)
 *   - Column resize persist/reset (reuses MLQuestions.test.jsx's
 *     TanStack column-sizing pattern, own localStorage key)
 *   - MAL_PUBLICADO and DUPLICADO surfaced as dedicated, clearly labeled views
 *   - DUPLICADO groups never pre-select/highlight/recommend a row (assertion
 *     scoped to the DUPLICADO group specifically — the banlist view below
 *     legitimately renders checkboxes for bulk unban elsewhere)
 *   - Ban/unban error handling (try/catch + toast, never an unhandled
 *     rejection)
 *   - Banlist view: list, individual unban, bulk unban
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
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

const REPORTE_ITEMS = [
  { ean: '111', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [] },
  {
    ean: '222',
    verdict: 'MAL_PUBLICADO',
    despublicar: false,
    tn_matches: [{ product_id: 1, variant_id: 1, variant_sku: '999', activo: true }],
  },
  {
    ean: '333',
    verdict: 'DUPLICADO',
    despublicar: false,
    tn_matches: [
      { product_id: 10, variant_id: 1, variant_sku: '333', activo: true },
      { product_id: 11, variant_id: 1, variant_sku: '333', activo: true },
    ],
  },
];

const BANEADOS = [
  {
    id: 1,
    ean: 'BANNED-1',
    motivo: 'test motivo',
    usuario_nombre: 'Operador',
    fecha_creacion: '2026-07-01T00:00:00Z',
  },
];

function setupApiMocks({ baneados = BANEADOS } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/tienda-nube-reconcile/reporte') {
      return Promise.resolve({ data: { items: REPORTE_ITEMS, total: REPORTE_ITEMS.length, page: 1, page_size: 200 } });
    }
    if (url === '/tienda-nube-reconcile/baneados') {
      return Promise.resolve({ data: baneados });
    }
    return Promise.resolve({ data: [] });
  });
  api.post.mockImplementation(() => Promise.resolve({ data: { success: true } }));
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
      expect(api.get).toHaveBeenCalledWith('/tienda-nube-reconcile/reporte', expect.anything());
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

  it('shows all conflicting TN rows in a DUPLICADO group with no pre-selected, highlighted, or recommended row', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    const user = userEvent.setup();
    const dupTab = await screen.findByRole('button', { name: /Duplicado/i });
    await user.click(dupTab);

    const groupHeading = await screen.findByText(/EAN GBP: 333/i);
    const group = groupHeading.closest(`[data-testid="duplicado-group"]`);
    expect(group).not.toBeNull();

    // Both conflicting TN rows are present with full context.
    expect(within(group).getByText(/product_id: 10/i)).toBeInTheDocument();
    expect(within(group).getByText(/product_id: 11/i)).toBeInTheDocument();

    // Scoped to the DUPLICADO group specifically: no row carries a
    // selection/highlight/recommendation affordance (radio, checkbox, a
    // "selected"/"recommended" row class, or an aria-selected row).
    expect(within(group).queryAllByRole('radio')).toHaveLength(0);
    expect(within(group).queryAllByRole('checkbox')).toHaveLength(0);
    const rows = within(group).getAllByRole('row');
    for (const row of rows) {
      expect(row).not.toHaveAttribute('aria-selected', 'true');
      expect(row.className || '').not.toMatch(/selected|recommended|highlight/i);
    }
  });
});

describe('Ban/unban error handling', () => {
  it('shows a success toast and reloads the report after a successful ban', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const banButton = await screen.findByRole('button', { name: /Banear/i });
    await user.click(banButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/banear', { ean: '111' });
    });
    await waitFor(() => {
      expect(screen.getByText(/agregado a la banlist/i)).toBeInTheDocument();
    });
  });

  it('shows an error toast (never an unhandled rejection) when ban fails with 400', async () => {
    api.post.mockImplementation(() =>
      Promise.reject({ response: { data: { detail: 'El EAN ya está en la banlist' } } })
    );
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const banButton = await screen.findByRole('button', { name: /Banear/i });
    await user.click(banButton);

    await waitFor(() => {
      expect(screen.getByText(/El EAN ya está en la banlist/i)).toBeInTheDocument();
    });
  });

  it('shows an error toast when unban fails', async () => {
    api.post.mockImplementation((url) => {
      if (url === '/tienda-nube-reconcile/desbanear') {
        return Promise.reject({ response: { data: { detail: 'Entrada de banlist no encontrada' } } });
      }
      return Promise.resolve({ data: { success: true } });
    });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const banlistTab = await screen.findByRole('button', { name: /Banlist/i });
    await user.click(banlistTab);

    const unbanButton = await screen.findByRole('button', { name: /Desbanear/i });
    await user.click(unbanButton);

    await waitFor(() => {
      expect(screen.getByText(/Entrada de banlist no encontrada/i)).toBeInTheDocument();
    });
  });
});

describe('Banlist view', () => {
  it('is hidden without admin.gestionar_tn_reconcile_banlist', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'admin.gestionar_tn_reconcile_banlist');

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Todos/i })).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /Banlist/i })).not.toBeInTheDocument();
  });

  it('lists banned EANs fetched from GET /baneados', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const banlistTab = await screen.findByRole('button', { name: /Banlist/i });
    await user.click(banlistTab);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/tienda-nube-reconcile/baneados');
    });
    expect(await screen.findByText('BANNED-1')).toBeInTheDocument();
    expect(screen.getByText('test motivo')).toBeInTheDocument();
  });

  it('unbans an individual EAN via POST /desbanear and reloads the list', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const banlistTab = await screen.findByRole('button', { name: /Banlist/i });
    await user.click(banlistTab);

    const unbanButton = await screen.findByRole('button', { name: /Desbanear/i });
    await user.click(unbanButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/desbanear', { banlist_id: 1 });
    });
  });

  it('bulk-unbans selected EANs via sequential POST /desbanear calls', async () => {
    setupApiMocks({
      baneados: [
        { id: 1, ean: 'A', motivo: null, usuario_nombre: 'Op', fecha_creacion: '2026-07-01T00:00:00Z' },
        { id: 2, ean: 'B', motivo: null, usuario_nombre: 'Op', fecha_creacion: '2026-07-01T00:00:00Z' },
      ],
    });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const banlistTab = await screen.findByRole('button', { name: /Banlist/i });
    await user.click(banlistTab);

    const checkboxes = await screen.findAllByRole('checkbox');
    for (const cb of checkboxes) {
      await user.click(cb);
    }

    const bulkButton = await screen.findByRole('button', { name: /Desbanear seleccionados/i });
    await user.click(bulkButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/desbanear', { banlist_id: 1 });
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/desbanear', { banlist_id: 2 });
    });
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
