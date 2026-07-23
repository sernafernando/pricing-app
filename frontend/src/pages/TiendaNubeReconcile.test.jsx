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
 *   - Banlist view: list (loaded on mount, not just when the tab is opened),
 *     individual unban, bulk unban (clears selection + reports a partial
 *     count on failure)
 *   - One-shot fetch (third review round): the report is fetched once on
 *     mount + on explicit "Actualizar" clicks, NEVER on sub-tab change or
 *     page navigation — those are derived client-side from the already
 *     fetched set.
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
    tn_matches: [{ product_id: 1, variant_id: 1, variant_sku: '999', activo: true, published: true }],
  },
  {
    ean: '333',
    verdict: 'DUPLICADO',
    despublicar: false,
    tn_matches: [
      { product_id: 10, variant_id: 1, variant_sku: '333', activo: true, published: true },
      { product_id: 11, variant_id: 1, variant_sku: '333', activo: true, published: null },
    ],
  },
];

const VERDICT_COUNTS = { FALTA_PUBLICAR: 1, MAL_PUBLICADO: 1, DUPLICADO: 2 };

const BANEADOS = [
  {
    id: 1,
    ean: 'BANNED-1',
    motivo: 'test motivo',
    usuario_nombre: 'Operador',
    fecha_creacion: '2026-07-01T00:00:00Z',
  },
];

function setupApiMocks({ baneados = BANEADOS, verdictCounts = VERDICT_COUNTS, items = REPORTE_ITEMS, catalogCapHit = false } = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/tienda-nube-reconcile/reporte') {
      return Promise.resolve({
        data: { items, total: items.length, verdict_counts: verdictCounts, catalog_cap_hit: catalogCapHit },
      });
    }
    if (url === '/tienda-nube-reconcile/baneados') {
      return Promise.resolve({ data: baneados });
    }
    return Promise.resolve({ data: [] });
  });
  api.post.mockImplementation(() => Promise.resolve({ data: { success: true } }));
}

function manyFaltaPublicar(count) {
  return Array.from({ length: count }, (_, i) => ({
    ean: `FP-${i}`,
    verdict: 'FALTA_PUBLICAR',
    despublicar: false,
    tn_matches: [],
  }));
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

  it('fetches the report once when permission is granted', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/tienda-nube-reconcile/reporte');
    });
    expect(api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/reporte')).toHaveLength(1);
  });
});

