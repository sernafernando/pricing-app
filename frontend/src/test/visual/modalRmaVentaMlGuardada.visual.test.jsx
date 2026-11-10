/**
 * RMA new case, "traza ML" of a sale known only to our stored ML sales (Ventas ML): a pack of two cartridges without
 * serial, each with its code and quantity sold and its Agregar button, inside the modal, in light and dark. Real
 * CSS, real Chromium.
 *
 *   VITE_RMA_VENTA_ML_SHOTS_DIR=<dir> pnpm exec vitest run --project=visual modalRmaVentaMlGuardada   (also saves screenshots)
 */
import { describe, it, expect, vi } from 'vitest';
import { render } from 'vitest-browser-react';
import { page } from 'vitest/browser';
import { setTheme } from './visualHelpers';
import api from '../../services/api';
import ModalRma from '../../components/ModalRma';

vi.mock('../../services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => permiso === 'rma.gestionar' }),
}));

const SHOTS_DIR = import.meta.env.VITE_RMA_VENTA_ML_SHOTS_DIR;

const PACK_ID = '2000000000000101';
const pedido = (mlId) => ({
  soh_id: 0,
  bra_id: 0,
  fecha: '2026-11-07 14:30:00+00:00',
  estado: 'paid',
  cust_id: null,
  cliente: 'COMPRADORPRUEBA',
  cliente_dni: null,
  cliente_telefono: null,
  cliente_email: null,
  ml_id: mlId,
  shipping_id: 40000000101,
});
const producto = (itemId, codigo, descripcion, cantidad) => ({
  serial: '',
  articulo: { item_id: itemId, codigo, descripcion, marca: null, categoria: null },
  movimientos: [],
  rma: [],
  cantidad,
});

const VENTA = {
  ml_id: PACK_ID,
  busqueda_por: 'ventas_ml',
  ml_ids_relacionados: ['2000000000000102', '2000000000000103'],
  shipping_ids_relacionados: ['40000000101'],
  pack_ids_relacionados: [PACK_ID],
  discrepancias_identificadores: [],
  webhook_previews: [],
  pedidos: [pedido('2000000000000102'), pedido('2000000000000103')],
  seriales: [
    producto(601, 'CART-NEGRO', 'Cartucho de tinta negro 664 para EcoTank', 2),
    producto(602, 'CART-COLOR', 'Cartucho de tinta cian 664 para EcoTank', 1),
  ],
  rma_por_factura: [],
  claims: [],
};

describe.each([
  { width: 1366, height: 900, theme: 'light' },
  { width: 1366, height: 900, theme: 'dark' },
])('ModalRma traza ML at $width px, $theme', ({ width, height, theme }) => {
  it('lists the products of a stored ML sale without serial, with code and quantity', async () => {
    api.get.mockImplementation((url) => {
      if (url === `/seriales/traza/ml/${PACK_ID}`) return Promise.resolve({ data: VENTA });
      if (url.startsWith('/seriales/traza/')) return Promise.reject(new Error('404')); // not a serial number
      return Promise.resolve({ data: [] });
    });
    await page.viewport(width, height);
    setTheme(theme);
    document.body.style.background = 'var(--cf-bg-app)';
    const screen = await render(<ModalRma caso={null} onClose={() => {}} />);

    await screen.getByPlaceholder('Ingresar serie o ID de venta ML...').fill(PACK_ID);
    await screen.getByRole('button', { name: /Buscar/ }).click();
    await expect.element(screen.getByText('CART-NEGRO · Cant. 2')).toBeVisible();
    await expect.element(screen.getByText('CART-COLOR · Cant. 1')).toBeVisible();
    expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(width);
    if (SHOTS_DIR) await page.screenshot({ path: `${SHOTS_DIR}/rma-traza-venta-ml-${theme}-${width}.png` });
  });
});
