import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInAPI, sellInBonosAPI } from '../../services/sellInAPI';
import { ALCANCE, ALCANCE_VACIO, BONO, BONO_ANULADO, operacionesFake, PRODUCTOS } from './sellInFixtures';
import SellInBonoPanel from './SellInBonoPanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInBonosAPI: { detalle: vi.fn(), alcance: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
  sellInAPI: { operaciones: vi.fn(), operacionProductos: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  productosAPI: { categorias: vi.fn(), listar: vi.fn() },
}));

const MARCAS = ['MERCUSYS', 'TP-LINK'];
const apiError = (status, message) => Object.assign(new Error(message), { response: { status, data: { error: { message } } } });

beforeEach(() => {
  vi.clearAllMocks();
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE });
  sellInBonosAPI.crear.mockResolvedValue({ data: { ...BONO, id: 9 } });
  sellInBonosAPI.editar.mockResolvedValue({ data: { ...BONO, monto_unit: '4.00' } });
  sellInBonosAPI.anular.mockResolvedValue({ data: { ...BONO, estado: 'anulada' } });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Routers', 'Switches'] } });
  productosAPI.listar.mockResolvedValue({ data: { productos: PRODUCTOS, total: 2, page: 1, page_size: 10 } });
  sellInAPI.operaciones.mockImplementation(operacionesFake);
});

const renderPanel = (props = {}) => {
  const handlers = { onSaved: vi.fn(), onClose: vi.fn(), onVerCompra: vi.fn() };
  render(<SellInBonoPanel bonoId={3} marcas={MARCAS} puedeGestionar {...handlers} {...props} />);
  return handlers;
};

const llenar = async (user) => {
  await user.selectOptions(screen.getByLabelText('Marca'), 'TP-LINK');
  await user.type(screen.getByLabelText('Monto por unidad'), '3');
  await user.type(screen.getByLabelText('Factura desde'), '2026-09-01');
  await user.type(screen.getByLabelText('Factura hasta'), '2026-11-30');
  await user.type(screen.getByLabelText('Descripción'), 'Bono TP-Link');
};

describe('SellInBonoPanel — new bonus', () => {
  it('does not let "Cancelar" or "Cerrar" close the panel while the bonus is being saved', async () => {
    const user = userEvent.setup();
    let resolver;
    sellInBonosAPI.crear.mockReturnValueOnce(new Promise((resolve) => (resolver = resolve)));
    const { onSaved, onClose } = renderPanel({ bonoId: null });
    await llenar(user);

    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));

    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cerrar' })).toBeDisabled();
    resolver({ data: { ...BONO, id: 9 } });
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(onClose).not.toHaveBeenCalled();
  });

  it('creates a bonus in USD by default with the brand, amount per unit and invoice range', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderPanel({ bonoId: null });
    expect(screen.getByRole('heading', { name: 'Nuevo sell in · Bono de marca' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'USD' })).toHaveAttribute('aria-pressed', 'true');
    await llenar(user);
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));
    expect(sellInBonosAPI.crear).toHaveBeenCalledWith({
      alcance: 'marca',
      marca: 'TP-LINK',
      tipo: 'por_unidad',
      monto_unit: '3',
      moneda: 'USD',
      fecha_desde: '2026-09-01',
      fecha_hasta: '2026-11-30',
      descripcion: 'Bono TP-Link',
      tope_unidades: null,
      tope_monto: null,
      acumulable: true,
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ ...BONO, id: 9 }));
    expect(sellInBonosAPI.detalle).not.toHaveBeenCalled();
  });

  it('offers only the brands of the brand filter', () => {
    renderPanel({ bonoId: null });
    const opciones = within(screen.getByLabelText('Marca')).getAllByRole('option').map((o) => o.value);
    expect(opciones).toEqual(['', 'MERCUSYS', 'TP-LINK']);
  });

  it('shows the backend message inline when it refuses the bonus', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.crear.mockRejectedValue(apiError(422, 'La fecha desde no puede ser posterior a la fecha hasta'));
    const { onSaved } = renderPanel({ bonoId: null });
    await llenar(user);
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La fecha desde no puede ser posterior a la fecha hasta');
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('asks for the missing data before calling the backend', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Faltan datos');
    expect(sellInBonosAPI.crear).not.toHaveBeenCalled();
  });
});

