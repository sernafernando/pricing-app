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
import { selectTabItems } from './tiendaNubeReconcileHelpers';
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

// Despublicar/Editar en TN live behind the Acciones column's overflow menu
// (PR-A of the table redesign); Banear is a visible button next to the
// primary action (tn-categorias-descubribles fix, defect 2) and is clicked
// directly — see `screen.findByRole('button', { name: 'Banear' })` below.
async function openRowMenu(user, ean) {
  const trigger = await screen.findByRole('button', { name: new RegExp(`Más acciones para ${ean}`, 'i') });
  await user.click(trigger);
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

    await user.click(await screen.findByRole('button', { name: 'Banear' }));

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

    await user.click(await screen.findByRole('button', { name: 'Banear' }));

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

  it('shows all conflicting TN matches in a DUPLICADO group with no pre-selected, highlighted, or recommended match', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    const user = userEvent.setup();
    const dupTab = await screen.findByRole('tab', { name: /Duplicado/i });
    await user.click(dupTab);

    const group = await screen.findByTestId('duplicado-group');
    expect(within(group).getByTestId('duplicado-group-header')).toHaveTextContent('333');

    // Both conflicting TN matches are present, bare product_id/variant_id
    // pair (no redundant "product_id: N" prefix — pass C card redesign).
    const matchRows = within(group).getAllByTestId('duplicado-match-row');
    expect(matchRows).toHaveLength(2);
    expect(matchRows.map((r) => r.textContent).some((t) => /10\s*\/\s*1/.test(t))).toBe(true);
    expect(matchRows.map((r) => r.textContent).some((t) => /11\s*\/\s*1/.test(t))).toBe(true);

    // Scoped to the DUPLICADO group specifically: no match carries a
    // selection/highlight/recommendation affordance (radio, checkbox, a
    // "selected"/"recommended" row class, or an aria-selected row).
    expect(within(group).queryAllByRole('radio')).toHaveLength(0);
    expect(within(group).queryAllByRole('checkbox')).toHaveLength(0);
    for (const matchRow of matchRows) {
      expect(matchRow).not.toHaveAttribute('aria-selected', 'true');
      expect(matchRow.className || '').not.toMatch(/selected|recommended|highlight/i);
    }
  });

  it('shows TN\'s real `published` field in the DUPLICADO view, never the misleading `activo`', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    const user = userEvent.setup();
    const dupTab = await screen.findByRole('tab', { name: /Duplicado/i });
    await user.click(dupTab);

    const group = await screen.findByTestId('duplicado-group');

    expect(within(group).getByText(/publicado/i)).toBeInTheDocument();
    expect(within(group).queryByRole('columnheader', { name: /^activo$/i })).not.toBeInTheDocument();
    expect(within(group).getByText(/desconocido/i)).toBeInTheDocument();
  });
});

describe('POR_CORREGIR verdict (match accuracy)', () => {
  it('shows a dedicated POR_CORREGIR sub-tab, distinct from OK/MAL_PUBLICADO', async () => {
    setupApiMocks({
      items: [
        {
          ean: '023942321477',
          verdict: 'POR_CORREGIR',
          despublicar: false,
          tn_matches: [],
          tn_presence: 'published',
        },
      ],
      verdictCounts: { POR_CORREGIR: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Por corregir \(1\)/i });
    expect(tab).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(tab);

    await waitFor(() => {
      expect(screen.getByText('023942321477')).toBeInTheDocument();
    });
  });

  it('does not mix POR_CORREGIR rows into the MAL_PUBLICADO sub-tab', async () => {
    setupApiMocks({
      items: [
        { ean: 'PC-1', verdict: 'POR_CORREGIR', despublicar: false, tn_matches: [], tn_presence: 'published' },
        { ean: 'MP-1', verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [], tn_presence: 'published' },
      ],
      verdictCounts: { POR_CORREGIR: 1, MAL_PUBLICADO: 1 },
    });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const malPublicadoTab = await screen.findByRole('tab', { name: /Mal publicado/i });
    await user.click(malPublicadoTab);

    await waitFor(() => {
      expect(screen.getByText('MP-1')).toBeInTheDocument();
    });
    expect(screen.queryByText('PC-1')).not.toBeInTheDocument();
  });
});

describe('tn_presence display', () => {
  it('renders published/draft/unknown/not_in_tn distinctly, replacing the ambiguous "Desconocido"', async () => {
    setupApiMocks({
      items: [
        { ean: 'A', verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [], tn_presence: 'published' },
        { ean: 'B', verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [], tn_presence: 'draft' },
        { ean: 'C', verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [], tn_presence: 'unknown' },
        { ean: 'D', verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [], tn_presence: 'not_in_tn' },
      ],
      verdictCounts: { MAL_PUBLICADO: 4 },
    });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal publicado/i });
    await user.click(tab);

    await waitFor(() => {
      expect(screen.getByText('A')).toBeInTheDocument();
    });

    const rows = screen.getAllByRole('row').filter((r) => r.textContent.match(/^[ABCD]/));
    expect(rows).toHaveLength(4);
    const texts = rows.map((r) => r.textContent);
    // Four distinct, non-ambiguous presence labels — no bare "Desconocido".
    expect(new Set(texts).size).toBe(4);
    expect(texts.some((t) => /no está/i.test(t))).toBe(true);
    // Pass B: the short label is backed by the full explanatory sentence as
    // a tooltip, so the detail isn't lost, only demoted from cell text.
    const notInTnLabel = rows.find((r) => /^D/.test(r.textContent)).querySelector(`[title]`);
    expect(notInTnLabel).toHaveAttribute('title', expect.stringMatching(/no está en tienda nube/i));
  });

  it('splits DUPLICADO rows by tn_presence: "sin presencia en TN" vs "existe en TN"', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'DUP-A',
          verdict: 'DUPLICADO',
          despublicar: false,
          tn_matches: [{ product_id: 1, variant_id: 1, variant_sku: 'DUP-A', activo: true, published: true }],
          tn_presence: 'published',
        },
        {
          ean: 'DUP-B',
          verdict: 'DUPLICADO',
          despublicar: false,
          tn_matches: [],
          tn_presence: 'not_in_tn',
        },
      ],
      verdictCounts: { DUPLICADO: 2 },
    });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const dupTab = await screen.findByRole('tab', { name: /Duplicado/i });
    await user.click(dupTab);

    await waitFor(() => {
      expect(screen.getAllByText(/DUP-A/).length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/sin presencia en TN/i)).toBeInTheDocument();
    expect(screen.getByText(/^existe en TN$/i)).toBeInTheDocument();
  });
});

