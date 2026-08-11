import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useTiendaKeyboard } from './useTiendaKeyboard';

/**
 * Regression tests for the off-by-one in the Tienda keyboard column mapping.
 *
 * `columnasNavegablesNormal` used to hold only 4 entries
 * (clasica / gremio / web_transf / web_tarjeta) while Tienda.jsx renders FIVE
 * navigable price cells, because a `Precio Sugerido` column was added later and
 * never registered. Every index from 1 onward was shifted: colIndex 2 highlighted
 * Precio Gremio but opened the Web Transf editor, and colIndex 4 was unreachable.
 *
 * The array must map 1:1 onto the colIndex values Tienda.jsx highlights:
 *   normal → 0 Clásica, 1 Sugerido, 2 Gremio, 3 Web Transf, 4 Web Tarjeta
 * and `web_tarjeta` only exists when the user holds `tienda.ver_web_tarjeta`,
 * because its <td>/<th> live behind that same guard.
 */

const VISTA_NORMAL_CON_WEB_TARJETA = [
  'precio_clasica',
  'precio_sugerido',
  'precio_gremio',
  'precio_web_transf',
  'web_tarjeta',
];

const VISTA_CUOTAS = ['precio_clasica', 'cuotas_3', 'cuotas_6', 'cuotas_9', 'cuotas_12'];

function makeArgs({ puedeVerWebTarjeta = true, vistaModoCuotas = false, pricing = {} } = {}) {
  return {
    pricing: {
      editandoPrecio: null,
      editandoRebate: null,
      editandoWebTransf: null,
      editandoCuota: null,
      setEditandoPrecio: vi.fn(),
      setEditandoRebate: vi.fn(),
      setEditandoWebTransf: vi.fn(),
      iniciarEdicionDesdeTeclado: vi.fn(),
      cambiarColorRapido: vi.fn(),
      toggleRebateRapido: vi.fn(),
      toggleWebTransfRapido: vi.fn(),
      toggleOutOfCardsRapido: vi.fn(),
      ...pricing,
    },
    selection: { toggleSeleccion: vi.fn() },
    data: {
      productos: [{ item_id: 1, codigo: 'SKU1' }, { item_id: 2, codigo: 'SKU2' }],
      setProductos: vi.fn(),
      cargarStats: vi.fn(),
    },
    ui: {
      vistaModoCuotas,
      panelFiltroActivo: null,
      mostrarFiltrosAvanzados: false,
      mostrarExportModal: false,
      mostrarCalcularWebModal: false,
      mostrarModalConfig: false,
      mostrarModalInfo: false,
      recalcularCuotasAuto: false,
      vistaModoPrecioGremioUSD: false,
      setPanelFiltroActivo: vi.fn(),
      setColorDropdownAbierto: vi.fn(),
      setProductoInfo: vi.fn(),
      setMostrarModalInfo: vi.fn(),
      setMostrarFiltrosAvanzados: vi.fn(),
      setVistaModoCuotas: vi.fn(),
      setRecalcularCuotasAuto: vi.fn(),
      setVistaModoPrecioGremioUSD: vi.fn(),
      setMostrarExportModal: vi.fn(),
      setMostrarCalcularWebModal: vi.fn(),
    },
    permissions: {
      puedeEditar: true,
      puedeMarcarColor: true,
      puedeEditarWebTransf: true,
      puedeCalcularWebMasivo: true,
      puedeVerWebTarjeta,
    },
    showToast: vi.fn(),
  };
}

async function press(key) {
  await act(async () => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  });
}

/** Enter activates navigation mode at { rowIndex: 0, colIndex: 0 }. */
async function activarNavegacion() {
  await press('Enter');
}

