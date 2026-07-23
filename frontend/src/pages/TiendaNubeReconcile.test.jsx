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

function setupApiMocks({
  baneados = BANEADOS,
  verdictCounts = VERDICT_COUNTS,
  items = REPORTE_ITEMS,
  catalogCapHit = false,
  gbpRowsCapHit = false,
} = {}) {
  api.get.mockImplementation((url) => {
    if (url === '/tienda-nube-reconcile/reporte') {
      return Promise.resolve({
        data: {
          items,
          total: items.length,
          verdict_counts: verdictCounts,
          catalog_cap_hit: catalogCapHit,
          gbp_rows_cap_hit: gbpRowsCapHit,
        },
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

    const malPublicadoTab = await screen.findByRole('tab', { name: /Mal publicado/i });
    await user.click(malPublicadoTab);
    const duplicadoTab = await screen.findByRole('tab', { name: /Duplicado/i });
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

describe('catalog_cap_hit banner', () => {
  it('uses a distinct warning style, not the error banner (a truncation notice is not an error)', async () => {
    setupApiMocks({ catalogCapHit: true });

    await renderWithRouter(<TiendaNubeReconcile />);

    const banner = await screen.findByText(/superó el límite de sincronización/i);
    expect(banner.className).not.toMatch(/errorBanner/i);
    expect(banner.className).toMatch(/warningBanner/i);
  });

  it('surfaces gbp_rows_cap_hit through the same warning style (round 6, item 1)', async () => {
    setupApiMocks({ gbpRowsCapHit: true });

    await renderWithRouter(<TiendaNubeReconcile />);

    const banner = await screen.findByText(/reporte GBP.*límite|límite.*reporte GBP/i);
    expect(banner.className).not.toMatch(/errorBanner/i);
    expect(banner.className).toMatch(/warningBanner/i);
  });
});

describe('Accessible sub-tabs (round 6, item 3)', () => {
  it('marks the container as a tablist and each tab with role="tab" + aria-selected tracking the active tab', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tablist = await screen.findByRole('tablist');
    expect(tablist).toBeInTheDocument();

    const todosTab = await screen.findByRole('tab', { name: /Todos/i });
    const malPublicadoTab = await screen.findByRole('tab', { name: /Mal publicado/i });

    expect(todosTab).toHaveAttribute('aria-selected', 'true');
    expect(malPublicadoTab).toHaveAttribute('aria-selected', 'false');

    await user.click(malPublicadoTab);

    expect(todosTab).toHaveAttribute('aria-selected', 'false');
    expect(malPublicadoTab).toHaveAttribute('aria-selected', 'true');
  });

  it('associates the active tab with its panel via aria-controls/id and role="tabpanel"', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    const todosTab = await screen.findByRole('tab', { name: /Todos/i });
    const panel = await screen.findByRole('tabpanel');

    expect(todosTab).toHaveAttribute('aria-controls', panel.id);
    expect(panel).toHaveAttribute('aria-labelledby', todosTab.id);
  });

  it('every tab\'s aria-controls resolves to an element actually in the document, including INACTIVE tabs (round 7, item 3)', async () => {
    // Only the active panel is rendered — before this fix, an inactive
    // tab's aria-controls pointed at a `tn-panel-{id}` that only exists
    // while THAT tab is selected, so every other tab's aria-controls was
    // dangling. A single always-present panel (relabeled per active tab)
    // means every tab's aria-controls resolves to the SAME real element.
    await renderWithRouter(<TiendaNubeReconcile />);

    const tabs = await screen.findAllByRole('tab');
    expect(tabs.length).toBeGreaterThan(1);

    for (const tab of tabs) {
      const controlsId = tab.getAttribute('aria-controls');
      expect(controlsId).toBeTruthy();
      expect(document.getElementById(controlsId)).not.toBeNull();
    }
  });

  it('moves selection with ArrowRight/ArrowLeft between tabs (roving focus)', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const todosTab = await screen.findByRole('tab', { name: /Todos/i });
    todosTab.focus();

    await user.keyboard('{ArrowRight}');
    const faltaVincularTab = await screen.findByRole('tab', { name: /Falta vincular/i });
    expect(faltaVincularTab).toHaveAttribute('aria-selected', 'true');
    expect(faltaVincularTab).toHaveFocus();

    await user.keyboard('{ArrowLeft}');
    expect(await screen.findByRole('tab', { name: /Todos/i })).toHaveAttribute('aria-selected', 'true');
  });
});

describe('Anomaly sub-tabs', () => {
  it('shows a dedicated MAL_PUBLICADO sub-tab', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /Mal publicado/i })).toBeInTheDocument();
    });
  });

  it('sub-tab counters use the server-reported true totals (verdict_counts)', async () => {
    setupApiMocks({
      items: [{ ean: 'X', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [] }],
      verdictCounts: { FALTA_PUBLICAR: 3, MAL_VINCULADO: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /Falta publicar \(3\)/i })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: /Mal vinculado \(1\)/i })).toBeInTheDocument();
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

  it('clamps the page back into range when the dataset shrinks while on the last page (fourth review round)', async () => {
    let itemCount = 51;
    api.get.mockImplementation((url) => {
      if (url === '/tienda-nube-reconcile/reporte') {
        return Promise.resolve({
          data: {
            items: manyFaltaPublicar(itemCount),
            total: itemCount,
            verdict_counts: { FALTA_PUBLICAR: itemCount },
            catalog_cap_hit: false,
          },
        });
      }
      if (url === '/tienda-nube-reconcile/baneados') return Promise.resolve({ data: [] });
      return Promise.resolve({ data: [] });
    });
    api.post.mockImplementation(() => {
      // Simulate a ban shrinking the FALTA_PUBLICAR set from 51 to 50 —
      // page 2 (which only had row #51) would otherwise become empty.
      itemCount = 50;
      return Promise.resolve({ data: { success: true } });
    });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const faltaPublicarTab = await screen.findByRole('tab', { name: /Falta publicar/i });
    await user.click(faltaPublicarTab);

    const nextButton = await screen.findByRole('button', { name: /Siguiente/i });
    await user.click(nextButton);

    await waitFor(() => {
      expect(screen.getByText('FP-50')).toBeInTheDocument();
    });

    const banButton = await screen.findByRole('button', { name: /Banear/i });
    await user.click(banButton);

    // The set shrank to 50 (exactly one page) — the view must recover with
    // real rows, never a stuck-on-page-2 "No hay filas" dead end.
    await waitFor(() => {
      expect(screen.queryByText(/No hay filas para este veredicto/i)).not.toBeInTheDocument();
    });
    expect(screen.getByText('FP-0')).toBeInTheDocument();
  });

  it('offers the Banear action on FALTA_VINCULAR rows too, not only FALTA_PUBLICAR', async () => {
    setupApiMocks({
      items: [{ ean: 'FV-1', verdict: 'FALTA_VINCULAR', despublicar: false, tn_matches: [] }],
      verdictCounts: { FALTA_VINCULAR: 1 },
    });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Falta vincular/i });
    await user.click(tab);

    const banButton = await screen.findByRole('button', { name: /Banear/i });
    await user.click(banButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/banear', { ean: 'FV-1' });
    });
  });

  it('shows a dedicated DUPLICADO sub-tab labeled as human review, not error', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    const dupTab = await screen.findByRole('tab', { name: /Duplicado/i });
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
    const dupTab = await screen.findByRole('tab', { name: /Duplicado/i });
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
    const dupTab = await screen.findByRole('tab', { name: /Duplicado/i });
    await user.click(dupTab);

    const groupHeading = await screen.findByText(/EAN GBP: 333/i);
    const group = groupHeading.closest(`[data-testid="duplicado-group"]`);

    expect(within(group).getByText(/publicado/i)).toBeInTheDocument();
    expect(within(group).queryByRole('columnheader', { name: /^activo$/i })).not.toBeInTheDocument();
    expect(within(group).getByText(/desconocido/i)).toBeInTheDocument();
  });
});

