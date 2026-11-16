/**
 * /notificaciones: family tabs, server-side paging of the flat list, and
 * non-markup groups rendering their own message instead of the markup template.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import api from '../services/api';
import Notificaciones from './Notificaciones';

const notif = (overrides) => ({
  id: 1,
  tipo: 'markup_bajo',
  mensaje: 'Markup bajo',
  leida: true,
  severidad: 'INFO',
  estado: 'PENDIENTE',
  fecha_creacion: '2026-11-14T10:00:00Z',
  ...overrides,
});

const grupo = (overrides) => ({
  item_id: null,
  markup_real: null,
  codigo_producto: null,
  descripcion_producto: null,
  pm: null,
  count: 1,
  primera_fecha: '2026-11-13T09:00:00Z',
  ultima_fecha: '2026-11-13T09:00:00Z',
  notificaciones_ids: [1],
  ...overrides,
});

const grupoFailover = grupo({
  tipo: 'ml_bot.llm_failover',
  count: 1400,
  primera_fecha: '2026-07-30T23:09:00Z',
  ultima_fecha: '2026-11-14T23:11:00Z',
  notificacion_reciente: notif({
    id: 900,
    tipo: 'ml_bot.llm_failover',
    severidad: 'WARNING',
    mensaje: "Bot ML: el proveedor LLM 'openrouter' falló — failover activo a 'groq'.",
  }),
  notificaciones_ids: [900],
});

const grupoFactura = grupo({
  item_id: 321,
  tipo: 'compras.factura_cargada',
  notificacion_reciente: notif({
    id: 371433,
    tipo: 'compras.factura_cargada',
    mensaje: 'Factura 00002-00006138 cargada en P-321 (Proveedor SA).',
  }),
  notificaciones_ids: [371433],
});

const grupoMarkup = grupo({
  item_id: 9000,
  tipo: 'markup_bajo',
  markup_real: -4.5,
  codigo_producto: 'COD-9000',
  descripcion_producto: 'Producto 9000',
  notificacion_reciente: notif({ id: 5, markup_real: -4.5 }),
  notificaciones_ids: [5],
});

const stats = {
  total: 2300,
  no_leidas: 3,
  por_tipo: {},
  no_leidas_por_familia: { compras: 1, markup: 2, tecnicas: 0, otras: 0 },
};

const flatPage = (offset) =>
  Array.from({ length: 20 }, (_, i) => notif({ id: offset + i + 1, mensaje: `Fila ${offset + i + 1}` }));

describe('Notificaciones page — families, paging and non-markup rendering', () => {
  beforeEach(() => {
    api.get.mockImplementation((url, config) => {
      if (url === '/notificaciones/stats') return Promise.resolve({ data: stats });
      if (url === '/notificaciones/agrupadas') {
        return Promise.resolve({ data: [grupoFailover, grupoFactura, grupoMarkup] });
      }
      if (url === '/notificaciones/total') return Promise.resolve({ data: { total: 2300 } });
      if (url === '/notificaciones') return Promise.resolve({ data: flatPage(config?.params?.offset ?? 0) });
      return Promise.resolve({ data: {} });
    });
  });

  it('non-markup groups render their title and latest message, never the markup template', async () => {
    renderWithRouter(<Notificaciones />);

    const failover = await screen.findByText(/el proveedor LLM 'openrouter' falló/);
    const cardFailover = failover.closest('[data-testid="notif-grupo"]');
    expect(within(cardFailover).getByText('Bot ML: falla de proveedor LLM')).toBeInTheDocument();
    expect(within(cardFailover).getByText(/1400 notificaciones/)).toBeInTheDocument();
    expect(within(cardFailover).queryByText(/Markup Real/)).not.toBeInTheDocument();
    expect(within(cardFailover).queryByText(/^ - $/)).not.toBeInTheDocument();

    const factura = screen.getByText(/Factura 00002-00006138 cargada en P-321/);
    const cardFactura = factura.closest('[data-testid="notif-grupo"]');
    expect(within(cardFactura).getByText('Factura cargada')).toBeInTheDocument();
    expect(within(cardFactura).queryByText(/Markup Real/)).not.toBeInTheDocument();

    const cardMarkup = screen.getByText('COD-9000 - Producto 9000').closest('[data-testid="notif-grupo"]');
    expect(within(cardMarkup).getByText(/Markup Real: -4.5%/)).toBeInTheDocument();
  });

  it('expanding a compras group shows its message and does not look up a product price', async () => {
    const user = userEvent.setup();
    renderWithRouter(<Notificaciones />);

    const factura = await screen.findByText(/Factura 00002-00006138 cargada en P-321/);
    await user.click(factura);

    expect(screen.queryByText('📊 Operación Más Reciente')).not.toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalledWith('/productos/321/pricing-stored');
  });

  it('the Compras tab filters server-side with its unread count', async () => {
    const user = userEvent.setup();
    renderWithRouter(<Notificaciones />);

    const tab = await screen.findByRole('tab', { name: /Compras\s*1/ });
    await user.click(tab);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/notificaciones/agrupadas', {
        params: { solo_no_leidas: false, familia: 'compras' },
      });
    });
  });

  it('the flat list pages on the server and reaches rows past the first hundred', async () => {
    const user = userEvent.setup();
    renderWithRouter(<Notificaciones />);

    await user.click(await screen.findByLabelText('Agrupar por producto/markup'));
    expect(await screen.findByText('Fila 1')).toBeInTheDocument();
    expect(screen.getByText('Página 1 de 115')).toBeInTheDocument();

    for (let i = 0; i < 6; i += 1) {
      await user.click(screen.getByRole('button', { name: /Siguiente/ }));
    }

    expect(await screen.findByText('Fila 121')).toBeInTheDocument();
    expect(screen.getByText('Página 7 de 115')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/notificaciones', {
      params: expect.objectContaining({ limit: 20, offset: 120, orden: 'severidad_desc' }),
    });
    expect(api.get).toHaveBeenCalledWith('/notificaciones/total', {
      params: expect.not.objectContaining({ limit: expect.anything() }),
    });
  });
});
