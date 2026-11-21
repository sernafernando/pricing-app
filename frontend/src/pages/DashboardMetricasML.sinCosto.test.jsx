import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import DashboardMetricasML from './DashboardMetricasML';
import api from '../services/api';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}));

const operacion = (id, codigo, costo) => ({
  id_operacion: id,
  ml_id: `${id}`,
  fecha_venta: '2026-10-05T15:00:00',
  item_id: id,
  codigo,
  descripcion: `Producto ${codigo}`,
  marca: 'MARCA DEMO',
  categoria: 'CAMARAS',
  cantidad: '1',
  monto_unitario: '100000',
  monto_total: '100000',
  iva: '21',
  pricelist_id: 4,
  tipo_publicacion: 'Clásica',
  costo_sin_iva: costo,
  costo_total: costo,
  comision_porcentaje: '12',
  comision_pesos: '12000',
  costo_envio: '1500',
  monto_limpio: '80000',
  markup_porcentaje: costo === null ? null : '220',
  offset_flex: '0',
  is_cancelled: false,
});

beforeEach(() => {
  seedTiendasOficiales([{ store_id: 57997, nombre: 'Gauss', clave: null, orden: 0, activa: true }]);
  api.get.mockReset();
  api.get.mockImplementation((url) => {
    if (url.includes('operaciones-con-metricas')) {
      return Promise.resolve({ data: [operacion(1, 'SINCOSTO', null), operacion(2, 'CONCOSTO', '25000')] });
    }
    return Promise.resolve({ data: url.includes('disponibles') || url.includes('/usuarios/pms') || url.includes('por-') ? [] : {} });
  });
});

afterAll(resetTiendasOficiales);

describe('DashboardMetricasML operations without a known cost', () => {
  it('shows a null cost, costo total and markup as "sin costo", never $0', async () => {
    await renderWithRouter(<DashboardMetricasML />, { initialEntries: ['/?tab=operaciones'] });

    const sinCosto = (await screen.findByText('SINCOSTO')).closest('tr');
    expect(within(sinCosto).getAllByLabelText('Sin costo')).toHaveLength(3);
    expect(within(sinCosto).getAllByText('—').length).toBeGreaterThanOrEqual(3);
    expect(within(sinCosto).queryByText(/^\$\s?0$/)).not.toBeInTheDocument();
    expect(within(sinCosto).queryByText('0.00%')).not.toBeInTheDocument();

    const conCosto = screen.getByText('CONCOSTO').closest('tr');
    expect(within(conCosto).queryByLabelText('Sin costo')).not.toBeInTheDocument();
    expect(within(conCosto).getAllByText(/25\.000/)).toHaveLength(2);
    expect(within(conCosto).getByText('220.00%')).toBeInTheDocument();
  });
});
