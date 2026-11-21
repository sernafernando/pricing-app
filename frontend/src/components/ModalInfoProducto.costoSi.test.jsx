import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ModalInfoProducto from './ModalInfoProducto';
import api from '../services/api';

// The product info's Costos section shows the costo SI next to the list cost (S13 two columns), from
// `/productos/{id}/detalle`'s `costo_si` (inside the `ver_info_pricing` gate, interfaz §6).

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => permiso === 'productos.ver_info_pricing' }),
}));

const PRODUCTO = {
  item_id: 1,
  codigo: 'ARCHER-AX55',
  descripcion: 'Router Archer AX55',
  moneda_costo: 'USD',
  costo: 30,
  tipo_cambio_usado: 1000,
  costo_ars: 30000,
  iva: 21,
  costo_envio: 0,
};

const detalle = (costoSi) => ({
  data: { producto: { ...PRODUCTO, costo_si: costoSi }, pricing: { markup: 20 }, ultimas_compras: [], publicaciones_ml: [] },
});

const valorDe = async (label) => (await screen.findByText(label)).nextElementSibling;

describe('ModalInfoProducto - costo SI', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows the costo SI in its currency with its pesos, right after the list cost', async () => {
    api.get.mockResolvedValue(
      detalle({ costo: 25, moneda: 'USD', fuente: 'costo_si', desde: '2026-10-01', tipo_cambio: 1000, tipo_cambio_fecha: '2026-11-20', costo_ars: 25000 }),
    );
    render(<ModalInfoProducto isOpen onClose={() => {}} itemId={1} />);

    const valor = await valorDe('Costo SI:');
    expect(valor).toHaveTextContent('USD 25,00 · $ 25.000,00');
    expect(valor.querySelector('[title]').getAttribute('title')).toContain('Costo SI desde 01/10/26');
    const labels = [...document.querySelectorAll('.info-label')].map((l) => l.textContent);
    expect(labels.indexOf('Costo SI:')).toBe(labels.indexOf('Costo (USD):') + 1);
  });

  it('marks the list cost that stands in, and an unknown one reads "—", never $ 0', async () => {
    api.get.mockResolvedValue(detalle({ costo: 28, moneda: 'USD', fuente: 'lista', costo_ars: null }));
    const { unmount } = render(<ModalInfoProducto isOpen onClose={() => {}} itemId={1} />);
    expect(await valorDe('Costo SI:')).toHaveTextContent(/^USD 28,00 lista$/);
    unmount();

    api.get.mockResolvedValue(detalle(null));
    render(<ModalInfoProducto isOpen onClose={() => {}} itemId={1} />);
    expect(await valorDe('Costo SI:')).toHaveTextContent(/^—$/);
  });
});
