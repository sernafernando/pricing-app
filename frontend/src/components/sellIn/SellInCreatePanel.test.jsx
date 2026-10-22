import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInAPI } from '../../services/sellInAPI';
import { COMPRA_ARS, operacionesFake, PREFILL, PREVIEW, PRODUCTOS } from './sellInFixtures';
import SellInCreatePanel from './SellInCreatePanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInAPI: { preview: vi.fn(), crear: vi.fn(), proveedores: vi.fn(), prefill: vi.fn(), operaciones: vi.fn(), operacionProductos: vi.fn() },
}));

// Operation 20 belongs to another supplier, Mercusys (9), with no receipt yet.
const PREFILL_MERCUSYS = {
  pedido_compra_ids: [20],
  proveedor_id: 9,
  proveedor_nombre: 'Mercusys',
  moneda: 'ARS',
  fecha_ingreso: null,
  items: [{ item_id: 4513, codigo: 'SW-16', descripcion: 'Switch 16 bocas', cantidad: 7 }],
};
const MEZCLA = {
  response: { status: 422, data: { error: { code: 'VALIDATION_ERROR', message: 'Las operaciones son de distintos proveedores.' } } },
};

/** A promise and the function that settles it, to answer requests in a chosen order. */
const diferido = () => {
  let resolver;
  const promise = new Promise((resolve) => (resolver = resolve));
  return { promise, resolver };
};

const PROVEEDORES = { proveedores: [{ id: 7, nombre: 'TP-Link', cuit: '30-1' }], total: 1, page: 1, page_size: 10 };

beforeEach(() => {
  vi.clearAllMocks();
  productosAPI.listar.mockResolvedValue({ data: { productos: PRODUCTOS, total: 2, page: 1, page_size: 10 } });
  sellInAPI.proveedores.mockResolvedValue({ data: PROVEEDORES });
  sellInAPI.preview.mockResolvedValue({ data: PREVIEW });
  sellInAPI.crear.mockResolvedValue({ data: COMPRA_ARS });
  sellInAPI.prefill.mockResolvedValue({ data: PREFILL });
  sellInAPI.operaciones.mockImplementation(operacionesFake);
});

const renderPanel = (props = {}) => {
  const onCreated = vi.fn();
  const onClose = vi.fn();
  render(<SellInCreatePanel onCreated={onCreated} onClose={onClose} {...props} />);
  return { onCreated, onClose };
};

