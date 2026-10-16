/**
 * The best-offer column shows "Hasta DD/MM" from mejor_oferta_fecha_hasta, a
 * SQL Date (OfertaML.fecha_hasta) serialized as a bare YYYY-MM-DD. Parsed
 * natively it is UTC midnight, which in Argentina (UTC-3) renders the
 * PREVIOUS day.
 *
 * Kept apart from Productos.test.jsx, whose characterization tests must stay
 * byte-identical; the render setup below mirrors its setupApiMocks.
 */

import { describe, it, expect, vi } from 'vitest';
import { screen, act } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import Productos from './Productos';
import api, { productosAPI } from '../services/api';

vi.mock('../hooks/useSSEChannel', () => ({ useSSEChannel: vi.fn() }));

const PRODUCTO = {
  item_id: 'ITEM001',
  codigo: 'SKU001',
  descripcion: 'Producto Test',
  marca: 'BRAND_X',
  precio_lista_ml: 100,
  precio_clasica: 100,
  costo: 10,
  costo_ars: 10000,
  moneda_costo: 'USD',
  tipo_cambio: 1000,
  markup: 5.0,
  markup_clasica: 5.0,
  participa_rebate: false,
  participa_web_transferencia: false,
  stock: 5,
  out_of_cards: false,
  subcategoria: 'Sub1',
  mejor_oferta_precio: 90,
  mejor_oferta_fecha_hasta: '2026-12-31',
};

function setupApiMocks() {
  productosAPI.listar.mockResolvedValue({ data: { productos: [PRODUCTO], total: 1 } });
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

describe('Productos - best offer end date', () => {
  it('shows "Hasta DD/MM" on the offer end calendar day in Argentina', async () => {
    // Guard: without this premise the test would pass without exercising the bug.
    expect(new Date('2026-12-31').toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit' })).toBe('30/12');

    setupApiMocks();
    await act(async () => {
      renderWithRouter(<Productos />);
    });

    expect(await screen.findByText(/^Hasta /)).toHaveTextContent('Hasta 31/12');
  });
});
