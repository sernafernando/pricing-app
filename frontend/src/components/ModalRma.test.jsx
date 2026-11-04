import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import ModalRma from './ModalRma';
import api from '../services/api';

// Reported to the owner (2026-11-04): "cuando cargo un caso que no tiene numero de serie y lo tengo que cargar por
// el numero de compra de ML, no me trae la info del producto o los datos del cliente". A sale the ERP has no order
// for comes back with soh_id 0 and cust_id 0 (ML header only) and its products from the ML order detail. The
// response follows GET /seriales/traza/ml's TrazaMLResponse, with anonymized buyer data.

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => permiso === 'rma.gestionar' }),
}));

const PACK_ID = '2000000000000001';
const ORDER_ID = '2000000000000002';

const ventaSinPedidoErp = {
  ml_id: PACK_ID,
  busqueda_por: 'soh_mlid_fallback_mlo_direct',
  ml_ids_relacionados: [ORDER_ID],
  shipping_ids_relacionados: ['40000000001'],
  pack_ids_relacionados: [],
  discrepancias_identificadores: [],
  webhook_previews: [],
  pedidos: [
    {
      soh_id: 0,
      bra_id: 45,
      fecha: '2026-10-25 10:00:00',
      estado: 'paid',
      cust_id: 0,
      cliente: 'Comprador De Prueba',
      cliente_dni: '20000000001',
      cliente_telefono: 'XXXXXXX',
      cliente_email: null,
      ml_id: ORDER_ID,
      shipping_id: 40000000001,
    },
  ],
  seriales: [
    {
      serial: '',
      articulo: { item_id: 501, codigo: '7790000000011', descripcion: 'Router de prueba', marca: null, categoria: null },
      movimientos: [],
      rma: [],
    },
  ],
  rma_por_factura: [],
  claims: [],
};

function mockApi() {
  api.get.mockImplementation((url) => {
    if (url === '/rma-seguimiento/opciones' || url === '/rma-seguimiento/depositos') {
      return Promise.resolve({ data: [] });
    }
    if (url === `/seriales/traza/ml/${PACK_ID}`) return Promise.resolve({ data: ventaSinPedidoErp });
    return Promise.reject(new Error(`not found: ${url}`));
  });
}

async function buscar(valor) {
  render(<ModalRma caso={null} onClose={() => {}} />);
  const input = screen.getByPlaceholderText('Ingresar serie o ID de venta ML...');
  fireEvent.change(input, { target: { value: valor } });
  fireEvent.keyDown(input, { key: 'Enter' });
  await screen.findByText(`Venta ML #${ORDER_ID}`);
}

describe('ModalRma - ML sale without serials nor ERP order', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi();
  });

  it('shows no stray 0 for a sale with no ERP customer nor ERP order', async () => {
    await buscar(PACK_ID);

    const detalles = screen.getByText('Comprador De Prueba').closest('div').parentElement;
    const textos = Array.from(detalles.childNodes)
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent);
    expect(textos).not.toContain('0');
    expect(within(detalles).queryByText(/Cliente #/)).toBeNull();
    expect(within(detalles).queryByText(/Pedido #/)).toBeNull();
  });

  it('offers the sale product and Agregar fills the article and the customer', async () => {
    await buscar(PACK_ID);

    const producto = screen.getByText('Router de prueba').parentElement.parentElement;
    fireEvent.click(within(producto).getByRole('button', { name: /Agregar/ }));

    expect(screen.getByText('Artículos (1)')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Comprador De Prueba')).toBeInTheDocument();
    expect(screen.getByDisplayValue('20000000001')).toBeInTheDocument();
    expect(screen.getByDisplayValue(ORDER_ID)).toBeInTheDocument();
    expect(screen.getByPlaceholderText('ID del cliente en ERP')).toHaveValue(null);
  });
});
