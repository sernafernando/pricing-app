import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInAPI } from '../../services/sellInAPI';
import { COMPRA_ARS, PREFILL, PREVIEW, PRODUCTOS } from './sellInFixtures';
import SellInCreatePanel from './SellInCreatePanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { preview: vi.fn(), crear: vi.fn(), proveedores: vi.fn(), prefill: vi.fn() },
}));

const PROVEEDORES = { proveedores: [{ id: 7, nombre: 'TP-Link', cuit: '30-1' }], total: 1, page: 1, page_size: 10 };

beforeEach(() => {
  vi.clearAllMocks();
  productosAPI.listar.mockResolvedValue({ data: { productos: PRODUCTOS, total: 2, page: 1, page_size: 10 } });
  sellInAPI.proveedores.mockResolvedValue({ data: PROVEEDORES });
  sellInAPI.preview.mockResolvedValue({ data: PREVIEW });
  sellInAPI.crear.mockResolvedValue({ data: COMPRA_ARS });
  sellInAPI.prefill.mockResolvedValue({ data: PREFILL });
});

const renderPanel = (props = {}) => {
  const onCreated = vi.fn();
  const onClose = vi.fn();
  render(<SellInCreatePanel onCreated={onCreated} onClose={onClose} {...props} />);
  return { onCreated, onClose };
};

/** Links Compras operation `numero` to the sell in. */
async function agregarOperacion(user, numero) {
  await user.type(screen.getByLabelText('Pedido de compra (N°)'), String(numero));
  await user.click(screen.getByRole('button', { name: 'Agregar operación' }));
}

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

  it('shows what a USD total is worth in pesos at the FX rate typed', async () => {
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
      pedido_compra_ids: [],
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

  it('blocks the preview of a USD purchase without FX rate, as the backend would refuse it', async () => {
    const user = userEvent.setup();
    renderPanel();
    await fillCompra(user);
    await user.click(screen.getByRole('button', { name: 'USD' }));
    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Una compra en USD necesita el tipo de cambio.');
    expect(sellInAPI.preview).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Guardar sell in' })).toBeDisabled();
  });

  it('a preview that answers after an edit is dropped: save stays off and saves nothing stale', async () => {
    const user = userEvent.setup();
    let responder;
    sellInAPI.preview.mockReturnValue(new Promise((resolve) => (responder = resolve)));
    renderPanel();
    await fillCompra(user);
    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
    await user.type(screen.getByLabelText('Monto total'), '0');
    responder({ data: PREVIEW });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Calcular vista previa' })).toBeEnabled());
    expect(screen.queryByRole('table', { name: 'Vista previa por ítem' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Guardar sell in' })).toBeDisabled();
  });

  it('a rejected preview that answers after an edit shows no stale error', async () => {
    const user = userEvent.setup();
    let rechazar;
    sellInAPI.preview.mockReturnValue(new Promise((_, reject) => (rechazar = reject)));
    renderPanel();
    await fillCompra(user);
    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
    await user.type(screen.getByLabelText('Monto total'), '0');
    rechazar({ response: { status: 422, data: { error: { message: 'Monto viejo inválido' } } } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Calcular vista previa' })).toBeEnabled());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
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

  it('links several operations, asks their prefill for each set, and saves them as pedido_compra_ids', async () => {
    const user = userEvent.setup();
    const { onCreated } = renderPanel();
    await agregarOperacion(user, 15);
    await agregarOperacion(user, 16);
    await agregarOperacion(user, 17);
    await user.click(screen.getByRole('button', { name: 'Quitar operación 17' }));
    expect(screen.getByText('N° 15')).toBeInTheDocument();
    expect(screen.getByText('N° 16')).toBeInTheDocument();
    expect(screen.queryByText('N° 17')).not.toBeInTheDocument();
    await waitFor(() => expect(sellInAPI.prefill).toHaveBeenLastCalledWith([15, 16]));

    await user.type(screen.getByLabelText('Monto total'), '1000');
    await user.type(screen.getByLabelText('Tipo de cambio'), '1000');
    await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
    await screen.findByRole('table', { name: 'Vista previa por ítem' });
    await user.click(screen.getByRole('button', { name: 'Guardar sell in' }));

    expect(sellInAPI.crear).toHaveBeenCalledWith(
      expect.objectContaining({
        pedido_compra_ids: [15, 16],
        proveedor_id: 7,
        fecha_ingreso: '2026-10-05',
        lineas: [
          { item_id: 4512, cantidad: 12 },
          { item_id: 4513, cantidad: 4 },
        ],
      }),
    );
    expect(sellInAPI.crear.mock.calls[0][0]).not.toHaveProperty('pedido_compra_id');
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(COMPRA_ARS));
  });

  it('fills an empty form from the operations, and only suggests their currency', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'ARS' }));
    await agregarOperacion(user, 15);

    expect(await screen.findByText('TP-Link')).toBeInTheDocument();
    expect(screen.getByLabelText('Fecha de ingreso')).toHaveValue('2026-10-05');
    expect(screen.getByLabelText('Cantidad de SW-8')).toHaveValue(12);
    expect(screen.getByLabelText('Cantidad de SW-16')).toHaveValue(4);
    // The sell in keeps its own currency: the operations' one is offered, not imposed.
    expect(screen.getByRole('button', { name: 'ARS' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Las operaciones están en USD.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Usar USD' }));
    expect(screen.getByRole('button', { name: 'USD' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText('Las operaciones están en USD.')).not.toBeInTheDocument();
  });

  it('keeps typed lines, date and supplier unless the user confirms replacing the lines', async () => {
    const user = userEvent.setup();
    renderPanel();
    await fillCompra(user);
    await user.type(screen.getByLabelText('Fecha de ingreso'), '2026-10-09');
    await agregarOperacion(user, 15);

    expect(await screen.findByText('Ya hay productos cargados. ¿Reemplazarlos por los de las operaciones?')).toBeInTheDocument();
    expect(screen.getByLabelText('Cantidad de SW-8')).toHaveValue(10);
    expect(screen.getByLabelText('Cantidad de SW-16')).toHaveValue(10);
    expect(screen.getByLabelText('Fecha de ingreso')).toHaveValue('2026-10-09');
    await user.click(screen.getByRole('button', { name: 'Mantener los actuales' }));
    expect(screen.queryByText(/Ya hay productos cargados/)).not.toBeInTheDocument();
    expect(screen.getByLabelText('Cantidad de SW-8')).toHaveValue(10);

    await agregarOperacion(user, 16);
    await user.click(await screen.findByRole('button', { name: 'Reemplazar productos' }));
    expect(screen.getByLabelText('Cantidad de SW-8')).toHaveValue(12);
    expect(screen.getByLabelText('Cantidad de SW-16')).toHaveValue(4);
  });

  it('shows the readable message of a rejected prefill and fills nothing', async () => {
    const user = userEvent.setup();
    sellInAPI.prefill.mockRejectedValue({
      response: { status: 422, data: { error: { code: 'VALIDATION_ERROR', message: 'Las operaciones son de distintos proveedores.' } } },
    });
    renderPanel();
    await agregarOperacion(user, 15);
    expect(await screen.findByRole('alert')).toHaveTextContent('Las operaciones son de distintos proveedores.');
    expect(screen.queryByLabelText(/Cantidad de/)).not.toBeInTheDocument();
  });
});