describe('tn_presence "unknown" relabel + sync trigger (Slice 3)', () => {
  const UNKNOWN_ITEM = {
    ean: 'UNK-1',
    verdict: 'MAL_PUBLICADO',
    despublicar: false,
    tn_matches: [],
    tn_presence: 'unknown',
  };

  it('communicates the row exists in TN but its publish state is not synced, not that presence is unknown', async () => {
    setupApiMocks({ items: [UNKNOWN_ITEM], verdictCounts: { MAL_PUBLICADO: 1 } });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal publicado/i });
    await user.click(tab);

    await waitFor(() => {
      expect(screen.getAllByText('UNK-1').length).toBeGreaterThan(0);
    });
    expect(screen.queryByText('Presencia en TN desconocida')).not.toBeInTheDocument();
    expect(screen.queryByText(/desconocid/i)).not.toBeInTheDocument();
    // Pass B: the cell shows a short label ("Sin sincronizar"), with the
    // full "publish state not synced" sentence carried as its tooltip — the
    // actionable truth still reaches the operator, just not as raw cell text.
    expect(screen.getByText('Sin sincronizar')).toBeInTheDocument();
    expect(screen.getByTitle(/publicaci[oó]n.*no.*sincroniz/i)).toBeInTheDocument();
  });

  it('offers a control to trigger the existing sync endpoint, gated by admin.gestionar_tn_publicacion', async () => {
    setupApiMocks({ items: [UNKNOWN_ITEM], verdictCounts: { MAL_PUBLICADO: 1 } });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal publicado/i });
    await user.click(tab);

    const syncButton = await screen.findByRole('button', { name: /sincronizar/i });
    await user.click(syncButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube/sync');
    });
  });

  it('hides the sync control without admin.gestionar_tn_publicacion, keeping only the explanatory label', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'admin.gestionar_tn_publicacion');
    setupApiMocks({ items: [UNKNOWN_ITEM], verdictCounts: { MAL_PUBLICADO: 1 } });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal publicado/i });
    await user.click(tab);

    await waitFor(() => {
      expect(screen.getAllByText('UNK-1').length).toBeGreaterThan(0);
    });
    expect(screen.queryByRole('button', { name: /sincronizar/i })).not.toBeInTheDocument();
    expect(screen.getByText('Sin sincronizar')).toBeInTheDocument();
    expect(screen.getByTitle(/publicaci[oó]n.*no.*sincroniz/i)).toBeInTheDocument();
  });

  it('renders a single global trigger (not one per row) even with many unknown rows, and never inside a row cell', async () => {
    const manyUnknown = Array.from({ length: 5 }, (_, i) => ({
      ean: `UNK-${i}`,
      verdict: 'MAL_PUBLICADO',
      despublicar: false,
      tn_matches: [],
      tn_presence: 'unknown',
    }));
    setupApiMocks({ items: manyUnknown, verdictCounts: { MAL_PUBLICADO: 5 } });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal publicado/i });
    await user.click(tab);

    await waitFor(() => {
      expect(screen.getAllByText('UNK-0').length).toBeGreaterThan(0);
    });
    // Exactly one trigger for the whole page, describing the FULL catalog
    // scope — never N row-scoped buttons for one global side effect.
    const syncButtons = screen.getAllByRole('button', { name: /sincronizar cat[aá]logo/i });
    expect(syncButtons).toHaveLength(1);
    // It must live in the page header, not inside the results table (which
    // is where the previous, since-removed per-row control used to sit).
    expect(syncButtons[0].closest('table')).toBeNull();
  });

  it('shows an error toast and never leaves an unhandled rejection when the sync call fails', async () => {
    setupApiMocks({ items: [UNKNOWN_ITEM], verdictCounts: { MAL_PUBLICADO: 1 } });
    api.post.mockImplementation((url) => {
      if (url === '/tienda-nube/sync') {
        return Promise.reject({ response: { data: { error: { message: 'TN no responde' } } } });
      }
      return Promise.resolve({ data: { success: true } });
    });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal publicado/i });
    await user.click(tab);

    const syncButton = await screen.findByRole('button', { name: /sincronizar cat[aá]logo/i });
    await user.click(syncButton);

    await waitFor(() => {
      expect(screen.getByText('TN no responde')).toBeInTheDocument();
    });
    // Button must recover (never stuck disabled after a failed attempt).
    expect(syncButton).not.toBeDisabled();
  });
});