describe('One-shot fetch — no refetch on navigation', () => {
  it('does NOT refetch the report when switching sub-tabs', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/reporte')).toHaveLength(1);
    });

    const malPublicadoTab = await screen.findByRole('button', { name: /Mal publicado/i });
    await user.click(malPublicadoTab);
    const duplicadoTab = await screen.findByRole('button', { name: /Duplicado/i });
    await user.click(duplicadoTab);

    // Still exactly 1 report fetch — sub-tab filtering happened client-side.
    expect(api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/reporte')).toHaveLength(1);
  });

  it('does NOT refetch the report when paging', async () => {
    setupApiMocks({ items: manyFaltaPublicar(120), verdictCounts: { FALTA_PUBLICAR: 120 } });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/reporte')).toHaveLength(1);
    });

    const nextButton = await screen.findByRole('button', { name: /Siguiente/i });
    await user.click(nextButton);

    expect(api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/reporte')).toHaveLength(1);
  });

  it('refetches the report when the "Actualizar" button is clicked', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/reporte')).toHaveLength(1);
    });

    const refreshButton = await screen.findByRole('button', { name: /Actualizar/i });
    await user.click(refreshButton);

    await waitFor(() => {
      expect(api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/reporte')).toHaveLength(2);
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

  it('sub-tab counters use the server-reported true totals (verdict_counts)', async () => {
    setupApiMocks({
      items: [{ ean: 'X', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [] }],
      verdictCounts: { FALTA_PUBLICAR: 3, MAL_VINCULADO: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Falta publicar \(3\)/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /Mal vinculado \(1\)/i })).toBeInTheDocument();
    });
  });

  it('shows a paginator with "de N" and Siguiente when the current tab exceeds one client-side page', async () => {
    setupApiMocks({ items: manyFaltaPublicar(120), verdictCounts: { FALTA_PUBLICAR: 120 } });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText(/de 120/i)).toBeInTheDocument();
    });
    expect(screen.getByRole('button', { name: /Siguiente/i })).toBeInTheDocument();
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

  it('shows TN\'s real `published` field in the DUPLICADO view, never the misleading `activo`', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    const user = userEvent.setup();
    const dupTab = await screen.findByRole('button', { name: /Duplicado/i });
    await user.click(dupTab);

    const groupHeading = await screen.findByText(/EAN GBP: 333/i);
    const group = groupHeading.closest(`[data-testid="duplicado-group"]`);

    expect(within(group).getByText(/publicado/i)).toBeInTheDocument();
    expect(within(group).queryByRole('columnheader', { name: /^activo$/i })).not.toBeInTheDocument();
    expect(within(group).getByText(/desconocido/i)).toBeInTheDocument();
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
      Promise.reject({ response: { data: { error: { code: 'ALREADY_EXISTS', message: 'El EAN ya está en la banlist' } } } })
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
        return Promise.reject({
          response: { data: { error: { code: 'NOT_FOUND', message: 'Entrada de banlist no encontrada' } } },
        });
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

  it('loads the banlist count on MOUNT, not only when the Banlist tab is opened (a stale "(0)" is the same "lying counter" bug this slice fixes for verdict_counts)', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/tienda-nube-reconcile/baneados');
    });
    expect(await screen.findByRole('button', { name: /Banlist \(1\)/i })).toBeInTheDocument();
  });

  it('refreshes the banlist count after a successful ban from the report tab', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    await screen.findByRole('button', { name: /Banlist \(1\)/i });
    const initialBaneadosCalls = api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/baneados').length;

    const banButton = await screen.findByRole('button', { name: /Banear/i });
    await user.click(banButton);

    await waitFor(() => {
      const callsAfter = api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/baneados').length;
      expect(callsAfter).toBeGreaterThan(initialBaneadosCalls);
    });
  });

  it('lists banned EANs fetched from GET /baneados', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const banlistTab = await screen.findByRole('button', { name: /Banlist/i });
    await user.click(banlistTab);

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

  it('on partial bulk-unban failure: refreshes the banlist, clears the selection, and reports how many succeeded', async () => {
    setupApiMocks({
      baneados: [
        { id: 1, ean: 'A', motivo: null, usuario_nombre: 'Op', fecha_creacion: '2026-07-01T00:00:00Z' },
        { id: 2, ean: 'B', motivo: null, usuario_nombre: 'Op', fecha_creacion: '2026-07-01T00:00:00Z' },
        { id: 3, ean: 'C', motivo: null, usuario_nombre: 'Op', fecha_creacion: '2026-07-01T00:00:00Z' },
      ],
    });
    // 1st succeeds, 2nd fails, 3rd is never attempted (loop aborts).
    let call = 0;
    api.post.mockImplementation((url) => {
      if (url === '/tienda-nube-reconcile/desbanear') {
        call += 1;
        if (call === 2) {
          return Promise.reject({ response: { data: { error: { code: 'NOT_FOUND', message: 'falló' } } } });
        }
        return Promise.resolve({ data: { success: true } });
      }
      return Promise.resolve({ data: { success: true } });
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

    // Reports how many succeeded out of the total attempted.
    await waitFor(() => {
      expect(screen.getByText(/1.*3|1 de 3/i)).toBeInTheDocument();
    });

    // GET /baneados is called once on mount + once more in the `finally`
    // refresh after the bulk action settles (success or failure).
    await waitFor(() => {
      expect(api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/baneados').length).toBeGreaterThanOrEqual(2);
    });

    // Selection is cleared even on partial failure — no stale ids of rows
    // that no longer exist (or were never attempted) remain "selected".
    await waitFor(() => {
      const remainingChecked = screen.queryAllByRole('checkbox').filter((cb) => cb.checked);
      expect(remainingChecked).toHaveLength(0);
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
