import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useProductosKeyboard } from './useProductosKeyboard';

/**
 * Regression test for the auto-scroll DOM-position bug (productos-promociones-ui).
 *
 * `useProductosKeyboard`'s auto-scroll effect used to do
 * `tbody.querySelectorAll('tr')[celdaActiva.rowIndex]`, a DOM-position index.
 * Once detail rows (MLA/promotions expand) are inserted between main product
 * rows, that index no longer maps to the correct product row.
 *
 * The fix prefers `tr[data-nav-row="<rowIndex>"]` and falls back to the
 * legacy DOM-position lookup when no row has that attribute yet, so this
 * stays backward-compatible until FE-C wires `data-nav-row` in Productos.jsx.
 */

function makeBaseArgs(overrides = {}) {
  return {
    data: { productos: [{ item_id: 'A' }, { item_id: 'B' }, { item_id: 'C' }] },
    editing: {
      editandoPrecio: null, editandoCuota: null, modoVista: 'normal', recalcularCuotasAuto: false,
    },
    toggles: { editandoRebate: null, editandoWebTransf: null },
    seleccion: {},
    ui: {
      panelFiltroActivo: null, mostrarFiltrosAvanzados: false,
      mostrarExportModal: false, mostrarCalcularWebModal: false, mostrarCalcularPVPModal: false,
      mostrarModalConfig: false, mostrarModalInfo: false,
    },
    permissions: {
      puedeEditar: true, puedeMarcarColor: true,
      puedeToggleRebate: true, puedeToggleWebTransf: true, puedeToggleOutOfCards: true,
      puedeCalcularWebMasivo: true, puedeCalcularPVPMasivo: true,
    },
    showToast: vi.fn(),
    ...overrides,
  };
}

describe('useProductosKeyboard — auto-scroll nav-row selector', () => {
  let container;

  beforeEach(() => {
    document.body.innerHTML = '';
    container = document.createElement('div');
    const tbody = document.createElement('tbody');
    tbody.className = 'table-tesla-body';
    container.appendChild(tbody);
    document.body.appendChild(container);
  });

  it('targets the row via data-nav-row when present, ignoring inserted detail rows', () => {
    const tbody = document.querySelector('.table-tesla-body');
    // Simulate: row 0 (main, data-nav-row=0), a detail row with NO data-nav-row
    // inserted right after it, then row 1 (main, data-nav-row=1).
    tbody.innerHTML = `
      <tr data-nav-row="0"><td>Row 0</td></tr>
      <tr data-detail-row><td>Detail for row 0</td></tr>
      <tr data-nav-row="1"><td>Row 1</td></tr>
    `;
    const row1 = tbody.querySelector('tr[data-nav-row="1"]');
    row1.scrollIntoView = vi.fn();
    const detailRow = tbody.querySelector('[data-detail-row]');
    detailRow.scrollIntoView = vi.fn();

    const { result } = renderHook(() => useProductosKeyboard(makeBaseArgs()));

    act(() => {
      result.current.setModoNavegacion(true);
      result.current.setCeldaActiva({ rowIndex: 1, colIndex: 0 });
    });

    expect(row1.scrollIntoView).toHaveBeenCalled();
    expect(detailRow.scrollIntoView).not.toHaveBeenCalled();
  });

  it('falls back to legacy DOM-position lookup when no data-nav-row exists yet', () => {
    const tbody = document.querySelector('.table-tesla-body');
    tbody.innerHTML = `
      <tr><td>Row 0</td></tr>
      <tr><td>Row 1</td></tr>
      <tr><td>Row 2</td></tr>
    `;
    const rows = tbody.querySelectorAll('tr');
    rows.forEach((r) => { r.scrollIntoView = vi.fn(); });

    const { result } = renderHook(() => useProductosKeyboard(makeBaseArgs()));

    act(() => {
      result.current.setModoNavegacion(true);
      result.current.setCeldaActiva({ rowIndex: 2, colIndex: 0 });
    });

    expect(rows[2].scrollIntoView).toHaveBeenCalled();
    expect(rows[0].scrollIntoView).not.toHaveBeenCalled();
    expect(rows[1].scrollIntoView).not.toHaveBeenCalled();
  });
});