describe('POR_CORREGIR EAN vs TN SKU (Slice 3)', () => {
  it('renders the GBP EAN and the matched TN SKU side by side', async () => {
    setupApiMocks({
      items: [
        {
          ean: '023942321477',
          verdict: 'POR_CORREGIR',
          despublicar: false,
          tn_matches: [{ product_id: 1, variant_id: 1, variant_sku: '23942321477', activo: true, published: true }],
          tn_presence: 'published',
        },
      ],
      verdictCounts: { POR_CORREGIR: 1 },
    });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Por corregir \(1\)/i });
    await user.click(tab);

    await waitFor(() => {
      expect(screen.getByText(/023942321477/)).toBeInTheDocument();
    });
    expect(screen.getByText(/EAN: 023942321477/)).toBeInTheDocument();
    expect(screen.getByText(/SKU TN: 23942321477/)).toBeInTheDocument();
  });
});

describe('FALTA_VINCULAR matched TN IDs', () => {
  it('shows the matched product_id/variant_id on a FALTA_VINCULAR row', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'FV-IDS',
          verdict: 'FALTA_VINCULAR',
          despublicar: false,
          tn_matches: [],
          tn_presence: 'unknown',
          product_id: 42,
          variant_id: 7,
        },
      ],
      verdictCounts: { FALTA_VINCULAR: 1 },
    });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Falta vincular/i });
    await user.click(tab);

    await waitFor(() => {
      expect(screen.getByText(/product_id: 42 \/ variant_id: 7/)).toBeInTheDocument();
    });
  });

  it('shows no broken/undefined display when matched IDs are null', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'FV-NOIDS',
          verdict: 'FALTA_VINCULAR',
          despublicar: false,
          tn_matches: [],
          tn_presence: 'not_in_tn',
          product_id: null,
          variant_id: null,
        },
      ],
      verdictCounts: { FALTA_VINCULAR: 1 },
    });

    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Falta vincular/i });
    await user.click(tab);

    await waitFor(() => {
      expect(screen.getByText('FV-NOIDS')).toBeInTheDocument();
    });
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument();
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

    await openRowMenu(user, 'DP-1');
    expect(screen.getByRole('menuitem', { name: 'Despublicar' })).toBeInTheDocument();
  });

  it('requires an explicit confirmation step before calling the endpoint', async () => {
    setupApiMocks({ items: DESPUBLICAR_ITEMS, verdictCounts: { MAL_VINCULADO: 1 } });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    const tab = await screen.findByRole('tab', { name: /Mal vinculado/i });
    await user.click(tab);

    await openRowMenu(user, 'DP-1');
    await user.click(screen.getByRole('menuitem', { name: 'Despublicar' }));

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

    await openRowMenu(user, 'DP-1');
    await user.click(screen.getByRole('menuitem', { name: 'Despublicar' }));

    const cancelButton = await screen.findByRole('button', { name: /Cancelar/i });
    await user.click(cancelButton);

    expect(api.post).not.toHaveBeenCalledWith('/tienda-nube-reconcile/despublicar', expect.anything());
    await openRowMenu(user, 'DP-1');
    expect(screen.getByRole('menuitem', { name: 'Despublicar' })).toBeInTheDocument();
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

    await openRowMenu(user, 'DP-1');
    await user.click(screen.getByRole('menuitem', { name: 'Despublicar' }));
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

    await openRowMenu(user, 'DP-1');
    await user.click(screen.getByRole('menuitem', { name: 'Despublicar' }));
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
    expect(screen.queryByRole('menuitem', { name: 'Despublicar' })).not.toBeInTheDocument();
  });
});

