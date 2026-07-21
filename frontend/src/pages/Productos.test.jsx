/**
 * Characterization tests for Productos.jsx
 *
 * These tests pin the EXISTING behavior of <Productos /> (page-level).
 * They stay BYTE-IDENTICAL across all extraction slices — that invariance
 * proves behavior preservation as internals move into hooks.
 *
 * Verified facts (T1.1 / T1.2 — 2026-06-29):
 *   - productosAPI.listar → { data: { productos: [...], total: N } }
 *   - productosAPI.statsDinamicos → { data: { ... } }
 *   - Keyboard activation key: Enter (when modoNavegacion===false && productos.length>0)
 *   - iniciarEdicion, guardarPrecio, iniciarEdicionCuota, guardarCuota
 *   - toggleRebateRapido, toggleWebTransfRapido, toggleOutOfCardsRapido
 *   - toggleSeleccion, seleccionarTodos, pintarLote
 *   - No heavy import-time deps (leaflet/pdfme not in Productos.jsx chain)
 *
 * Mutation-verified (2026-06-29 oracle hardening pass):
 *   All CS-3..CS-7 rewritten tests went RED when the relevant production
 *   code path was commented out, and GREEN after restore.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, act, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import Productos from './Productos';

// Reach into the mocked module
import { productosAPI } from '../services/api';
import api from '../services/api';

function getPromoFilterContainer() {
  return screen.getByText('🏷️ Promos').closest('.filter-item');
}

// ---------------------------------------------------------------------------
// Shared fixture helpers
// ---------------------------------------------------------------------------

function makeProducto(overrides = {}) {
  return {
    item_id: 'ITEM001',
    codigo: 'SKU001',
    descripcion: 'Producto Test',
    marca: 'BRAND_X',
    // Price field displayed in the clasica column: precio_lista_ml
    precio_lista_ml: 100,
    precio_clasica: 100,
    costo_usd: 10,
    costo: 10,
    costo_ars: 10000,
    moneda_costo: 'USD',
    tipo_cambio: 1000,
    markup: 5.0,
    markup_clasica: 5.0,
    precio_rebate: null,
    rebate_porcentaje: null,
    rebate_participa: false,
    participa_rebate: false,
    mejor_oferta: null,
    mejor_oferta_precio: null,
    precio_web_transf: null,
    precio_web_transferencia: null,
    web_transf_participa: false,
    participa_web_transferencia: false,
    web_transf_porcentaje: null,
    porcentaje_markup_web: null,
    cuotas_3: null,
    cuotas_6: null,
    cuotas_9: null,
    cuotas_12: null,
    pvp_cuotas_3: null,
    pvp_cuotas_6: null,
    pvp_cuotas_9: null,
    pvp_cuotas_12: null,
    precio_3_cuotas: null,
    precio_6_cuotas: null,
    precio_9_cuotas: null,
    precio_12_cuotas: null,
    precio_pvp_3_cuotas: null,
    precio_pvp_6_cuotas: null,
    precio_pvp_9_cuotas: null,
    precio_pvp_12_cuotas: null,
    precio_pvp: null,
    markup_pvp: null,
    stock: 5,
    color_marcado: null,
    out_of_cards: false,
    subcategoria: 'Sub1',
    recalcular_cuotas_auto: null,
    ...overrides,
  };
}

/**
 * Base API mock setup shared across all tests.
 * Individual tests can override specific URLs via api.get.mockImplementation
 * after calling this.
 */
function setupApiMocks({ productos = [], total = 0 } = {}) {
  productosAPI.listar.mockResolvedValue({
    data: { productos, total },
  });
  productosAPI.statsDinamicos.mockResolvedValue({ data: {} });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
  api.get.mockImplementation((url) => {
    if (url === '/auditoria/usuarios') return Promise.resolve({ data: [] });
    if (url === '/auditoria/tipos-accion') return Promise.resolve({ data: [] });
    if (url.startsWith('/usuarios/pms')) return Promise.resolve({ data: [] });
    if (url === '/offsets-ganancia') return Promise.resolve({ data: [] });
    if (url === '/tipo-cambio-hoy') return Promise.resolve({ data: { tipo_cambio: 1000 } });
    return Promise.resolve({ data: {} });
  });
}