const fechas = async (user) => {
  await user.type(screen.getByLabelText('Factura desde'), '2026-09-01');
  await user.type(screen.getByLabelText('Factura hasta'), '2026-11-30');
};

const BASE_BODY = { moneda: 'USD', fecha_desde: '2026-09-01', fecha_hasta: '2026-11-30', descripcion: null, tope_unidades: null, tope_monto: null, acumulable: true };

describe('SellInBonoPanel — scope and kind (T3e)', () => {
  it('creates a category bonus from the catalog categories', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.click(screen.getByRole('button', { name: 'Categoría' }));
    await user.selectOptions(await screen.findByLabelText('Categoría del bono'), 'Switches');
    await user.type(screen.getByLabelText('Monto por unidad'), '3');
    await fechas(user);

    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));

    expect(sellInBonosAPI.crear).toHaveBeenCalledWith({ alcance: 'categoria', categoria: 'Switches', tipo: 'por_unidad', monto_unit: '3', ...BASE_BODY });
    expect(screen.queryByLabelText('Marca')).not.toBeInTheDocument();
  });

  it('creates a models bonus from the product search, each model once', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.click(screen.getByRole('button', { name: 'Modelos' }));
    const buscador = screen.getByRole('group', { name: 'Agregar modelo' });
    for (const codigo of [/SW-16/, /SW-8/, /SW-16/]) {
      await user.type(within(buscador).getByRole('searchbox'), 'switch');
      await user.click(await within(buscador).findByRole('button', { name: codigo }));
    }
    const chips = screen.getByRole('list', { name: 'Modelos del bono' });
    expect(within(chips).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['SW-16 · Switch 16 bocas', 'SW-8 · Switch 8 bocas']);
    await user.click(screen.getByRole('button', { name: 'Quitar modelo SW-16 · Switch 16 bocas' }));
    await user.type(screen.getByLabelText('Monto por unidad'), '3');
    await fechas(user);

    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));

    expect(sellInBonosAPI.crear).toHaveBeenCalledWith({ alcance: 'modelos', modelos: [{ item_id: 4512 }], tipo: 'por_unidad', monto_unit: '3', ...BASE_BODY });
  });

  it('creates an invoice bonus on one Compras operation', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.click(screen.getByRole('button', { name: 'Factura' }));
    await user.type(screen.getByLabelText('Pedido de compra (N°)'), 'P-00020{Enter}');
    expect(await screen.findByText('N° P-00020')).toBeInTheDocument();
    expect(screen.queryByLabelText('Pedido de compra (N°)')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Monto por unidad'), '3');
    await fechas(user);

    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));

    expect(sellInBonosAPI.crear).toHaveBeenCalledWith({ alcance: 'factura', pedido_id: 20, tipo: 'por_unidad', monto_unit: '3', ...BASE_BODY });
  });

  it('creates a percentage bonus without an amount per unit', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.selectOptions(screen.getByLabelText('Marca'), 'TP-LINK');
    await user.click(screen.getByRole('button', { name: '% de lo facturado' }));
    expect(screen.queryByLabelText('Monto por unidad')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Porcentaje'), '2.5');
    await fechas(user);

    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));

    expect(sellInBonosAPI.crear).toHaveBeenCalledWith({ alcance: 'marca', marca: 'TP-LINK', tipo: 'porcentaje', porcentaje: '2.5', ...BASE_BODY });
  });

  it('names what is missing for the chosen scope and kind', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.click(screen.getByRole('button', { name: 'Modelos' }));
    await user.click(screen.getByRole('button', { name: '% de lo facturado' }));
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Faltan datos: al menos un modelo, porcentaje y fechas de factura.');
    expect(sellInBonosAPI.crear).not.toHaveBeenCalled();
  });

  it('shows an existing models bonus with its models, its percentage and what it generated in each currency', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({
      data: {
        ...BONO,
        alcance: 'modelos',
        marca: null,
        modelos: [{ item_id: 4512, codigo: 'SW-8', descripcion: 'Switch 8 bocas' }, { item_id: 999, codigo: null, descripcion: null }],
        tipo: 'porcentaje',
        monto_unit: null,
        porcentaje: '2.5000',
        montos_generados: [{ moneda: 'ARS', monto: '1450.00' }, { moneda: 'USD', monto: '3120.00' }],
      },
    });
    renderPanel();

    const chips = await screen.findByRole('list', { name: 'Modelos del bono' });
    expect(within(chips).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['SW-8 · Switch 8 bocas', 'Item 999']);
    expect(screen.getByLabelText('Porcentaje')).toHaveValue(2.5);
    expect(screen.getByText('18 compras · 1.040 u · USD 3.120,00 aplicados')).toBeInTheDocument();
    expect(screen.getByText('Además $ 1.450,00 en otra moneda (de antes de cambiarla).')).toBeInTheDocument();
  });
});