describe('Ban/unban error handling', () => {
  it('shows a success toast and reloads the report after a successful ban', async () => {
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    await user.click(await screen.findByRole('button', { name: 'Banear' }));

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

    await user.click(await screen.findByRole('button', { name: 'Banear' }));

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

    await user.click(await screen.findByRole('button', { name: 'Banear' }));

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

    // Esperar las 2 casillas: `findAllByRole` resuelve apenas
    // aparece UNA, y si el DOM todavía está pintando filas el loop de
    // abajo clickea de menos y el conteo del toast cambia.
    await waitFor(() => expect(screen.getAllByRole('checkbox')).toHaveLength(2));
    const checkboxes = screen.getAllByRole('checkbox');
    for (const cb of checkboxes) {
      await user.click(cb);
    }

    const bulkButton = await screen.findByRole('button', { name: /Desbanear seleccionados/i });
    await user.click(bulkButton);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/desbanear', { banlist_id: 1 });
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/desbanear', { banlist_id: 2 });
    });

    // Full-success toast shape — was previously only exercised indirectly;
    // the partial-failure shape below has its own dedicated assertion.
    await waitFor(() => {
      expect(screen.getByText(/2 EAN\(s\) desbaneados exitosamente/i)).toBeInTheDocument();
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

    // Esperar las 3 casillas: `findAllByRole` resuelve apenas
    // aparece UNA, y si el DOM todavía está pintando filas el loop de
    // abajo clickea de menos y el conteo del toast cambia.
    await waitFor(() => expect(screen.getAllByRole('checkbox')).toHaveLength(3));
    const checkboxes = screen.getAllByRole('checkbox');
    for (const cb of checkboxes) {
      await user.click(cb);
    }

    const bulkButton = await screen.findByRole('button', { name: /Desbanear seleccionados/i });
    await user.click(bulkButton);

    // Reports how many succeeded out of the total attempted.
    // El texto exacto, no `/1.*3/`: ese regex también matchea la hora del
    // encabezado ("Actualizado 04:13 p. m." contiene 1 y luego 3), así que
    // el test fallaba SEGÚN EL RELOJ — verde 16:20, rojo 16:13.
    await waitFor(() => {
      expect(screen.getByText('1 de 3 desbaneados. falló')).toBeInTheDocument();
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

describe('Product identity in rows (rebuilt UI)', () => {
  const LONG_DESC_TEXT = 'Auricular inalámbrico con cancelación activa de ruido, 30 horas de batería, estuche de carga rápida USB-C, resistencia al agua IPX4 y micrófono dual para llamadas nítidas en cualquier ambiente.';
  const ENRICHED_ITEMS = [
    {
      ean: 'RICH-1',
      verdict: 'MAL_PUBLICADO',
      despublicar: false,
      tn_presence: 'published',
      tn_matches: [
        {
          product_id: 123,
          variant_id: 456,
          variant_sku: 'RICH-1',
          activo: true,
          published: true,
          tn_admin_url: 'https://admin.tiendanube.com/products/123',
        },
      ],
      ml_title: 'Auricular Bluetooth XYZ',
      ml_desc: `<p>${LONG_DESC_TEXT}</p>`,
      images: ['https://example.com/th.jpg'],
      // Row-level tn_admin_url intentionally null: the link MUST come from
      // the match's own tn_admin_url, never a row-level single link.
      tn_admin_url: null,
    },
  ];

  function setupEnriched() {
    setupApiMocks({ items: ENRICHED_ITEMS, verdictCounts: { MAL_PUBLICADO: 1 } });
  }

  it('shows the product title and a truncated description that expands on click', async () => {
    setupEnriched();
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('Auricular Bluetooth XYZ')).toBeInTheDocument();
    });

    // Truncated (ends with an ellipsis), full text available as tooltip.
    const descToggle = screen.getByRole('button', { name: /expandir descripción/i });
    expect(descToggle.textContent.endsWith('…')).toBe(true);
    expect(descToggle).toHaveAttribute('title', LONG_DESC_TEXT);
    expect(descToggle).toHaveAttribute('aria-expanded', 'false');

    await user.click(descToggle);

    const expanded = screen.getByRole('button', { name: /contraer descripción/i });
    expect(expanded).toHaveAttribute('aria-expanded', 'true');
    expect(expanded.textContent).toBe(LONG_DESC_TEXT);
  });

  it('renders a thumbnail from images[0] with an accessible role/label so the operator can recognize the product', async () => {
    setupEnriched();
    await renderWithRouter(<TiendaNubeReconcile />);

    // The focusable wrapper is announced as an image with a descriptive
    // label (a bare focusable span would announce nothing); the inner <img>
    // is presentational.
    const thumbWrap = await screen.findByRole('img', { name: 'Miniatura de Auricular Bluetooth XYZ' });
    expect(thumbWrap).toHaveAttribute('tabindex', '0');
    expect(thumbWrap.querySelector('img')).toHaveAttribute('src', 'https://example.com/th.jpg');
  });

  it('shows the TN product_id/variant_id of each match directly in the row', async () => {
    setupEnriched();
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('123/456')).toBeInTheDocument();
    });
  });

  // Coverage added in pass B: the "Coincidencias TN (IDs)" column that used
  // to list EVERY match is gone — the "En Tienda Nube" cell now shows only
  // the primary match's IDs plus a "+N" indicator, so this must be verified
  // explicitly (nothing in the pre-existing suite covered "more than one
  // match" for the general table branch, only for DUPLICADO's own view).
  it('shows a "+N" indicator when a row has more than one TN match (pass B collapse)', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'MULTI-1',
          verdict: 'MAL_PUBLICADO',
          despublicar: false,
          tn_presence: 'published',
          tn_matches: [
            { product_id: 1, variant_id: 1, variant_sku: 'MULTI-1', published: true },
            { product_id: 2, variant_id: 1, variant_sku: 'MULTI-1', published: false },
            { product_id: 3, variant_id: 1, variant_sku: 'MULTI-1', published: false },
          ],
        },
      ],
      verdictCounts: { MAL_PUBLICADO: 1 },
    });
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      // Primary match preferred: the one TN reports as published: true.
      expect(screen.getByText('1/1')).toBeInTheDocument();
    });
    expect(screen.getByText('+2')).toBeInTheDocument();
  });

  it('shows no "+N" indicator for a row with a single TN match', async () => {
    setupEnriched();
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('123/456')).toBeInTheDocument();
    });
    expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
  });

  it('offers "Editar en TN" as a visible link — no menu to discover first', async () => {
    // Was an overflow-menu item; promoted to a visible action because
    // opening the product in TN is the first move on any anomalous row.
    setupEnriched();
    await renderWithRouter(<TiendaNubeReconcile />);

    const link = await screen.findByRole('link', { name: /editar en tn/i });
    expect(link).toHaveAttribute('href', 'https://admin.tiendanube.com/products/123');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('DUPLICADO: renders one "Editar en TN" link PER conflicting match — never a single privileged group link', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'DUP-LINKS',
          verdict: 'DUPLICADO',
          despublicar: false,
          tn_presence: 'published',
          // Row-level url (backend derives it from tn_matches[0]) must NOT
          // surface as a single group-header link — that would implicitly
          // recommend one conflicting row.
          tn_admin_url: 'https://admin.tiendanube.com/products/10',
          tn_matches: [
            {
              product_id: 10,
              variant_id: 1,
              variant_sku: 'DUP-LINKS',
              activo: true,
              published: true,
              tn_admin_url: 'https://admin.tiendanube.com/products/10',
            },
            {
              product_id: 11,
              variant_id: 1,
              variant_sku: 'DUP-LINKS',
              activo: true,
              published: null,
              tn_admin_url: 'https://admin.tiendanube.com/products/11',
            },
          ],
        },
      ],
      verdictCounts: { DUPLICADO: 1 },
    });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    await user.click(await screen.findByRole('tab', { name: /Duplicado/i }));

    const group = await screen.findByTestId('duplicado-group');
    expect(within(group).getByTestId('duplicado-group-header')).toHaveTextContent('DUP-LINKS');

    // Exactly one link per conflicting match, each pointing at ITS product.
    const links = within(group).getAllByRole('link', { name: /editar en tn/i });
    expect(links).toHaveLength(2);
    expect(links.map((l) => l.getAttribute('href')).sort()).toEqual([
      'https://admin.tiendanube.com/products/10',
      'https://admin.tiendanube.com/products/11',
    ]);

    // The group header itself carries NO link — links live only in the
    // per-match rows, so none is privileged.
    const header = within(group).getByTestId('duplicado-group-header');
    expect(within(header).queryByRole('link')).not.toBeInTheDocument();

    // And each match row has exactly one link (its own).
    const matchRows = within(group).getAllByTestId('duplicado-match-row');
    expect(matchRows).toHaveLength(2);
    for (const matchRow of matchRows) {
      expect(within(matchRow).getAllByRole('link', { name: /editar en tn/i })).toHaveLength(1);
    }
  });

  it('renders a plain dash, never "undefined", for rows without title/desc/images', async () => {
    setupApiMocks({
      items: [{ ean: 'BARE-1', verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [], tn_presence: 'unknown' }],
      verdictCounts: { MAL_PUBLICADO: 1 },
    });
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('BARE-1')).toBeInTheDocument();
    });
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /editar en tn/i })).not.toBeInTheDocument();
  });

  it('PR5: falls back to the ERP description when ml_title is absent, and labels it as ERP (not ML)', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'NOMLTITLE-1',
          verdict: 'FALTA_PUBLICAR',
          despublicar: false,
          tn_matches: [],
          tn_presence: 'not_in_tn',
          erp_desc: 'Auricular inalambrico modelo X',
        },
      ],
      verdictCounts: { FALTA_PUBLICAR: 1 },
    });
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('Auricular inalambrico modelo X')).toBeInTheDocument();
    });
    // Distinguishable from an ML title so the operator never mistakes an
    // ERP description for a published ML title.
    // Exact text, not /ERP/i — a loose regex is satisfied by any string
    // containing "erp" and would keep passing if the tag disappeared.
    expect(screen.getByText('ERP')).toBeInTheDocument();
  });

  it('PR5: prefers ml_title over erp_desc when both are present (ml_title stays the primary identity line)', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'BOTH-1',
          verdict: 'MAL_PUBLICADO',
          despublicar: false,
          tn_matches: [],
          tn_presence: 'published',
          ml_title: 'Titulo ML',
          erp_desc: 'Descripcion ERP que no debe verse',
        },
      ],
      verdictCounts: { MAL_PUBLICADO: 1 },
    });
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('Titulo ML')).toBeInTheDocument();
    });
    expect(screen.queryByText('Descripcion ERP que no debe verse')).not.toBeInTheDocument();
  });

  it('PR5: still renders a plain dash when ml_title, erp_desc, desc and images are all absent', async () => {
    setupApiMocks({
      items: [{ ean: 'BARE-2', verdict: 'MAL_PUBLICADO', despublicar: false, tn_matches: [], tn_presence: 'unknown' }],
      verdictCounts: { MAL_PUBLICADO: 1 },
    });
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('BARE-2')).toBeInTheDocument();
    });
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
  });

  // Coverage added in pass B: the standalone EAN column is gone — the EAN
  // now renders inside the Producto cell, under the title. Nothing in the
  // pre-existing suite asserted the EAN renders ALONGSIDE a title (only that
  // each renders somewhere on the page independently).
  it('renders the EAN under the product title, inside the Producto cell (pass B collapse)', async () => {
    setupEnriched();
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('Auricular Bluetooth XYZ')).toBeInTheDocument();
    });
    const title = screen.getByText('Auricular Bluetooth XYZ');
    const productoCell = title.closest('td');
    expect(within(productoCell).getByText('RICH-1')).toBeInTheDocument();
  });
});

