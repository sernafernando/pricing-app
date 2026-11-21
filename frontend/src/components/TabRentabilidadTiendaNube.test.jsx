/**
 * Rentabilidad Tienda Nube: sales without a known cost (costo SI interface §7; the endpoint returns null costo, ganancia
 * and markup when no sale of a card has a cost, and counts the lines without one in `ventas_sin_costo`). Those figures
 * read "Sin costo", never "$0", and a card (and the totals) with sales without cost says how many and that they add
 * nothing to the cost or the ganancia.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TabRentabilidadTiendaNube from './TabRentabilidadTiendaNube';
import api from '../services/api';

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));
vi.mock('./ModalOffset', () => ({ default: () => null }));

const card = (nombre, figures) => ({
  nombre,
  tipo: 'marca',
  identificador: nombre,
  offset_total: 0,
  desglose_offsets: null,
  ...figures,
});

const RESPUESTA = {
  cards: [
    card('ACME', { total_ventas: 2, monto_venta: 1500, comision_tn: 15, monto_limpio: 1485, costo_total: 600, ganancia: 390, markup_promedio: 65, ventas_sin_costo: 1, ganancia_con_offset: 390, markup_con_offset: 65 }),
    card('CERO', { total_ventas: 1, monto_venta: 300, comision_tn: 3, monto_limpio: 297, costo_total: null, ganancia: null, markup_promedio: null, ventas_sin_costo: 1, ganancia_con_offset: null, markup_con_offset: null }),
    card('FULL', { total_ventas: 1, monto_venta: 1100, comision_tn: 11, monto_limpio: 1089, costo_total: 650, ganancia: 439, markup_promedio: 67.54, ventas_sin_costo: 0, ganancia_con_offset: 439, markup_con_offset: 67.54 }),
  ],
  totales: card('TOTAL', { total_ventas: 4, monto_venta: 2900, comision_tn: 29, monto_limpio: 2871, costo_total: 1250, ganancia: 829, markup_promedio: 66.32, ventas_sin_costo: 2, ganancia_con_offset: 829, markup_con_offset: 66.32 }),
  filtros_aplicados: { nivel_agrupacion: 'marca', comision_tn_porcentaje: 1 },
};

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.get).mockImplementation((url) =>
    Promise.resolve({ data: url.endsWith('/filtros') ? { marcas: [], categorias: [], subcategorias: [] } : RESPUESTA }),
  );
});

const renderTab = () =>
  render(
    <MemoryRouter>
      <TabRentabilidadTiendaNube fechaDesde="2026-01-01" fechaHasta="2026-01-31" />
    </MemoryRouter>,
  );

// The card holding the heading `nombre`.
const cardDe = async (nombre) => (await screen.findByRole('heading', { name: nombre })).parentElement.parentElement;
// Intl writes "$\u00a00": compare with a plain space.
const texto = (el) => el.textContent.replace(/\u00a0/g, ' ');

describe('TabRentabilidadTiendaNube with sales without cost', () => {
  it('a card without any costed sale shows "Sin costo" for costo, ganancia and markup, never $0', async () => {
    renderTab();
    const cero = await cardDe('CERO');

    const marcas = within(cero).getAllByLabelText('Sin costo');
    expect(marcas).toHaveLength(3);
    for (const marca of marcas) expect(marca.textContent).toBe('Sin costo');
    expect(texto(cero)).not.toMatch(/\$ ?0(?![\d.])/);
    expect(texto(cero)).not.toMatch(/(^|[^\d.,])0(\.00)?%/);
    expect(within(cero).getByText('1 venta sin costo: no suman al costo ni a la ganancia')).toBeTruthy();
  });

  it('a card with some sales without cost keeps its costed figures and says how many have none', async () => {
    renderTab();
    const acme = await cardDe('ACME');

    expect(within(acme).queryAllByLabelText('Sin costo')).toHaveLength(0);
    expect(texto(acme)).toContain('$ 600');
    expect(texto(acme)).toContain('65.00%');
    expect(within(acme).getByText('1 venta sin costo: no suman al costo ni a la ganancia')).toBeTruthy();
  });

  it('the totals say how many sales have no cost (plural)', async () => {
    renderTab();

    expect(await screen.findByText('2 ventas sin costo: no suman al costo ni a la ganancia')).toBeTruthy();
  });

  it('a card with every sale costed is unchanged: no "Sin costo", no note', async () => {
    renderTab();
    const full = await cardDe('FULL');

    expect(within(full).queryAllByLabelText('Sin costo')).toHaveLength(0);
    expect(within(full).queryByText(/sin costo:/)).toBeNull();
    expect(texto(full)).toContain('$ 650');
    expect(texto(full)).toContain('67.54%');
  });

  it('totals without any costed sale colour no ganancia green: null is not a profit', async () => {
    const sinCosto = { costo_total: null, ganancia: null, markup_promedio: null, ganancia_con_offset: null, markup_con_offset: null, offset_total: -100 };
    vi.mocked(api.get).mockImplementation((url) =>
      Promise.resolve({
        data: url.endsWith('/filtros')
          ? { marcas: [], categorias: [], subcategorias: [] }
          : { ...RESPUESTA, totales: { ...RESPUESTA.totales, ...sinCosto } },
      }),
    );
    renderTab();

    for (const etiqueta of ['Ganancia', 'Ganancia c/Offset']) {
      const valor = (await screen.findByText(etiqueta, { selector: 'span' })).nextElementSibling;
      expect(valor.style.color).toBe('');
    }
  });
});