describe('SellInBonoPanel — existing bonus', () => {
  it('loads the bonus and what it reaches, with its groups and their counts', async () => {
    renderPanel();
    expect(await screen.findByRole('heading', { name: 'Bono TP-Link USD 3/u' })).toBeInTheDocument();
    expect(sellInBonosAPI.detalle).toHaveBeenCalledWith(3);
    expect(sellInBonosAPI.alcance).toHaveBeenCalledWith(3);
    expect(screen.getByText('Bono de marca')).toBeInTheDocument();
    expect(screen.getByText('18 compras · 1.040 u · USD 3.120,00 aplicados')).toBeInTheDocument();

    const alcanzadas = await screen.findByRole('region', { name: 'Compras alcanzadas (18)' });
    expect(within(alcanzadas).getByText('Mostrando 1 de 18')).toBeInTheDocument();
    const fila = within(alcanzadas).getByText('OC-2026-01722').closest('tr');
    expect(within(fila).getByText('A-0003-00045871')).toBeInTheDocument();
    expect(within(fila).getByText('80')).toBeInTheDocument();
    expect(within(fila).getByText('USD 240,00')).toBeInTheDocument();

    const pendientes = screen.getByRole('region', { name: 'Pendientes de factura (1)' });
    expect(within(pendientes).getByText(/OC-2026-01890/)).toHaveTextContent('OC-2026-01890 · Global Tech · Nro. A-0007-00012233 · 120 u');

    const fuera = screen.getByRole('region', { name: 'Fuera de rango (1)' });
    expect(within(fuera).getByText(/OC-2026-01650/)).toHaveTextContent('OC-2026-01650 · TP-Link Argentina · factura 28/08/2026 · 15 u');
  });

  it('shows the in-range invoices the bonus did not apply, with why', async () => {
    renderPanel();
    const grupo = await screen.findByRole('region', { name: 'Con factura, sin aplicar (2)' });
    const items = within(grupo).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('OC-2026-00278 · TP-Link Argentina · factura 22/10/2026 · 21 u');
    expect(items[0]).toHaveTextContent('Error al aplicar: value too long for type character varying(20) (5 intentos)');
    expect(items[1]).toHaveTextContent('OC-2026-01901 · Global Tech · factura 15/10/2026 · 0 u');
    expect(items[1]).toHaveTextContent('Sin líneas de la marca en la factura');
    expect(items[1]).not.toHaveTextContent('intentos');
  });

  it('a response without the not-applied group (older backend) still renders', async () => {
    const { sin_aplicar: _omitido, ...viejo } = ALCANCE;
    sellInBonosAPI.alcance.mockResolvedValue({ data: viejo });
    renderPanel();
    expect(await screen.findByRole('region', { name: 'Con factura, sin aplicar (0)' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Compras alcanzadas (18)' })).toBeInTheDocument();
  });

  it('says so when a group is empty', async () => {
    sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE_VACIO });
    renderPanel();
    const alcanzadas = await screen.findByRole('region', { name: 'Compras alcanzadas (0)' });
    expect(within(alcanzadas).getByText('Todavía no alcanzó ninguna compra.')).toBeInTheDocument();
    const sinAplicar = screen.getByRole('region', { name: 'Con factura, sin aplicar (0)' });
    expect(within(sinAplicar).getByText('Todas las operaciones facturadas dentro del rango están aplicadas.')).toBeInTheDocument();
  });

  it('opens a reached purchase', async () => {
    const user = userEvent.setup();
    const { onVerCompra } = renderPanel();
    await user.click(await screen.findByRole('button', { name: 'OC-2026-01722' }));
    expect(onVerCompra).toHaveBeenCalledWith(41);
  });

  it('without onVerCompra a reached purchase is plain text, not a dead button', async () => {
    renderPanel({ onVerCompra: undefined });
    const alcanzadas = await screen.findByRole('region', { name: 'Compras alcanzadas (18)' });
    expect(within(alcanzadas).getByText('OC-2026-01722')).toBeInTheDocument();
    expect(within(alcanzadas).queryByRole('button', { name: 'OC-2026-01722' })).not.toBeInTheDocument();
  });

  it('saves an edit as a full replace and reloads what it reaches', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderPanel();
    const monto = await screen.findByLabelText('Monto por unidad');
    await user.clear(monto);
    await user.type(monto, '4');
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    expect(sellInBonosAPI.editar).toHaveBeenCalledWith(3, {
      alcance: 'marca',
      marca: 'TP-LINK',
      tipo: 'por_unidad',
      monto_unit: '4',
      moneda: 'USD',
      fecha_desde: '2026-09-01',
      fecha_hasta: '2026-11-30',
      descripcion: 'Bono TP-Link USD 3/u',
      tope_unidades: null,
      tope_monto: null,
      acumulable: true,
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ ...BONO, monto_unit: '4.00' }));
    expect(sellInBonosAPI.alcance).toHaveBeenCalledTimes(2);
  });

  it('shows the backend message inline when an edit is refused', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.editar.mockRejectedValue(apiError(409, 'El bono 3 está anulado'));
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Guardar cambios' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('El bono 3 está anulado');
  });

  it('voids after an inline confirmation with the reason, and shows the 409 if it was already voided', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular bono' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    await user.type(screen.getByLabelText('Motivo (opcional)'), 'Acuerdo caído');
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));
    expect(sellInBonosAPI.anular).toHaveBeenCalledWith(3, 'Acuerdo caído');
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith({ ...BONO, estado: 'anulada' }));
    expect(await screen.findByText('Anulado')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Anular bono' })).not.toBeInTheDocument();
  });

  it('shows the backend message when voiding is refused', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.anular.mockRejectedValue(apiError(409, 'El bono 3 ya está anulado'));
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular bono' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('El bono 3 ya está anulado');
  });

  it('is read-only without sell_in.gestionar', async () => {
    renderPanel({ puedeGestionar: false });
    expect(await screen.findByLabelText('Monto por unidad')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Guardar cambios' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Anular bono' })).not.toBeInTheDocument();
  });

  it('a voided bonus is read-only', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: BONO_ANULADO });
    renderPanel({ bonoId: 4 });
    expect(await screen.findByText('Anulado')).toBeInTheDocument();
    expect(screen.getByLabelText('Monto por unidad')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Guardar cambios' })).not.toBeInTheDocument();
  });

  it('keeps a brand that is not in the filter list', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: { ...BONO, marca: 'VIEJA' } });
    renderPanel();
    await waitFor(() => expect(screen.getByLabelText('Marca')).toHaveValue('VIEJA'));
  });

  it('shows a load error inline', async () => {
    sellInBonosAPI.detalle.mockRejectedValue(apiError(404, 'El bono 3 no existe'));
    renderPanel();
    expect(await screen.findByRole('alert')).toHaveTextContent('El bono 3 no existe');
  });

  it('shows the creation date in the local (Argentina) day, not the UTC one', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: { ...BONO, created_at: '2026-08-28T02:00:00+00:00' } });
    renderPanel();
    expect(await screen.findByText('Creado el 27/8/2026')).toBeInTheDocument();
  });

  it('cancelling the void confirmation clears the reason', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Anular bono' }));
    await user.type(screen.getByLabelText('Motivo (opcional)'), 'Acuerdo caído');
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    await user.click(screen.getByRole('button', { name: 'Anular bono' }));
    expect(screen.getByLabelText('Motivo (opcional)')).toHaveValue('');
  });

  it('a 409 on save (voided by someone else) reloads the bonus and shows it read-only', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.editar.mockRejectedValue(apiError(409, 'El bono 3 está anulado'));
    sellInBonosAPI.detalle.mockResolvedValueOnce({ data: BONO }).mockResolvedValueOnce({ data: { ...BONO, estado: 'anulada' } });
    renderPanel();
    await user.click(await screen.findByRole('button', { name: 'Guardar cambios' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('El bono 3 está anulado');
    expect(await screen.findByText('Anulado')).toBeInTheDocument();
    expect(sellInBonosAPI.detalle).toHaveBeenCalledTimes(2);
    expect(screen.getByLabelText('Monto por unidad')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Guardar cambios' })).not.toBeInTheDocument();
  });
});