describe('Motivo column (PR1 reason/cause taxonomy)', () => {
  it('renders a Spanish label for a DEAD_LINK reason', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'DL-1',
          verdict: 'MAL_PUBLICADO',
          despublicar: false,
          tn_matches: [],
          reason: 'DEAD_LINK',
          reason_detail: { expected_ean: 'DL-1', tn_sku_found: null, claimed_tnr_id: 999, claimed_tnr_variation_id: 88 },
        },
      ],
      verdictCounts: { MAL_PUBLICADO: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    // `getAllByText`: the EAN now appears twice — once as the row's own
    // column and once as the `EAN GBP` operand of the evidence pair, which
    // used to be hidden in a `title` tooltip.
    await waitFor(() => {
      expect(screen.getAllByText('DL-1').length).toBeGreaterThan(0);
    });
    // Motivo is no longer its own column (pass B: merged into "En Tienda
    // Nube") — it renders inline under the presence label instead.
    expect(screen.getByRole('columnheader', { name: /^en tienda nube/i })).toBeInTheDocument();
    expect(screen.getByText(/enlace inexistente en tienda nube/i)).toBeInTheDocument();
    // A dead link resolves to no TN row, so there is no SKU to show — the
    // operand must be absent, never rendered blank.
    expect(screen.queryByText(/^SKU en TN$/i)).not.toBeInTheDocument();
  });

  it('renders a Spanish label for a SKU_MISMATCH reason with its operands', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'SM-1',
          verdict: 'MAL_PUBLICADO',
          despublicar: false,
          tn_matches: [],
          reason: 'SKU_MISMATCH',
          reason_detail: {
            expected_ean: 'SM-1',
            tn_sku_found: '000123456789',
            claimed_tnr_id: 501,
            claimed_tnr_variation_id: 12,
          },
        },
      ],
      verdictCounts: { MAL_PUBLICADO: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getAllByText('SM-1').length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/sku no coincide con el ean/i)).toBeInTheDocument();
    // The whole point of the change: the SKU Tienda Nube actually holds is
    // READABLE in the row, not buried in a hover-only `title`. Without it
    // the operator cannot tell a typo from a different product.
    expect(screen.getByText('000123456789')).toBeInTheDocument();
    expect(screen.getByText(/^EAN GBP$/i)).toBeInTheDocument();
    expect(screen.getByText(/^SKU en TN$/i)).toBeInTheDocument();
  });

  it('renders a Spanish label for a NO_VARIANT_LINK reason', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'NVL-1',
          verdict: 'MAL_VINCULADO',
          despublicar: false,
          tn_matches: [],
          reason: 'NO_VARIANT_LINK',
          reason_detail: { expected_ean: 'NVL-1', tn_sku_found: null, claimed_tnr_id: 501, claimed_tnr_variation_id: null },
        },
      ],
      verdictCounts: { MAL_VINCULADO: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getAllByText('NVL-1').length).toBeGreaterThan(0);
    });
    expect(screen.getByText(/sin vínculo de variante/i)).toBeInTheDocument();
  });

  it('renders an empty Motivo cell (never a raw code, never "undefined") when reason is null', async () => {
    setupApiMocks({
      items: [{ ean: 'FP-1', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], reason: null }],
      verdictCounts: { FALTA_PUBLICAR: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('FP-1')).toBeInTheDocument();
    });
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
    expect(screen.queryByText('null')).not.toBeInTheDocument();
  });

  it('renders rows with reason=null exactly as before (no layout regression)', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('111')).toBeInTheDocument();
    });
    // No standalone Motivo column any more — a null reason simply renders
    // nothing under the presence label, no layout regression either way.
    expect(screen.getByRole('columnheader', { name: /^en tienda nube/i })).toBeInTheDocument();
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
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

  // Coverage added in pass B: `loadColumnSizing` filters persisted sizing to
  // known column ids (added in pass A) — verify it still holds after this
  // pass drops 4 column ids (ean/reason/despublicar/matches) from `COLUMNS`.
  // A stale localStorage entry for a since-removed column id must not leak
  // through and must not throw.
  it('drops sizing for columns removed by this pass (ean/reason/despublicar/matches) without throwing', async () => {
    localStorage.setItem(
      COLUMN_SIZING_STORAGE_KEY,
      JSON.stringify({ ean: 999, reason: 999, despublicar: 999, matches: 999, producto: 400 })
    );

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getAllByRole('table').length).toBeGreaterThan(0);
    });
    // The still-valid entry (producto) survives; nothing throws over the
    // stale ones for columns this pass removed.
    expect(screen.getByRole('columnheader', { name: /^producto/i })).toBeInTheDocument();
  });
});