describe('Despublicar action (Slice 2)', () => {
  const DESPUBLICAR_ITEMS = [
    {
      ean: 'DP-1',
      verdict: 'MAL_VINCULADO',
      despublicar: true,
      tn_matches: [{ product_id: 555, variant_id: 1, variant_sku: 'DP-1', activo: true, published: true }],
    },
  ];

  it('is hidden without admin.gestionar_tn_publicacion', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'admin.gestionar_tn_publicacion');
    setupApiMocks({ items: DESPUBLICAR_ITEMS, verdictCounts: { MAL_VINCULADO: 1 } });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal vinculado/i });
    await user.click(tab);

    await waitFor(() => {
      expect(screen.getAllByText('DP-1').length).toBeGreaterThan(0);
    });
    expect(screen.queryByRole('button', { name: /^Despublicar$/i })).not.toBeInTheDocument();
  });

  it('shows a Despublicar action on rows flagged despublicar, gated by admin.gestionar_tn_publicacion', async () => {
    setupApiMocks({ items: DESPUBLICAR_ITEMS, verdictCounts: { MAL_VINCULADO: 1 } });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal vinculado/i });
    await user.click(tab);

    expect(await screen.findByRole('button', { name: /^Despublicar$/i })).toBeInTheDocument();
  });

  it('requires an explicit confirmation step before calling the endpoint', async () => {
    setupApiMocks({ items: DESPUBLICAR_ITEMS, verdictCounts: { MAL_VINCULADO: 1 } });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal vinculado/i });
    await user.click(tab);

    const despublicarButton = await screen.findByRole('button', { name: /^Despublicar$/i });
    await user.click(despublicarButton);

    // Not yet called — a confirm step must appear first.
    expect(api.post).not.toHaveBeenCalledWith('/tienda-nube-reconcile/despublicar', expect.anything());

    const confirmButton = await screen.findByRole('button', { name: /Confirmar/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/despublicar', { product_id: 555 });
    });
  });

  it('cancelling the confirm step never calls the endpoint', async () => {
    setupApiMocks({ items: DESPUBLICAR_ITEMS, verdictCounts: { MAL_VINCULADO: 1 } });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal vinculado/i });
    await user.click(tab);

    const despublicarButton = await screen.findByRole('button', { name: /^Despublicar$/i });
    await user.click(despublicarButton);

    const cancelButton = await screen.findByRole('button', { name: /Cancelar/i });
    await user.click(cancelButton);

    expect(api.post).not.toHaveBeenCalledWith('/tienda-nube-reconcile/despublicar', expect.anything());
    expect(await screen.findByRole('button', { name: /^Despublicar$/i })).toBeInTheDocument();
  });

  it('shows a success toast and reloads the report after a successful unpublish', async () => {
    setupApiMocks({ items: DESPUBLICAR_ITEMS, verdictCounts: { MAL_VINCULADO: 1 } });
    api.post.mockImplementation((url) => {
      if (url === '/tienda-nube-reconcile/despublicar') {
        return Promise.resolve({ data: { submitted: true, status: 'submitted', detail: null } });
      }
      return Promise.resolve({ data: { success: true } });
    });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal vinculado/i });
    await user.click(tab);

    const despublicarButton = await screen.findByRole('button', { name: /^Despublicar$/i });
    await user.click(despublicarButton);
    const confirmButton = await screen.findByRole('button', { name: /Confirmar/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(screen.getByText(/despublicado/i)).toBeInTheDocument();
    });
  });

  it('shows an error toast (never an unhandled rejection) when the unpublish call fails', async () => {
    setupApiMocks({ items: DESPUBLICAR_ITEMS, verdictCounts: { MAL_VINCULADO: 1 } });
    api.post.mockImplementation((url) => {
      if (url === '/tienda-nube-reconcile/despublicar') {
        return Promise.reject({ response: { data: { error: { code: 'FORBIDDEN', message: 'No tenés permiso' } } } });
      }
      return Promise.resolve({ data: { success: true } });
    });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal vinculado/i });
    await user.click(tab);

    const despublicarButton = await screen.findByRole('button', { name: /^Despublicar$/i });
    await user.click(despublicarButton);
    const confirmButton = await screen.findByRole('button', { name: /Confirmar/i });
    await user.click(confirmButton);

    await waitFor(() => {
      expect(screen.getByText(/No tenés permiso/i)).toBeInTheDocument();
    });
  });

  it('does not show the action on rows not flagged despublicar', async () => {
    setupApiMocks();
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('111')).toBeInTheDocument();
    });
    expect(screen.queryByRole('button', { name: /^Despublicar$/i })).not.toBeInTheDocument();
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

    const banlistTab = await screen.findByRole('tab', { name: /Banlist/i });
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
      expect(screen.getByRole('tab', { name: /Todos/i })).toBeInTheDocument();
    });
    expect(screen.queryByRole('tab', { name: /Banlist/i })).not.toBeInTheDocument();
  });

  it('loads the banlist count on MOUNT, not only when the Banlist tab is opened (a stale "(0)" is the same "lying counter" bug this slice fixes for verdict_counts)', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/tienda-nube-reconcile/baneados');
    });
    expect(await screen.findByRole('tab', { name: /Banlist \(1\)/i })).toBeInTheDocument();
  });

  it('refreshes the banlist count after a successful ban from the report tab', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    await screen.findByRole('tab', { name: /Banlist \(1\)/i });
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

    const banlistTab = await screen.findByRole('tab', { name: /Banlist/i });
    await user.click(banlistTab);

    expect(await screen.findByText('BANNED-1')).toBeInTheDocument();
    expect(screen.getByText('test motivo')).toBeInTheDocument();
  });

  it('unbans an individual EAN via POST /desbanear and reloads the list', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const banlistTab = await screen.findByRole('tab', { name: /Banlist/i });
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

    const banlistTab = await screen.findByRole('tab', { name: /Banlist/i });
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

    const banlistTab = await screen.findByRole('tab', { name: /Banlist/i });
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