/** Setup api.get with an extra handler for consultarMarkup returning a specific markup value. */
function setupApiWithMarkup(markupValue) {
  api.get.mockImplementation((url) => {
    if (url === '/auditoria/usuarios') return Promise.resolve({ data: [] });
    if (url === '/auditoria/tipos-accion') return Promise.resolve({ data: [] });
    if (url.startsWith('/usuarios/pms')) return Promise.resolve({ data: [] });
    if (url === '/offsets-ganancia') return Promise.resolve({ data: [] });
    if (url === '/tipo-cambio-hoy') return Promise.resolve({ data: { tipo_cambio: 1000 } });
    if (url.startsWith('/precios/calcular-markup')) {
      return Promise.resolve({ data: { markup: markupValue } });
    }
    return Promise.resolve({ data: {} });
  });
}

// ---------------------------------------------------------------------------
// CS-1 — Page load + product list renders
// ---------------------------------------------------------------------------
describe('CS-1: page load + product list renders', () => {
  beforeEach(() => {
    setupApiMocks({
      productos: [
        makeProducto({ item_id: 'A1', descripcion: 'Producto Alfa' }),
        makeProducto({ item_id: 'A2', descripcion: 'Producto Beta' }),
      ],
      total: 2,
    });
  });

  it('renders the page and shows product rows after data loads', async () => {
    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => {
      expect(screen.getByText('Producto Alfa')).toBeInTheDocument();
      expect(screen.getByText('Producto Beta')).toBeInTheDocument();
    });

    expect(productosAPI.listar).toHaveBeenCalled();
  });

  it('calls statsDinamicos on mount', async () => {
    await act(async () => {
      renderWithRouter(<Productos />);
    });
    await waitFor(() => {
      expect(productosAPI.statsDinamicos).toHaveBeenCalled();
    });
  });
});

// ---------------------------------------------------------------------------
// CS-2 — Filter apply + URL sync
// ---------------------------------------------------------------------------
describe('CS-2: filter apply + URL sync', () => {
  it('mounts with ?marcas=BRAND_X and passes brand param to API', async () => {
    // URL param is "marcas" (plural) — verified from loadFiltersFromURL():
    //   const marcas = searchParams.get('marcas');
    //   if (marcas) setMarcasSeleccionadas(marcas.split(',')...);
    // Then cargarProductos builds: params.marcas = marcasSeleccionadas.join(',');
    setupApiMocks({
      productos: [makeProducto({ marca: 'BRAND_X', descripcion: 'BX Product' })],
      total: 1,
    });

    await act(async () => {
      renderWithRouter(<Productos />, { initialEntries: ['/?marcas=BRAND_X'] });
    });

    await waitFor(() => {
      const calls = productosAPI.listar.mock.calls;
      const hasMarkParam = calls.some(
        (call) => call[0] && call[0].marcas && call[0].marcas.includes('BRAND_X')
      );
      expect(hasMarkParam).toBe(true);
    }, { timeout: 3000 });
  });
});