describe('Column set (pass B: 5-column collapse)', () => {
  it('renders exactly the 5 target columns, in order, with EAN/Motivo/Despublicar/Coincidencias no longer standalone', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('111')).toBeInTheDocument();
    });
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent.replace(/\s+/g, ' ').trim());
    // Exactly 5 headers, matching column order.
    expect(headers).toHaveLength(5);
    expect(headers[0]).toMatch(/^Producto/i);
    expect(headers[1]).toMatch(/^Veredicto/i);
    expect(headers[2]).toMatch(/^En Tienda Nube/i);
    expect(headers[3]).toMatch(/^Stock/i);
    expect(headers[4]).toMatch(/^Acciones/i);

    expect(screen.queryByRole('columnheader', { name: /^ean$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /^motivo/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /^despublicar/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /coincidencias/i })).not.toBeInTheDocument();
  });

  it('drops the redundant Sí/— despublicar flag column — the info lives in the presence label and the Acciones menu instead', async () => {
    setupApiMocks({
      items: [
        {
          ean: 'DESP-1',
          verdict: 'MAL_VINCULADO',
          despublicar: true,
          tn_matches: [{ product_id: 555, variant_id: 1, variant_sku: 'DESP-1', published: true }],
        },
      ],
      verdictCounts: { MAL_VINCULADO: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('DESP-1')).toBeInTheDocument();
    });
    // No standalone "Sí" flag cell for the despublicar-flagged row (the
    // action itself is still reachable — covered by the "Despublicar
    // action" describe block above via the Acciones menu).
    const row = screen.getByText('DESP-1').closest('tr');
    expect(within(row).queryByText(/^Sí$/)).not.toBeInTheDocument();
  });
});