/** Links Compras operation `numero` to the sell in through the picker's typed-number fast path. */
async function agregarOperacion(user, numero) {
  await user.type(screen.getByLabelText('Pedido de compra (N°)'), `${numero}{Enter}`);
  await screen.findByText(`N° ${numero}`, { selector: 'li > span' });
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

  it('removing every operation clears what their prefill filled', async () => {
    const user = userEvent.setup();
    renderPanel();
    await agregarOperacion(user, 15);
    expect(await screen.findByText('TP-Link')).toBeInTheDocument();
    expect(screen.getByLabelText('Fecha de ingreso')).toHaveValue('2026-10-05');

    await user.click(screen.getByRole('button', { name: 'Quitar operación 15' }));
    expect(screen.queryByText('TP-Link')).not.toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Proveedor' })).toBeInTheDocument();
    expect(screen.getByLabelText('Fecha de ingreso')).toHaveValue('');
    expect(screen.queryByLabelText(/Cantidad de/)).not.toBeInTheDocument();
  });

  it("switching to another supplier's operation replaces the prefilled supplier, but not a date the user typed", async () => {
    const user = userEvent.setup();
    sellInAPI.prefill.mockImplementation((ids) => {
      if (ids.length === 1 && ids[0] === 15) return Promise.resolve({ data: PREFILL });
      if (ids.length === 1 && ids[0] === 20) return Promise.resolve({ data: PREFILL_MERCUSYS });
      return Promise.reject(MEZCLA);
    });
    renderPanel();
    await agregarOperacion(user, 15);
    expect(await screen.findByText('TP-Link')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Fecha de ingreso'));
    await user.type(screen.getByLabelText('Fecha de ingreso'), '2026-10-09');

    // The picker offers only TP-Link's operations while 15 is linked: another supplier's comes after removing it.
    await user.click(screen.getByRole('button', { name: 'Quitar operación 15' }));
    await agregarOperacion(user, 20);

    expect(await screen.findByText('Mercusys')).toBeInTheDocument();
    expect(screen.queryByText('TP-Link')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Fecha de ingreso')).toHaveValue('2026-10-09');
    // The untouched prefilled lines follow the operations.
    expect(screen.queryByLabelText('Cantidad de SW-8')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Cantidad de SW-16')).toHaveValue(7);
  });

  it('a supplier the user picked survives a prefill', async () => {
    const user = userEvent.setup();
    sellInAPI.prefill.mockResolvedValue({ data: PREFILL_MERCUSYS });
    renderPanel();
    const buscadorProveedor = screen.getByRole('group', { name: 'Proveedor' });
    await user.type(within(buscadorProveedor).getByRole('searchbox'), 'tp');
    await user.click(await within(buscadorProveedor).findByRole('button', { name: /TP-Link/ }));

    await agregarOperacion(user, 20);
    expect(await screen.findByLabelText('Cantidad de SW-16')).toHaveValue(7);
    expect(screen.getByText('TP-Link')).toBeInTheDocument();
    expect(screen.queryByText('Mercusys')).not.toBeInTheDocument();
  });

  it('an older prefill that answers after a newer one is dropped', async () => {
    const user = userEvent.setup();
    const viejo = diferido();
    const nuevo = diferido();
    sellInAPI.prefill.mockReturnValueOnce(viejo.promise).mockReturnValueOnce(nuevo.promise);
    renderPanel();
    await agregarOperacion(user, 15);
    await agregarOperacion(user, 16);

    // Only the order matters: the newer answer just has to differ from the older one.
    nuevo.resolver({ data: PREFILL_MERCUSYS });
    expect(await screen.findByText('Mercusys')).toBeInTheDocument();
    viejo.resolver({ data: PREFILL });
    await waitFor(() => expect(screen.getByLabelText('Cantidad de SW-16')).toHaveValue(7));
    expect(screen.queryByText('TP-Link')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Fecha de ingreso')).toHaveValue('');
    expect(screen.queryByLabelText('Cantidad de SW-8')).not.toBeInTheDocument();
  });

  it('removing the last operation drops the pending confirmation and the currency suggestion', async () => {
    const user = userEvent.setup();
    renderPanel();
    await fillCompra(user);
    await agregarOperacion(user, 15);
    expect(await screen.findByText(/Ya hay productos cargados/)).toBeInTheDocument();
    expect(screen.getByText('Las operaciones están en USD.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Quitar operación 15' }));
    expect(screen.queryByText(/Ya hay productos cargados/)).not.toBeInTheDocument();
    expect(screen.queryByText('Las operaciones están en USD.')).not.toBeInTheDocument();
    // The lines were the user's: they stay.
    expect(screen.getByLabelText('Cantidad de SW-8')).toHaveValue(10);
  });

  it('Enter on a typed operation number still adds it', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText('Pedido de compra (N°)'), '15{Enter}');
    expect(await screen.findByText('N° 15', { selector: 'li > span' })).toBeInTheDocument();
    expect(screen.getByLabelText('Pedido de compra (N°)')).toHaveValue('');
    await waitFor(() => expect(sellInAPI.prefill).toHaveBeenCalledWith([15]));
  });

  it('picking an operation from the search adds its chip and fills the panel from it', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText('Pedido de compra (N°)'), 'tp-link');
    await user.click(await screen.findByRole('option', { name: /N° 16/ }));

    expect(screen.getByText('N° 16', { selector: 'li > span' })).toBeInTheDocument();
    await waitFor(() => expect(sellInAPI.prefill).toHaveBeenCalledWith([16]));
    expect(await screen.findByText('TP-Link')).toBeInTheDocument();
    expect(screen.getByLabelText('Fecha de ingreso')).toHaveValue('2026-10-05');
    expect(screen.getByLabelText('Cantidad de SW-8')).toHaveValue(12);
  });

  it('after the first operation, offers only those of its supplier and currency that are not linked yet', async () => {
    const user = userEvent.setup();
    renderPanel();
    await agregarOperacion(user, 15);
    expect(screen.getByText('Solo se ofrecen operaciones de TP-Link en USD.')).toBeInTheDocument();

    await user.click(screen.getByLabelText('Pedido de compra (N°)'));
    const opciones = await within(await screen.findByRole('listbox')).findAllByRole('option');
    expect(opciones.map((o) => o.textContent)).toEqual([expect.stringContaining('N° 16')]);
    expect(sellInAPI.operaciones).toHaveBeenLastCalledWith({ q: '', excluir: [15], proveedor_id: 7, moneda: 'USD' });

    // Removing it lifts the restriction.
    await user.click(screen.getByRole('button', { name: 'Quitar operación 15' }));
    expect(screen.queryByText('Solo se ofrecen operaciones de TP-Link en USD.')).not.toBeInTheDocument();
  });

  it('the keyboard picks an operation: arrows, then Enter', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.type(screen.getByLabelText('Pedido de compra (N°)'), 'p-');
    await screen.findByRole('listbox');
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');

    expect(screen.getByText('N° 16', { selector: 'li > span' })).toBeInTheDocument();
    await waitFor(() => expect(sellInAPI.prefill).toHaveBeenCalledWith([16]));
  });

  it('links at most 50 operations, as the backend allows', async () => {
    const user = userEvent.setup();
    renderPanel();
    // 101..150: generated TP-Link USD operations, so the supplier and currency rule never gets in the way.
    for (let n = 101; n <= 150; n += 1) await agregarOperacion(user, n);
    expect(screen.getAllByRole('button', { name: /Quitar operación/ })).toHaveLength(50);

    expect(screen.getByLabelText('Pedido de compra (N°)')).toBeDisabled();
    expect(sellInAPI.prefill).toHaveBeenCalledTimes(50);
  });

  describe('as a percentage of what was invoiced', () => {
    // 4512 was invoiced USD 10.101,00 over the operations; 4513 has no invoiced line yet.
    const PREFILL_FACTURADO = {
      ...PREFILL,
      items: [
        { ...PREFILL.items[0], facturado: '10101.00', facturado_moneda: 'USD' },
        { ...PREFILL.items[1], facturado: null, facturado_moneda: null },
      ],
    };
    const PREVIEW_PORCENTAJE = {
      ...PREVIEW,
      moneda: 'USD',
      tipo: 'porcentaje',
      porcentaje: '2.5000',
      formula: 'manual',
      lineas: PREVIEW.lineas.map((l) => ({ ...l, base_facturada: '10101.00' })),
    };

    beforeEach(() => {
      sellInAPI.prefill.mockResolvedValue({ data: PREFILL_FACTURADO });
      sellInAPI.preview.mockResolvedValue({ data: PREVIEW_PORCENTAJE });
    });

    async function porcentaje(user, valor = '2.5') {
      await user.click(screen.getByRole('button', { name: '% de lo facturado' }));
      await user.type(screen.getByLabelText('Porcentaje'), valor);
      await user.type(screen.getByLabelText('Tipo de cambio'), '1400');
    }

    it('asks for the percentage instead of a total, shows each product invoiced and saves without a formula', async () => {
      const user = userEvent.setup();
      const { onCreated } = renderPanel();
      await agregarOperacion(user, 15);
      await screen.findByLabelText('Cantidad de SW-8');
      await porcentaje(user);

      expect(screen.queryByLabelText('Monto total')).not.toBeInTheDocument();
      expect(screen.queryByRole('group', { name: 'Reparto' })).not.toBeInTheDocument();
      expect(screen.getByText('Facturado USD 10.101,00')).toBeInTheDocument();
      expect(screen.getByText('Sin facturado')).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
      const enviado = {
        moneda: 'USD',
        tipo: 'porcentaje',
        porcentaje: '2.5',
        tipo_cambio: '1400',
        lineas: [
          { item_id: 4512, cantidad: 12 },
          { item_id: 4513, cantidad: 4 },
        ],
        pedido_compra_ids: [15],
      };
      expect(sellInAPI.preview).toHaveBeenCalledWith(enviado);
      const previa = await screen.findByRole('table', { name: 'Vista previa por ítem' });
      expect(within(previa).getByRole('columnheader', { name: 'Base facturada' })).toBeInTheDocument();
      expect(within(previa).getAllByText('USD 10.101,00').length).toBeGreaterThan(0);

      await user.click(screen.getByRole('button', { name: 'Guardar sell in' }));
      await waitFor(() => expect(onCreated).toHaveBeenCalledWith(COMPRA_ARS));
      const creado = sellInAPI.crear.mock.calls[0][0];
      expect(creado).toMatchObject({ ...enviado, pedido_compra_ids: [15] });
      expect(creado).not.toHaveProperty('monto_total');
      expect(creado).not.toHaveProperty('formula');
    });

    it('needs an operation to take the invoiced base from', async () => {
      const user = userEvent.setup();
      renderPanel();
      await fillCompra(user);
      await porcentaje(user);
      await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));

      expect(await screen.findByRole('alert')).toHaveTextContent(
        'Elegí al menos una operación de compra: el porcentaje se aplica sobre lo facturado.',
      );
      expect(sellInAPI.preview).not.toHaveBeenCalled();
    });

    it.each(['0', '150'])('refuses a percentage of %s before asking the server', async (valor) => {
      const user = userEvent.setup();
      renderPanel();
      await agregarOperacion(user, 15);
      await screen.findByLabelText('Cantidad de SW-8');
      await porcentaje(user, valor);
      await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));

      expect(await screen.findByRole('alert')).toHaveTextContent('El porcentaje debe ser mayor que 0 y hasta 100.');
      expect(sellInAPI.preview).not.toHaveBeenCalled();
    });

    it('drops the preview when the operations change, since the base comes from them', async () => {
      const user = userEvent.setup();
      renderPanel();
      await agregarOperacion(user, 15);
      await screen.findByLabelText('Cantidad de SW-8');
      await porcentaje(user);
      await user.click(screen.getByRole('button', { name: 'Calcular vista previa' }));
      await screen.findByRole('table', { name: 'Vista previa por ítem' });

      await agregarOperacion(user, 16);

      expect(screen.queryByRole('table', { name: 'Vista previa por ítem' })).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Guardar sell in' })).toBeDisabled();
    });
  });
});