// ---------------------------------------------------------------------------
// CS-3 — Inline price edit: open input + save (both verified)
// Verified: price column shows p.precio_lista_ml; click calls iniciarEdicion(p)
// which sets editandoPrecio and opens an input[inputMode="decimal"].
// Save triggers guardarPrecio → consultarMarkup → /precios/set-rapido.
// ---------------------------------------------------------------------------
describe('CS-3: inline price edit + save (happy path)', () => {
  it('clicking price cell shows edit input', async () => {
    // precio_lista_ml = 100 → renders "$100" in clasica column
    const producto = makeProducto({ item_id: 'P1', precio_lista_ml: 100, markup: 5.0 });
    setupApiMocks({ productos: [producto], total: 1 });
    setupApiWithMarkup(5.0);

    const user = userEvent.setup();

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => {
      expect(screen.getByText('Producto Test')).toBeInTheDocument();
    });

    // Find and click the price cell — it renders "$100"
    const priceText = screen.getByText('$100');
    await act(async () => {
      await user.click(priceText);
    });

    // After click, an inline edit input should appear (inputMode="decimal")
    await waitFor(() => {
      const inputs = document.querySelectorAll('input[inputMode="decimal"], input[inputmode="decimal"]');
      expect(inputs.length).toBeGreaterThan(0);
    });
  });

  it('saves price and calls /precios/set-rapido with correct params', async () => {
    // Oracle: if guardarPrecio's api.post call is removed, this test goes RED.
    const producto = makeProducto({ item_id: 'P1', precio_lista_ml: 100, markup: 5.0 });
    setupApiMocks({ productos: [producto], total: 1 });
    setupApiWithMarkup(5.0); // positive markup → no confirmation modal
    api.post.mockResolvedValue({ data: { precio_lista_ml: 150, markup: 5.0 } });

    const user = userEvent.setup();

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => {
      expect(screen.getByText('Producto Test')).toBeInTheDocument();
    });

    // Open edit
    await act(async () => {
      await user.click(screen.getByText('$100'));
    });

    await waitFor(() => {
      const inputs = document.querySelectorAll('input[inputMode="decimal"], input[inputmode="decimal"]');
      expect(inputs.length).toBeGreaterThan(0);
    });

    // Type new price
    const priceInput = document.querySelector('input[inputMode="decimal"], input[inputmode="decimal"]');
    await act(async () => {
      await user.clear(priceInput);
      await user.type(priceInput, '150');
    });

    // Click save (✓ button)
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Guardar precio' }));
    });

    // Assert the price save API was called with item_id and precio
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/precios/set-rapido',
        null,
        expect.objectContaining({
          params: expect.objectContaining({
            item_id: 'P1',
            precio: 150,
          }),
        })
      );
    });
  });
});

// ---------------------------------------------------------------------------
// CS-4 — Negative-markup confirmation modal (BOTH branches)
//
// Oracle: guardarPrecio calls consultarMarkup; if markup < 0, the modal
// appears and no write fires until the user confirms. Removing either the
// consultarMarkup call or the modal gate makes one of these sub-tests RED.
// ---------------------------------------------------------------------------
describe('CS-4: negative markup confirmation', () => {
  async function renderAndOpenEdit(user, producto) {
    setupApiMocks({ productos: [producto], total: 1 });
    setupApiWithMarkup(-5.0); // negative markup → modal gate

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => expect(screen.getByText(producto.descripcion)).toBeInTheDocument());

    // Click price cell to open inline edit
    await act(async () => {
      await user.click(screen.getByText('$100'));
    });

    await waitFor(() => {
      const inputs = document.querySelectorAll('input[inputMode="decimal"], input[inputmode="decimal"]');
      expect(inputs.length).toBeGreaterThan(0);
    });

    // Type a low price that yields negative markup
    const priceInput = document.querySelector('input[inputMode="decimal"], input[inputmode="decimal"]');
    await act(async () => {
      await user.clear(priceInput);
      await user.type(priceInput, '1');
    });

    // Click save — this triggers consultarMarkup which returns markup < 0
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Guardar precio' }));
    });

    // Modal must appear — use role heading to disambiguate from the stat card
    // that also contains "Markup Negativo" text.
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /MarkUp Negativo/i })).toBeInTheDocument();
    });
  }

  it('shows modal and holds off write when markup would be negative', async () => {
    const producto = makeProducto({ item_id: 'NM1', precio_lista_ml: 100 });
    const user = userEvent.setup();

    await renderAndOpenEdit(user, producto);

    // Modal is open — heading and confirm button are visible
    expect(screen.getByRole('heading', { name: /MarkUp Negativo/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Guardar de todas formas/i })).toBeInTheDocument();
    // No price write yet
    expect(api.post).not.toHaveBeenCalledWith(
      '/precios/set-rapido',
      expect.anything(),
      expect.anything()
    );
  });

  it('confirm branch: calls /precios/set-rapido after user confirms', async () => {
    const producto = makeProducto({ item_id: 'NM1', precio_lista_ml: 100 });
    const user = userEvent.setup();

    api.post.mockResolvedValue({ data: { precio_lista_ml: 1, markup: -5.0 } });

    await renderAndOpenEdit(user, producto);

    // Click confirm
    await act(async () => {
      await user.click(screen.getByRole('button', { name: /Guardar de todas formas/i }));
    });

    // Write must fire with item_id and precio
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/precios/set-rapido',
        null,
        expect.objectContaining({
          params: expect.objectContaining({ item_id: 'NM1', precio: 1 }),
        })
      );
    });

    // Modal must close
    expect(screen.queryByText(/Guardar de todas formas/i)).not.toBeInTheDocument();
  });

  it('cancel branch: no write and modal closes', async () => {
    const producto = makeProducto({ item_id: 'NM1', precio_lista_ml: 100 });
    const user = userEvent.setup();

    await renderAndOpenEdit(user, producto);

    // Click the Cancelar button inside the markup modal specifically
    const modalOverlay = document.querySelector('.modal-ban-overlay');
    const cancelarBtn = within(modalOverlay).getByRole('button', { name: /Cancelar/i });
    await act(async () => {
      await user.click(cancelarBtn);
    });

    // Modal closes
    await waitFor(() => {
      expect(screen.queryByText(/Guardar de todas formas/i)).not.toBeInTheDocument();
    });

    // No price write occurred
    expect(api.post).not.toHaveBeenCalledWith(
      '/precios/set-rapido',
      expect.anything(),
      expect.anything()
    );
  });
});