describe('Stock column (Slice 4)', () => {
  function eanOrder() {
    const rows = screen.getAllByRole('row').slice(1); // skip header row
    return rows.map((row) => within(row).getAllByRole('cell')[0].textContent.trim());
  }

  it('renders a Stock column header', async () => {
    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('111')).toBeInTheDocument();
    });
    // Resize-grip aria-label concatenates into the header's accessible name.
    expect(screen.getByRole('columnheader', { name: /^stock/i })).toBeInTheDocument();
  });

  it('renders the numeric stock value for a row with known stock', async () => {
    setupApiMocks({
      items: [{ ean: 'ST-1', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: 7 }],
      verdictCounts: { FALTA_PUBLICAR: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('ST-1')).toBeInTheDocument();
    });
    expect(screen.getByText('7')).toBeInTheDocument();
  });

  it('renders unknown stock (null) distinctly from a real zero — never "0", never blank', async () => {
    setupApiMocks({
      items: [{ ean: 'ST-NULL', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: null }],
      verdictCounts: { FALTA_PUBLICAR: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('ST-NULL')).toBeInTheDocument();
    });
    const row = screen.getByText('ST-NULL').closest('tr');
    // 5-column layout (pass B): Producto · Veredicto · En Tienda Nube ·
    // Stock · Acciones — Stock is index 3.
    const stockCell = within(row).getAllByRole('cell')[3];
    expect(stockCell.textContent.trim()).toBe('—');
    expect(stockCell.textContent.trim()).not.toBe('0');
    // The dash renders muted (.noLink), same as DuplicateGroupCard/BANLIST's
    // empty-value dash — never plain unstyled body text.
    expect(stockCell.querySelector('span').className).toMatch(/noLink/i);
  });

  it('renders a genuine zero stock as "0", not as the unknown marker', async () => {
    setupApiMocks({
      items: [{ ean: 'ST-ZERO', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: 0 }],
      verdictCounts: { FALTA_PUBLICAR: 1 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);

    await waitFor(() => {
      expect(screen.getByText('ST-ZERO')).toBeInTheDocument();
    });
    // Scoped to the row (not a bare screen.getByText('0')): PR-10's summary
    // strip renders its own "0" counts as sibling text (e.g. an empty
    // "Bloqueados" card), which now makes "0" ambiguous at the document
    // level — this assertion's actual subject is the STOCK CELL, not any
    // other zero on the page.
    const row = screen.getByText('ST-ZERO').closest('tr');
    // 5-column layout (pass B): Producto · Veredicto · En Tienda Nube ·
    // Stock · Acciones — Stock is index 3.
    const stockCell = within(row).getAllByRole('cell')[3];
    expect(stockCell.textContent.trim()).toBe('0');
  });

  it('sorts descending by stock on first click, nulls last', async () => {
    const user = userEvent.setup();
    setupApiMocks({
      items: [
        { ean: 'A-NULL', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: null },
        { ean: 'B-LOW', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: 2 },
        { ean: 'C-HIGH', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: 9 },
      ],
      verdictCounts: { FALTA_PUBLICAR: 3 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);
    await waitFor(() => {
      expect(screen.getByText('A-NULL')).toBeInTheDocument();
    });

    const stockHeader = screen.getByRole('columnheader', { name: /^stock/i });
    await user.click(within(stockHeader).getByRole('button'));

    await waitFor(() => {
      expect(eanOrder()).toEqual(['C-HIGH', 'B-LOW', 'A-NULL']);
    });
  });

  it('sorts ascending by stock on the second click, nulls still last', async () => {
    const user = userEvent.setup();
    setupApiMocks({
      items: [
        { ean: 'A-NULL', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: null },
        { ean: 'B-LOW', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: 2 },
        { ean: 'C-HIGH', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: 9 },
      ],
      verdictCounts: { FALTA_PUBLICAR: 3 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);
    await waitFor(() => {
      expect(screen.getByText('A-NULL')).toBeInTheDocument();
    });

    const stockHeader = screen.getByRole('columnheader', { name: /^stock/i });
    const sortButton = within(stockHeader).getByRole('button');
    await user.click(sortButton); // descending
    await user.click(sortButton); // ascending

    await waitFor(() => {
      expect(eanOrder()).toEqual(['B-LOW', 'C-HIGH', 'A-NULL']);
    });
  });

  it('breaks ties in stock value by EAN, deterministically', async () => {
    const user = userEvent.setup();
    setupApiMocks({
      items: [
        { ean: 'Z-TIE', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: 5 },
        { ean: 'A-TIE', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: 5 },
      ],
      verdictCounts: { FALTA_PUBLICAR: 2 },
    });

    await renderWithRouter(<TiendaNubeReconcile />);
    await waitFor(() => {
      expect(screen.getByText('Z-TIE')).toBeInTheDocument();
    });

    const stockHeader = screen.getByRole('columnheader', { name: /^stock/i });
    await user.click(within(stockHeader).getByRole('button'));

    await waitFor(() => {
      expect(eanOrder()).toEqual(['A-TIE', 'Z-TIE']);
    });
  });

  it('does not mutate the original reporte array when sorting', async () => {
    const user = userEvent.setup();
    const items = [
      { ean: 'A-NULL', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: null },
      { ean: 'C-HIGH', verdict: 'FALTA_PUBLICAR', despublicar: false, tn_matches: [], stock: 9 },
    ];
    setupApiMocks({ items, verdictCounts: { FALTA_PUBLICAR: 2 } });

    await renderWithRouter(<TiendaNubeReconcile />);
    await waitFor(() => {
      expect(screen.getByText('A-NULL')).toBeInTheDocument();
    });

    const stockHeader = screen.getByRole('columnheader', { name: /^stock/i });
    await user.click(within(stockHeader).getByRole('button'));

    await waitFor(() => {
      expect(eanOrder()).toEqual(['C-HIGH', 'A-NULL']);
    });
    // The array passed in by the mock (and re-used by the mock across
    // re-renders) must still be in its original fetched order.
    expect(items.map((r) => r.ean)).toEqual(['A-NULL', 'C-HIGH']);
  });

  it('resets to page 1 when the sort changes so the operator is never stranded on a now-empty page', async () => {
    const user = userEvent.setup();
    const items = manyFaltaPublicar(120).map((r, i) => ({ ...r, stock: i }));
    setupApiMocks({ items, verdictCounts: { FALTA_PUBLICAR: 120 } });

    await renderWithRouter(<TiendaNubeReconcile />);
    await waitFor(() => {
      expect(api.get.mock.calls.filter(([url]) => url === '/tienda-nube-reconcile/reporte')).toHaveLength(1);
    });

    const nextButton = await screen.findByRole('button', { name: /Siguiente/i });
    await user.click(nextButton);
    expect(await screen.findByRole('button', { name: /Anterior/i })).not.toBeDisabled();

    const stockHeader = screen.getByRole('columnheader', { name: /^stock/i });
    await user.click(within(stockHeader).getByRole('button'));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Anterior/i })).toBeDisabled();
    });
  });
});

