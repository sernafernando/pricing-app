/**
 * A cost bonus by total amount (tactical monto total S4): the ARS total split across the bonus's products by a
 * criterion, with no caps; the panel shows its fixed shares (iguales / costo) or says it follows units sold.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInBonosAPI } from '../../services/sellInAPI';
import { ALCANCE_VACIO, BONO_MONTO_TOTAL } from './sellInFixtures';
import SellInBonoPanel from './SellInBonoPanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInBonosAPI: { detalle: vi.fn(), alcance: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
  sellInAPI: { operaciones: vi.fn(), operacionProductos: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  productosAPI: { categorias: vi.fn(), listar: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO_MONTO_TOTAL });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE_VACIO });
  sellInBonosAPI.crear.mockResolvedValue({ data: BONO_MONTO_TOTAL });
  sellInBonosAPI.editar.mockResolvedValue({ data: BONO_MONTO_TOTAL });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Notebooks'] } });
  productosAPI.listar.mockResolvedValue({ data: { productos: [], total: 0, page: 1, page_size: 10 } });
});

const renderPanel = (props = {}) => {
  const handlers = { onSaved: vi.fn(), onClose: vi.fn(), onVerCompra: vi.fn() };
  render(<SellInBonoPanel bonoId={null} marcas={['HP']} puedeGestionar {...handlers} {...props} />);
  return handlers;
};

const forma = () => screen.getByRole('group', { name: 'Forma del monto' });

async function nuevoTotal(user) {
  renderPanel();
  await user.click(within(screen.getByRole('group', { name: 'Base del bono' })).getByRole('button', { name: 'Sobre el costo de la venta' }));
  await user.click(within(forma()).getByRole('button', { name: 'Monto total' }));
  await user.selectOptions(screen.getByLabelText('Marca'), 'HP');
  await user.type(screen.getByLabelText('Venta desde'), '2026-11-01');
  await user.type(screen.getByLabelText('Venta hasta'), '2026-11-30');
}

describe('SellInBonoForm — a cost bonus by total amount (S4)', () => {
  it('offers Monto total on the cost base only, with the split selector and no caps', async () => {
    const user = userEvent.setup();
    renderPanel();
    expect(within(forma()).queryByRole('button', { name: 'Monto total' })).not.toBeInTheDocument();
    await user.click(within(screen.getByRole('group', { name: 'Base del bono' })).getByRole('button', { name: 'Sobre el costo de la venta' }));
    expect(within(forma()).getAllByRole('button').map((b) => b.textContent)).toEqual(['% del costo de la venta', 'Monto total']);
    await user.click(within(forma()).getByRole('button', { name: 'Monto total' }));

    expect(screen.getByLabelText('Monto total (ARS)')).toBeInTheDocument();
    const criterio = screen.getByLabelText('Repartir el monto total');
    expect(within(criterio).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Elegí cómo repartir',
      'Partes iguales por modelo',
      'Según unidades vendidas',
      'Proporcional al costo',
    ]);
    expect(screen.queryByLabelText('Porcentaje')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Tope de unidades (opcional)')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Tope de monto en ARS (opcional)')).not.toBeInTheDocument();
    await user.selectOptions(criterio, 'unidades');
    expect(screen.getByText(/sigue las ventas y devoluciones/)).toBeInTheDocument();
  });

  it('creates it with the total and the criterion, in ARS, without caps', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderPanel();
    await user.click(within(screen.getByRole('group', { name: 'Base del bono' })).getByRole('button', { name: 'Sobre el costo de la venta' }));
    await user.click(within(forma()).getByRole('button', { name: 'Monto total' }));
    await user.selectOptions(screen.getByLabelText('Marca'), 'HP');
    await user.type(screen.getByLabelText('Monto total (ARS)'), '1200000');
    await user.selectOptions(screen.getByLabelText('Repartir el monto total'), 'iguales');
    await user.type(screen.getByLabelText('Venta desde'), '2026-11-01');
    await user.type(screen.getByLabelText('Venta hasta'), '2026-11-30');
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));

    expect(sellInBonosAPI.crear).toHaveBeenCalledWith({
      alcance: 'marca',
      marca: 'HP',
      tipo: 'monto_total',
      monto_total: '1200000',
      reparto_criterio: 'iguales',
      moneda: 'ARS',
      fecha_desde: '2026-11-01',
      fecha_hasta: '2026-11-30',
      descripcion: null,
      tope_unidades: null,
      tope_monto: null,
      acumulable: true,
      base: 'costo_venta',
      incluye_iva: false,
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(BONO_MONTO_TOTAL));
  });

  it('keeps the Incluye IVA box visible on a total, so a ticked one is never sent unseen', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(within(screen.getByRole('group', { name: 'Base del bono' })).getByRole('button', { name: 'Sobre el costo de la venta' }));
    await user.click(screen.getByRole('checkbox', { name: 'Incluye IVA' }));
    await user.click(within(forma()).getByRole('button', { name: 'Monto total' }));

    expect(screen.getByRole('checkbox', { name: 'Incluye IVA' })).toBeChecked();
    expect(screen.getByText(/el monto total cargado incluye IVA/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Marca'), 'HP');
    await user.type(screen.getByLabelText('Monto total (ARS)'), '1210000');
    await user.selectOptions(screen.getByLabelText('Repartir el monto total'), 'iguales');
    await user.type(screen.getByLabelText('Venta desde'), '2026-11-01');
    await user.type(screen.getByLabelText('Venta hasta'), '2026-11-30');
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));
    expect(sellInBonosAPI.crear).toHaveBeenCalledWith(expect.objectContaining({ tipo: 'monto_total', incluye_iva: true }));
  });

  it.each(['-500', '0'])('a total of %s goes to the backend and its message shows', async (monto) => {
    const user = userEvent.setup();
    const mensaje = 'El monto total debe ser mayor que cero: en sell in no se descuenta un monto negativo';
    sellInBonosAPI.crear.mockRejectedValue({ response: { status: 422, data: { detail: mensaje } } });
    await nuevoTotal(user);
    await user.type(screen.getByLabelText('Monto total (ARS)'), monto);
    await user.selectOptions(screen.getByLabelText('Repartir el monto total'), 'costo');
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));

    expect(sellInBonosAPI.crear).toHaveBeenCalledWith(expect.objectContaining({ tipo: 'monto_total', monto_total: monto }));
    expect(await screen.findByRole('alert')).toHaveTextContent(mensaje);
  });

  it('asks for the total and the criterion before sending', async () => {
    const user = userEvent.setup();
    await nuevoTotal(user);
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Faltan datos: marca, monto total, cómo repartirlo y fechas de venta.');
    expect(sellInBonosAPI.crear).not.toHaveBeenCalled();
  });

  it('a models bonus by total sends its models without values of their own', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: 21 });
    await screen.findByLabelText('Monto total (ARS)');
    expect(screen.queryByLabelText(/^Monto de NB-250RG10/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    expect(sellInBonosAPI.editar).toHaveBeenCalledWith(21, {
      alcance: 'modelos',
      modelos: [{ item_id: 103 }, { item_id: 104 }],
      tipo: 'monto_total',
      monto_total: '1200000',
      reparto_criterio: 'costo',
      moneda: 'ARS',
      fecha_desde: '2026-09-01',
      fecha_hasta: '2026-11-30',
      descripcion: 'Notebooks HP total noviembre',
      tope_unidades: null,
      tope_monto: null,
      acumulable: true,
      incluye_iva: false,
    });
  });
});

describe('SellInBonoPanel — the split of a bonus by total amount (S4)', () => {
  it('lists the stored shares of a split by cost, read only', async () => {
    renderPanel({ bonoId: 21, puedeGestionar: false });
    const tabla = await screen.findByRole('table', { name: 'Reparto del monto total' });
    const filas = within(tabla).getAllByRole('row').slice(1).map((fila) => within(fila).getAllByRole('cell').map((c) => c.textContent));
    expect(filas).toEqual([
      ['NB-250RG10', 'Notebook HP 250RG10', '$ 480.000,00'],
      ['NB-255RG10', 'Notebook HP 255r G10', '$ 720.000,00'],
    ]);
    expect(screen.getByText('Proporcional al costo')).toBeInTheDocument();
  });

  it('says a split by units follows the units sold, with no table', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: { ...BONO_MONTO_TOTAL, reparto_criterio: 'unidades', repartos: [] } });
    renderPanel({ bonoId: 21, puedeGestionar: false });
    expect(await screen.findByText(/El total se reparte según las unidades vendidas en las fechas del bono/)).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Reparto del monto total' })).not.toBeInTheDocument();
  });
});