// ---------------------------------------------------------------------------
// CS-5 — Cuota edit + save (real oracle)
//
// Oracle: switching to cuotas view exposes cuota cells. Clicking a cell opens
// an inline input; saving calls guardarCuota → /precios/set-cuota.
// Removing the api.post call in guardarCuota makes this test RED.
// ---------------------------------------------------------------------------
describe('CS-5: cuota edit + save', () => {
  it('clicking cuota cell in cuotas view shows input and save calls /precios/set-cuota', async () => {
    // precio_3_cuotas = 50 → renders "$50" in 3-cuotas column when modoVista='cuotas'
    const producto = makeProducto({ item_id: 'C1', precio_lista_ml: 100, precio_3_cuotas: 50 });
    setupApiMocks({ productos: [producto], total: 1 });
    setupApiWithMarkup(3.0); // positive markup → no modal gate

    api.post.mockResolvedValue({
      data: { precio_3_cuotas: 55, markup_3_cuotas: 3.5 },
    });

    const user = userEvent.setup();

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => expect(screen.getByText('Producto Test')).toBeInTheDocument());

    // Switch to cuotas view: button labeled 'Normal' cycles to 'cuotas'
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Normal' }));
    });

    // Cuota cell should now show '$50'
    await waitFor(() => {
      expect(screen.getByText('$50')).toBeInTheDocument();
    });

    // Click the cuota value to open inline edit
    await act(async () => {
      await user.click(screen.getByText('$50'));
    });

    await waitFor(() => {
      const inputs = document.querySelectorAll('input[inputMode="decimal"], input[inputmode="decimal"]');
      expect(inputs.length).toBeGreaterThan(0);
    });

    // Type a new cuota value
    const cuotaInput = document.querySelector('input[inputMode="decimal"], input[inputmode="decimal"]');
    await act(async () => {
      await user.clear(cuotaInput);
      await user.type(cuotaInput, '55');
    });

    // Click save (✓ with aria-label="Guardar cuota")
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Guardar cuota' }));
    });

    // Assert set-cuota was called with correct params
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/precios/set-cuota',
        null,
        expect.objectContaining({
          params: expect.objectContaining({
            item_id: 'C1',
            tipo_cuota: '3',
            precio: 55,
          }),
        })
      );
    });
  });
});