describe('selectTabItems — BANLIST sub-tab must paginate against banlist rows only', () => {
  const reporte = manyFaltaPublicar(120);
  const baneados = [
    { id: 1, ean: 'BANNED-1', motivo: 'x', usuario_nombre: 'Op', fecha_creacion: '2026-07-01T00:00:00Z' },
    { id: 2, ean: 'BANNED-2', motivo: 'x', usuario_nombre: 'Op', fecha_creacion: '2026-07-01T00:00:00Z' },
  ];

  it('returns the banlist rows, not the full reporte, for the BANLIST sub-tab', () => {
    // Before the fix, `currentTabItems`/`selectTabItems` fell back to the
    // WHOLE `reporte` (120 rows) on 'BANLIST' — total/totalPages/filasVisibles
    // were then computed against unrelated FALTA_PUBLICAR rows instead of the
    // 2 banned EANs actually rendered on that tab.
    const result = selectTabItems('BANLIST', reporte, baneados);
    expect(result).toBe(baneados);
    expect(result).toHaveLength(2);
  });

  it('still returns the whole reporte for the "todos" sub-tab', () => {
    expect(selectTabItems('todos', reporte, baneados)).toBe(reporte);
  });

  it('still filters by verdict for a verdict sub-tab', () => {
    const result = selectTabItems('FALTA_PUBLICAR', reporte, baneados);
    expect(result).toHaveLength(120);
    expect(result.every((r) => r.verdict === 'FALTA_PUBLICAR')).toBe(true);
  });
});

describe('Excepción aceptada — la salida que los veredictos de anomalía no tenían', () => {
  const FILA_ANOMALA = {
    ean: 'EXC-1',
    verdict: 'MAL_PUBLICADO',
    despublicar: false,
    tn_presence: 'published',
    tn_matches: [],
    reason: 'SKU_MISMATCH',
    reason_detail: {
      expected_ean: 'EXC-1',
      tn_sku_found: '6935364070922',
      claimed_tnr_id: 501,
      claimed_tnr_variation_id: 12,
    },
    evidencia: 'MAL_PUBLICADO|EXC-1|6935364070922|501|12',
    excepcion_aceptada: false,
  };

  it('pide un motivo y manda la evidencia que emitió el backend', async () => {
    setupApiMocks({ items: [FILA_ANOMALA], verdictCounts: { MAL_PUBLICADO: 1 } });
    const user = userEvent.setup();
    await renderWithRouter(<TiendaNubeReconcile />);

    await user.click(await screen.findByRole('button', { name: /aceptar como correcto/i }));

    // La evidencia concreta se muestra ANTES de aceptar: el operador
    // confirma una situación puntual, no un producto. `within(dialog)`
    // porque el SKU ahora también está a la vista en la propia fila.
    // `ModalTesla` no expone role="dialog", así que el ancla es el bloque
    // de evidencia del propio modal.
    const evidencia = await screen.findByTestId('excepcion-evidencia');
    expect(within(evidencia).getByText('6935364070922')).toBeInTheDocument();

    const confirmar = within(screen.getByTestId('excepcion-acciones')).getByRole('button', {
      name: /aceptar como correcto/i,
    });
    // Sin motivo no se puede confirmar: una excepción sin justificación es
    // indistinguible de alguien tapando una alerta que no entendió.
    expect(confirmar).toBeDisabled();

    await user.type(screen.getByLabelText(/motivo/i), 'El proveedor factura con otro código');
    await user.click(confirmar);

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/tienda-nube-reconcile/excepciones/aceptar', {
        evidencia: 'MAL_PUBLICADO|EXC-1|6935364070922|501|12',
        ean: 'EXC-1',
        verdict: 'MAL_PUBLICADO',
        motivo: 'El proveedor factura con otro código',
      });
    });
  });

  it('una fila aceptada se muestra como aceptada, nunca se oculta', async () => {
    setupApiMocks({
      items: [{ ...FILA_ANOMALA, excepcion_aceptada: true }],
      verdictCounts: { MAL_PUBLICADO: 1 },
    });
    await renderWithRouter(<TiendaNubeReconcile />);

    expect(await screen.findByText(/aceptada como correcta/i)).toBeInTheDocument();
    // Sigue en el reporte con su veredicto: si desapareciera, nadie podría
    // distinguir "revisada y está bien" de "alguien la tapó".
    expect(screen.getAllByText('EXC-1').length).toBeGreaterThan(0);
    // Y la excepción se puede deshacer.
    expect(screen.getByRole('button', { name: /quitar excepción/i })).toBeInTheDocument();
  });

  it('sin el permiso propio no ofrece aceptar nada', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'admin.gestionar_tn_reconcile_excepciones');
    setupApiMocks({ items: [FILA_ANOMALA], verdictCounts: { MAL_PUBLICADO: 1 } });
    await renderWithRouter(<TiendaNubeReconcile />);

    await screen.findByText(/sku no coincide/i);
    expect(screen.queryByRole('button', { name: /aceptar como correcto/i })).not.toBeInTheDocument();
    mockTienePermiso.mockImplementation(() => true);
  });
});
