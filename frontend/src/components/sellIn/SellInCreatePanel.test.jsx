import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInAPI } from '../../services/sellInAPI';
import { COMPRA_ARS, PREVIEW, PRODUCTOS } from './sellInFixtures';
import SellInCreatePanel from './SellInCreatePanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { preview: vi.fn(), crear: vi.fn(), proveedores: vi.fn() },
}));

const PROVEEDORES = { proveedores: [{ id: 7, nombre: 'TP-Link', cuit: '30-1' }], total: 1, page: 1, page_size: 10 };

beforeEach(() => {
  vi.clearAllMocks();
  productosAPI.listar.mockResolvedValue({ data: { productos: PRODUCTOS, total: 2, page: 1, page_size: 10 } });
  sellInAPI.proveedores.mockResolvedValue({ data: PROVEEDORES });
  sellInAPI.preview.mockResolvedValue({ data: PREVIEW });
  sellInAPI.crear.mockResolvedValue({ data: COMPRA_ARS });
});

const renderPanel = (props = {}) => {
  const onCreated = vi.fn();
  const onClose = vi.fn();
  render(<SellInCreatePanel onCreated={onCreated} onClose={onClose} {...props} />);
  return { onCreated, onClose };
};

/** Fills an ARS purchase of 1000 over SW-8 x10 and SW-16 x10 (the backend tests' purchase). */
async function fillCompra(user) {
  await user.click(screen.getByRole('button', { name: 'ARS' }));
  await user.type(screen.getByLabelText('Monto total'), '1000');
  const buscador = screen.getByRole('group', { name: 'Agregar producto' });
  await user.type(within(buscador).getByRole('searchbox'), 'switch');
  await user.click(await within(buscador).findByRole('button', { name: /SW-8/ }));
  // Picking clears the box: the next product is a new search.
  expect(within(buscador).getByRole('searchbox')).toHaveValue('');
  await user.type(within(buscador).getByRole('searchbox'), 'switch');
  await user.click(await within(buscador).findByRole('button', { name: /SW-16/ }));
  for (const input of screen.getAllByLabelText(/Cantidad de/)) {
    await user.clear(input);
    await user.type(input, '10');
  }
}

describe('SellInCreatePanel', () => {
  it('previews the split with the amount, currency, formula and lines it was given', async () => {
    const user = userEvent.setup();
    renderPanel();
    await fillCompra(user);
    expect(productosAPI.listar).toHaveBeenCalledWith({ search: 'switch', page_size: 10 });
    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));

    expect(sellInAPI.preview).toHaveBeenCalledWith({
      moneda: 'ARS',
      monto_total: '1000',
      tipo_cambio: null,
      formula: 'proporcional',
      lineas: [
        { item_id: 4512, cantidad: 10 },
        { item_id: 4513, cantidad: 10 },
      ],
    });
    const previa = await screen.findByRole('table', { name: 'Vista previa por ítem' });
    const fila = within(previa).getByText('Switch 8 bocas').closest('tr');
    expect(within(fila).getByText('$ 250,00')).toBeInTheDocument();
    expect(within(fila).getByText('$ 100,00')).toBeInTheDocument();
    expect(within(fila).getByText('$ 75,00')).toBeInTheDocument();
    expect(within(previa).getByText('$ 3.000,00')).toBeInTheDocument();
  });

  it('requires the FX rate for USD and shows what the total is worth in pesos', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'USD' }));
    await user.type(screen.getByLabelText('Monto total'), '4500');
    await user.type(screen.getByLabelText('Tipo de cambio'), '1065.5');
    expect(screen.getByText('$ 4.794.750,00')).toBeInTheDocument();
  });

  it('in manual, blocks the preview until the amounts add up to the total', async () => {
    const user = userEvent.setup();
    renderPanel();
    await fillCompra(user);
    await user.click(screen.getByRole('button', { name: 'Manual' }));
    const [primero, segundo] = screen.getAllByLabelText(/Monto manual de/);
    await user.type(primero, '400');
    await user.type(segundo, '500');
    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Los montos manuales suman $ 900,00 y el total es $ 1.000,00.');
    expect(sellInAPI.preview).not.toHaveBeenCalled();

    await user.clear(segundo);
    await user.type(segundo, '600');
    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
    expect(sellInAPI.preview).toHaveBeenCalledWith(
      expect.objectContaining({
        formula: 'manual',
        lineas: [
          { item_id: 4512, cantidad: 10, monto_manual: '400' },
          { item_id: 4513, cantidad: 10, monto_manual: '600' },
        ],
      }),
    );
  });

  it('saves only after a current preview, with the purchase data, and hands back the created purchase', async () => {
    const user = userEvent.setup();
    const { onCreated } = renderPanel();
    await fillCompra(user);
    const guardar = screen.getByRole('button', { name: 'Guardar sell in' });
    expect(guardar).toBeDisabled();

    await user.clear(screen.getByLabelText('Fecha de compra'));
    await user.type(screen.getByLabelText('Fecha de compra'), '2026-10-01');
    await user.type(screen.getByLabelText('Descripción'), 'Bonificación Q4 switches');
    await user.type(screen.getByLabelText('Pedido de compra (N°)'), '15');
    const buscadorProveedor = screen.getByRole('group', { name: 'Proveedor' });
    await user.type(within(buscadorProveedor).getByRole('searchbox'), 'tp');
    await user.click(await within(buscadorProveedor).findByRole('button', { name: /TP-Link/ }));
    expect(sellInAPI.proveedores).toHaveBeenCalledWith('tp');

    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
    await screen.findByRole('table', { name: 'Vista previa por ítem' });
    expect(guardar).toBeEnabled();
    await user.click(guardar);

    expect(sellInAPI.crear).toHaveBeenCalledWith({
      moneda: 'ARS',
      monto_total: '1000',
      tipo_cambio: null,
      formula: 'proporcional',
      lineas: [
        { item_id: 4512, cantidad: 10 },
        { item_id: 4513, cantidad: 10 },
      ],
      fecha_compra: '2026-10-01',
      fecha_ingreso: null,
      cuenta_desde: 'compra',
      proveedor_id: 7,
      pedido_compra_id: 15,
      descripcion: 'Bonificación Q4 switches',
    });
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(COMPRA_ARS));
  });

  it('a change after the preview discards it, so what is saved is what was seen', async () => {
    const user = userEvent.setup();
    renderPanel();
    await fillCompra(user);
    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
    await screen.findByRole('table', { name: 'Vista previa por ítem' });
    await user.type(screen.getByLabelText('Monto total'), '0');
    expect(screen.queryByRole('table', { name: 'Vista previa por ítem' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Guardar sell in' })).toBeDisabled();
  });

  it('shows the readable message of a rejected preview', async () => {
    const user = userEvent.setup();
    sellInAPI.preview.mockRejectedValue({
      response: { status: 422, data: { error: { code: 'VALIDATION_ERROR', message: 'Falta el tipo de cambio' } } },
    });
    renderPanel();
    await fillCompra(user);
    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Falta el tipo de cambio');
  });
});