// ---------------------------------------------------------------------------
// CS-6a — Rebate toggle (keyboard nav: Enter → active row, then 'r')
//
// Oracle: toggleRebateRapido is keyboard-only. Pressing Enter activates
// navigation (row gets keyboard-row-active class), then 'r' fires the rebate
// patch. Removing the api.patch call in toggleRebateRapido makes this RED.
// ---------------------------------------------------------------------------
describe('CS-6a: rebate toggle (keyboard)', () => {
  it('pressing r in navigation mode fires /productos/:id/rebate with participa_rebate true', async () => {
    const producto = makeProducto({
      item_id: 'R1',
      participa_rebate: false,
      precio_rebate: null,
    });
    setupApiMocks({ productos: [producto], total: 1 });
    api.patch.mockResolvedValue({ data: { precio_rebate: 95, markup_rebate: 3.5 } });

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => expect(screen.getByText('Producto Test')).toBeInTheDocument());

    // Activate keyboard navigation with Enter
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });

    // Wait until the first row has the active class (modoNavegacion=true took effect)
    await waitFor(() => {
      expect(document.querySelectorAll('tr.keyboard-row-active').length).toBeGreaterThan(0);
    });

    // Press 'r' (lowercase) to toggle rebate on the active row
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'r', bubbles: true }));
    });

    // api.patch must have been called with participa_rebate: true
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        '/productos/R1/rebate',
        expect.objectContaining({ participa_rebate: true })
      );
    });
  });
});

// ---------------------------------------------------------------------------
// CS-6b — Webtransf toggle (keyboard nav: Enter → active row, then 'w')
//
// Oracle: toggleWebTransfRapido is keyboard-only. Removing api.patch in
// toggleWebTransfRapido makes this test RED.
// ---------------------------------------------------------------------------
describe('CS-6b: webtransf toggle (keyboard)', () => {
  it('pressing w in navigation mode fires /productos/:id/web-transferencia with participa true', async () => {
    const producto = makeProducto({
      item_id: 'W1',
      participa_web_transferencia: false,
      precio_web_transferencia: null,
    });
    setupApiMocks({ productos: [producto], total: 1 });
    api.patch.mockResolvedValue({ data: { precio_web_transferencia: 106, markup_web_real: 4.0 } });

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => expect(screen.getByText('Producto Test')).toBeInTheDocument());

    // Activate keyboard navigation
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });

    await waitFor(() => {
      expect(document.querySelectorAll('tr.keyboard-row-active').length).toBeGreaterThan(0);
    });

    // Press 'w' (lowercase) to toggle webtransf
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'w', bubbles: true }));
    });

    // api.patch must have been called with participa: true
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        '/productos/W1/web-transferencia',
        expect.objectContaining({ participa: true })
      );
    });
  });
});

// ---------------------------------------------------------------------------
// CS-7 — Batch selection + color paint (real oracles)
//
// seleccionarTodos oracle: removing setProductosSeleccionados call in
// seleccionarTodos causes row checkboxes to stay unchecked → RED.
//
// pintarLote oracle: removing api.post call in pintarLote makes the
// batch-paint assertion fail → RED.
// ---------------------------------------------------------------------------
describe('CS-7: batch selection + color paint', () => {
  it('seleccionarTodos selects all products and shows selection counter', async () => {
    const items = [
      makeProducto({ item_id: 'B1', descripcion: 'Batch A' }),
      makeProducto({ item_id: 'B2', descripcion: 'Batch B' }),
    ];
    setupApiMocks({ productos: items, total: 2 });

    const user = userEvent.setup();

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => {
      expect(screen.getByText('Batch A')).toBeInTheDocument();
      expect(screen.getByText('Batch B')).toBeInTheDocument();
    });

    // Click the header checkbox (select all)
    const headerCheckbox = screen.getByRole('checkbox', {
      name: 'Seleccionar todos los productos',
    });
    await act(async () => {
      await user.click(headerCheckbox);
    });

    // All row checkboxes must be checked
    await waitFor(() => {
      const rowCheckboxes = screen.getAllByRole('checkbox', { name: /Seleccionar producto/ });
      expect(rowCheckboxes.length).toBe(2);
      rowCheckboxes.forEach((cb) => expect(cb).toBeChecked());
    });

    // Selection counter must appear
    expect(screen.getByText(/2 productos seleccionados/)).toBeInTheDocument();
  });

  it('pintarLote fires /productos/actualizar-color-lote with selected ids and color', async () => {
    const items = [
      makeProducto({ item_id: 'L1', descripcion: 'Lote A' }),
      makeProducto({ item_id: 'L2', descripcion: 'Lote B' }),
    ];
    setupApiMocks({ productos: items, total: 2 });
    api.post.mockResolvedValue({ data: {} });

    const user = userEvent.setup();

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => {
      expect(screen.getByText('Lote A')).toBeInTheDocument();
    });

    // Select all products
    const headerCheckbox = screen.getByRole('checkbox', {
      name: 'Seleccionar todos los productos',
    });
    await act(async () => {
      await user.click(headerCheckbox);
    });

    // Selection bar must appear with paint buttons
    await waitFor(() => {
      expect(screen.getByText(/2 productos seleccionados/)).toBeInTheDocument();
    });

    // Click the 'Urgente' (rojo) paint button
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Pintar lote como Urgente' }));
    });

    // Assert batch paint API was called with both ids and color='rojo'
    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/productos/actualizar-color-lote',
        expect.objectContaining({
          item_ids: expect.arrayContaining(['L1', 'L2']),
          color: 'rojo',
        })
      );
    });
  });
});