describe('useTiendaKeyboard — mapeo de columnas navegables', () => {
  it('vista normal expone las 5 columnas en el mismo orden que los colIndex de Tienda.jsx', () => {
    const { result } = renderHook(() => useTiendaKeyboard(makeArgs()));

    expect(result.current.columnasEditables).toEqual(VISTA_NORMAL_CON_WEB_TARJETA);
  });

  it('omite web_tarjeta cuando falta el permiso tienda.ver_web_tarjeta', () => {
    const { result } = renderHook(() =>
      useTiendaKeyboard(makeArgs({ puedeVerWebTarjeta: false }))
    );

    expect(result.current.columnasEditables).toEqual([
      'precio_clasica',
      'precio_sugerido',
      'precio_gremio',
      'precio_web_transf',
    ]);
    expect(result.current.columnasEditables).not.toContain('web_tarjeta');
  });

  it('la vista cuotas no se ve afectada por el permiso de web tarjeta', () => {
    const { result } = renderHook(() =>
      useTiendaKeyboard(makeArgs({ vistaModoCuotas: true, puedeVerWebTarjeta: false }))
    );

    expect(result.current.columnasEditables).toEqual(VISTA_CUOTAS);
  });

  it('mantiene referencia estable entre renders (no recrea el listener)', () => {
    const args = makeArgs();
    const { result, rerender } = renderHook(() => useTiendaKeyboard(args));
    const primera = result.current.columnasEditables;

    rerender();

    expect(result.current.columnasEditables).toBe(primera);
  });
});

describe('useTiendaKeyboard — Enter abre el editor de la columna resaltada', () => {
  it.each([
    [0, 'precio_clasica'],
    [1, 'precio_sugerido'],
    [2, 'precio_gremio'],
    [3, 'precio_web_transf'],
    [4, 'web_tarjeta'],
  ])('colIndex %i edita la columna %s', async (colIndex, columnaEsperada) => {
    const iniciarEdicionDesdeTeclado = vi.fn();
    const { result } = renderHook(() =>
      useTiendaKeyboard(makeArgs({ pricing: { iniciarEdicionDesdeTeclado } }))
    );

    await activarNavegacion();
    for (let i = 0; i < colIndex; i += 1) {
      await press('ArrowRight');
    }
    expect(result.current.celdaActiva).toEqual({ rowIndex: 0, colIndex });

    await press('Enter');

    expect(iniciarEdicionDesdeTeclado).toHaveBeenCalledWith(
      expect.objectContaining({ item_id: 1 }),
      columnaEsperada
    );
  });
});

describe('useTiendaKeyboard — límites del colIndex', () => {
  it('ArrowRight no pasa de la última columna existente sin permiso de web tarjeta', async () => {
    const { result } = renderHook(() =>
      useTiendaKeyboard(makeArgs({ puedeVerWebTarjeta: false }))
    );

    await activarNavegacion();
    for (let i = 0; i < 10; i += 1) {
      await press('ArrowRight');
    }

    // 4 columnas → último índice válido es 3 (precio_web_transf), no 4.
    expect(result.current.celdaActiva).toEqual({ rowIndex: 0, colIndex: 3 });
  });

  it('End va a la última columna navegable y Home vuelve a la primera', async () => {
    const { result } = renderHook(() => useTiendaKeyboard(makeArgs()));

    await activarNavegacion();
    await press('End');
    expect(result.current.celdaActiva).toEqual({ rowIndex: 0, colIndex: 4 });

    await press('Home');
    expect(result.current.celdaActiva).toEqual({ rowIndex: 0, colIndex: 0 });
  });

  it('recorta el colIndex si el permiso de web tarjeta desaparece en caliente', async () => {
    const { result, rerender } = renderHook(
      ({ puedeVerWebTarjeta }) => useTiendaKeyboard(makeArgs({ puedeVerWebTarjeta })),
      { initialProps: { puedeVerWebTarjeta: true } }
    );

    await activarNavegacion();
    await press('End');
    expect(result.current.celdaActiva).toEqual({ rowIndex: 0, colIndex: 4 });

    await act(async () => {
      rerender({ puedeVerWebTarjeta: false });
    });

    // Sin la columna, el colIndex 4 apuntaría a una celda inexistente.
    expect(result.current.celdaActiva).toEqual({ rowIndex: 0, colIndex: 3 });
  });

  it('al cambiar de vista normal a cuotas el colIndex sigue en rango', async () => {
    const { result, rerender } = renderHook(
      ({ vistaModoCuotas }) =>
        useTiendaKeyboard(makeArgs({ vistaModoCuotas, puedeVerWebTarjeta: false })),
      { initialProps: { vistaModoCuotas: false } }
    );

    await activarNavegacion();
    await press('End');
    expect(result.current.celdaActiva).toEqual({ rowIndex: 0, colIndex: 3 });

    await act(async () => {
      rerender({ vistaModoCuotas: true });
    });

    const { colIndex } = result.current.celdaActiva;
    expect(colIndex).toBeLessThan(result.current.columnasEditables.length);
    expect(result.current.columnasEditables[colIndex]).toBeDefined();
  });
});
