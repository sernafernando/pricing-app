/**
 * /notificaciones (sell-in-costo-si T3 PR 10): a low-markup notification's sale cost and current cost (costo SI,
 * frozen when the notification was made) read "Sin costo" when unknown, never "$N/A" nor a $0.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import api from '../services/api';
import Notificaciones from './Notificaciones';

const reciente = (overrides) => ({
  id: 5,
  tipo: 'markup_bajo',
  mensaje: 'Markup bajo',
  leida: true,
  severidad: 'WARNING',
  estado: 'PENDIENTE',
  fecha_creacion: '2026-11-14T10:00:00Z',
  item_id: 9000,
  markup_real: -4.5,
  monto_venta: 20000,
  costo_operacion: 1234.5,
  costo_actual: null,
  ...overrides,
});

const grupoMarkup = (overrides) => ({
  item_id: 9000,
  tipo: 'markup_bajo',
  markup_real: -4.5,
  codigo_producto: 'COD-9000',
  descripcion_producto: 'Producto 9000',
  pm: null,
  count: 1,
  primera_fecha: '2026-11-13T09:00:00Z',
  ultima_fecha: '2026-11-13T09:00:00Z',
  notificacion_reciente: reciente(overrides),
  notificaciones_ids: [5],
});

const valorDe = (etiqueta) => screen.getByText(etiqueta, { selector: 'strong' }).nextElementSibling.textContent;

const abrir = async (grupo) => {
  api.get.mockImplementation((url) => {
    if (url === '/notificaciones/stats') return Promise.resolve({ data: { total: 1, no_leidas: 0, por_tipo: {} } });
    if (url === '/notificaciones/agrupadas') return Promise.resolve({ data: [grupo] });
    return Promise.resolve({ data: {} });
  });
  const user = userEvent.setup();
  renderWithRouter(<Notificaciones />);
  await user.click(await screen.findByText('COD-9000 - Producto 9000'));
};

describe('Notificaciones — costs of a low-markup notification', () => {
  beforeEach(() => {
    api.get.mockReset();
  });

  it('shows a known cost in pesos and an unknown one as "Sin costo"', async () => {
    await abrir(grupoMarkup());

    expect(valorDe('Costo de la Venta:')).toBe('$1.234,50');
    expect(valorDe('Costo Actual:')).toBe('Sin costo');
  });

  it('a stored 0 (an unknown cost of old notifications) is "Sin costo" too, never $0', async () => {
    await abrir(grupoMarkup({ costo_operacion: 0, costo_actual: 987 }));

    expect(valorDe('Costo de la Venta:')).toBe('Sin costo');
    expect(valorDe('Costo Actual:')).toBe('$987,00');
  });
});