// ---------------------------------------------------------------------------
// CS-6c — Out-of-cards toggle -> rebate state cross-write
//
// Oracle: toggleOutOfCardsRapido (keyboard 'o') on a product without out_of_cards
// activates out_of_cards AND opens rebate edit mode (editandoRebate side-effect).
// This cross-write is the coupling that stays INTERNAL to useProductosToggles.
//
// Mutation-verify target: setEditandoRebate(producto.item_id) in toggleOutOfCardsRapido.
// Removing that call: .rebate-edit never renders -> test goes RED.
// ---------------------------------------------------------------------------
describe('CS-6c: out-of-cards toggle -> rebate state cross-write', () => {
  it('pressing o activates out-of-cards AND opens rebate edit mode (internal cross-write)', async () => {
    const producto = makeProducto({
      item_id: 'OC1',
      out_of_cards: false,
      participa_rebate: false,
      porcentaje_rebate: null,
    });
    setupApiMocks({ productos: [producto], total: 1 });
    // api.patch returns valid data for both calls (rebate activation + out-of-cards)
    api.patch.mockResolvedValue({
      data: { out_of_cards: true, precio_rebate: 95, markup_rebate: 3.5 },
    });

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => expect(screen.getByText('Producto Test')).toBeInTheDocument());

    // Activate keyboard navigation
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });

    await waitFor(() => {
      expect(document.querySelectorAll('tr.keyboard-row-active').length).toBeGreaterThan(0);
    });

    // Press 'o' to trigger toggleOutOfCardsRapido
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'o', bubbles: true }));
    });

    // Primary assertion: out-of-cards was activated via API
    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        '/productos/OC1/out-of-cards',
        expect.objectContaining({ out_of_cards: true })
      );
    });

    // Cross-write oracle: rebate edit mode opened (editandoRebate === 'OC1')
    // If setEditandoRebate is removed from toggleOutOfCardsRapido, this goes RED.
    await waitFor(() => {
      expect(document.querySelector('.rebate-edit')).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// CS-8 — Keyboard navigation smoke test
//
// Oracle: pressing Enter activates modoNavegacion (tr.keyboard-row-active
// appears), ArrowDown moves the active row, and pressing Enter again in nav
// mode triggers iniciarEdicionDesdeTeclado (inline edit input appears).
//
// Mutation-verify target: Enter handler in the main keyboard useEffect.
// No-op-ing the Enter activation branch → tr.keyboard-row-active never
// renders → test goes RED.  Restoring → GREEN.
// ---------------------------------------------------------------------------
describe('CS-8: keyboard navigation smoke', () => {
  it('Enter activates nav mode, ArrowDown moves row, Enter in nav triggers inline edit', async () => {
    const p1 = makeProducto({ item_id: 'KB1', descripcion: 'Producto KB1', precio_lista_ml: 100 });
    const p2 = makeProducto({ item_id: 'KB2', descripcion: 'Producto KB2', precio_lista_ml: 200 });
    setupApiMocks({ productos: [p1, p2], total: 2 });
    // guardarPrecio / inline-edit path uses api.patch
    api.patch.mockResolvedValue({ data: {} });

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    // Wait for rows to render
    await waitFor(() => expect(screen.getByText('Producto KB1')).toBeInTheDocument());

    // --- Step 1: Enter activates modoNavegacion ---
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });

    // tr.keyboard-row-active must appear (row 0 is active)
    await waitFor(() => {
      expect(document.querySelectorAll('tr.keyboard-row-active').length).toBeGreaterThan(0);
    });

    // --- Step 2: ArrowDown moves active row ---
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    });

    // After ArrowDown celdaActiva.rowIndex must be 1, not still 0.
    // Assert the ONLY keyboard-row-active tr contains KB2 text (proves the move —
    // if ArrowDown is a no-op the active row still shows KB1 and this fails RED).
    await waitFor(() => {
      const activeRows = document.querySelectorAll('tr.keyboard-row-active');
      expect(activeRows.length).toBe(1);
      expect(activeRows[0].textContent).toContain('Producto KB2');
    });

    // --- Step 3: Space triggers iniciarEdicionDesdeTeclado (precio_clasica col) ---
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    });

    // inline-edit input must appear (precio clasica edit mode)
    await waitFor(() => {
      expect(document.querySelector('.inline-edit')).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// CS-9 — productos-promociones-ui (FE-B): L1 expansion + keyboard nav coexistence
//
// Oracle: expanding a product row's toggle mounts <ProductoMLAsPanel> (lazy
// fetch via productosAPI.getProductoMercadolibre) inside a `data-detail-row`
// <tr>, and the main product rows keep their `data-nav-row` contract so
// keyboard navigation is unaffected by the inserted detail row.
// ---------------------------------------------------------------------------
describe('CS-9: productos-promociones-ui FE-B — L1 panel expansion + keyboard nav', () => {
  it('expanding a product row shows the MLAs panel', async () => {
    const p1 = makeProducto({ item_id: 'EXP1', descripcion: 'Producto EXP1' });
    setupApiMocks({ productos: [p1], total: 1 });
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: { publicaciones_ml: [{ mla: 'MLA999', pricelist_id: 4, publication_status: 'active' }] },
    });

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => expect(screen.getByText('Producto EXP1')).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir publicaciones de/i }));

    await waitFor(() => expect(screen.getByText('MLA999')).toBeInTheDocument());
    expect(productosAPI.getProductoMercadolibreLite).toHaveBeenCalledWith('EXP1', {});

    const detailRow = document.querySelector('tr[data-detail-row]');
    expect(detailRow).toBeInTheDocument();
    expect(detailRow.textContent).toContain('MLA999');
  });

  it('keyboard nav still targets the correct main row when a detail row is present', async () => {
    const p1 = makeProducto({ item_id: 'NAV1', descripcion: 'Producto NAV1' });
    const p2 = makeProducto({ item_id: 'NAV2', descripcion: 'Producto NAV2' });
    setupApiMocks({ productos: [p1, p2], total: 2 });
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: { publicaciones_ml: [] },
    });

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => expect(screen.getByText('Producto NAV1')).toBeInTheDocument());

    // Expand the first product row (inserts a data-detail-row <tr> above row 1).
    const user = userEvent.setup();
    await user.click(screen.getAllByRole('button', { name: /expandir publicaciones de/i })[0]);
    await waitFor(() => expect(screen.getByText(/sin publicaciones/i)).toBeInTheDocument());

    // Main rows keep their data-nav-row indices regardless of the inserted detail row.
    const navRows = document.querySelectorAll('tr[data-nav-row]');
    expect(navRows.length).toBe(2);
    expect(navRows[0].getAttribute('data-nav-row')).toBe('0');
    expect(navRows[1].getAttribute('data-nav-row')).toBe('1');

    // Enter activates nav mode (row 0 active), ArrowDown moves to row 1 (NAV2).
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    });
    await waitFor(() => {
      expect(document.querySelectorAll('tr.keyboard-row-active').length).toBeGreaterThan(0);
    });

    await act(async () => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    });

    await waitFor(() => {
      const activeRows = document.querySelectorAll('tr.keyboard-row-active');
      expect(activeRows.length).toBe(1);
      expect(activeRows[0].textContent).toContain('Producto NAV2');
    });
  });
});

// ---------------------------------------------------------------------------
// CS-10 — productos-list-promo-filter (FE): promo type/status filter control
//
// Oracle: the "Avanzados" panel exposes a promo-type multi-select (chips,
// shared PROMO_TYPES) + a disponible/aplicada mode toggle. Selecting a chip
// triggers a reload with promo_tipos + default promo_estado=disponible;
// combining with an existing filter (marcas) keeps both active.
// ---------------------------------------------------------------------------
describe('CS-10: promo type/status filter control', () => {
  it('selecting a promo type chip reloads with promo_tipos + default promo_estado', async () => {
    setupApiMocks({ productos: [makeProducto()], total: 1 });

    const user = userEvent.setup();

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => expect(screen.getByText('Producto Test')).toBeInTheDocument());

    // Open the "Avanzados" panel
    await act(async () => {
      await user.click(screen.getByRole('button', { name: /avanzados/i }));
    });

    const smartChip = await within(getPromoFilterContainer()).findByRole('button', { name: /^smart$/i });
    await act(async () => {
      await user.click(smartChip);
    });

    await waitFor(() => {
      const calls = productosAPI.listar.mock.calls;
      const hasPromoParams = calls.some(
        (call) => call[0] && call[0].promo_tipos === 'SMART' && call[0].promo_estado === 'disponible'
      );
      expect(hasPromoParams).toBe(true);
    });
  });

  it('is combinable with an existing filter (marcas via URL) — both params sent together', async () => {
    setupApiMocks({ productos: [makeProducto({ marca: 'BRAND_X' })], total: 1 });

    const user = userEvent.setup();

    await act(async () => {
      renderWithRouter(<Productos />, { initialEntries: ['/?marcas=BRAND_X'] });
    });

    await waitFor(() => expect(screen.getByText('Producto Test')).toBeInTheDocument());

    await act(async () => {
      await user.click(screen.getByRole('button', { name: /avanzados/i }));
    });

    const dealChip = await within(getPromoFilterContainer()).findByRole('button', { name: /^deal$/i });
    await act(async () => {
      await user.click(dealChip);
    });

    await waitFor(() => {
      const calls = productosAPI.listar.mock.calls;
      const hasCombinedParams = calls.some(
        (call) => call[0] && call[0].marcas && call[0].marcas.includes('BRAND_X') && call[0].promo_tipos === 'DEAL'
      );
      expect(hasCombinedParams).toBe(true);
    });
  });

  it('toggling the mode select to aplicada sends promo_estado=aplicada', async () => {
    setupApiMocks({ productos: [makeProducto()], total: 1 });

    const user = userEvent.setup();

    await act(async () => {
      renderWithRouter(<Productos />);
    });

    await waitFor(() => expect(screen.getByText('Producto Test')).toBeInTheDocument());

    await act(async () => {
      await user.click(screen.getByRole('button', { name: /avanzados/i }));
    });

    const smartChip = await within(getPromoFilterContainer()).findByRole('button', { name: /^smart$/i });
    await act(async () => {
      await user.click(smartChip);
    });

    const modeSelect = screen.getByLabelText(/estado de promo/i);
    await act(async () => {
      await user.selectOptions(modeSelect, 'aplicada');
    });

    await waitFor(() => {
      const calls = productosAPI.listar.mock.calls;
      const hasAplicada = calls.some(
        (call) => call[0] && call[0].promo_tipos === 'SMART' && call[0].promo_estado === 'aplicada'
      );
      expect(hasAplicada).toBe(true);
    });
  });
});
