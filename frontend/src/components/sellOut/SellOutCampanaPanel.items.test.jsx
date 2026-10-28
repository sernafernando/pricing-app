/**
 * SellOutCampanaPanel: per-product amounts in a `por_unidad` campaign (T22c, S25): legacy grouped offsets,
 * each product with its own amount under the campaign's one cap.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CAMPANA_MIGRADA, CONSUMOS_USD } from './sellOutFixtures';
import SellOutCampanaPanel from './SellOutCampanaPanel';
import SellOutCampanasTable from './SellOutCampanasTable';

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn(), definirTipoCambio: vi.fn(), consumos: vi.fn() },
}));
vi.mock('../../services/api', () => ({ productosAPI: { listar: vi.fn() } }));

const GRUPOS = [
  { id: 1, nombre: 'TP-Link redes' },
  { id: 301, nombre: 'Offset #48: RB 8180' },
];
const PRODUCTOS = [
  { item_id: 4172, codigo: 'C13T00R120', descripcion: 'Epson EcoTank L8180', marca: 'EPSON' },
  { item_id: 4173, codigo: 'C11CJ21301', descripcion: 'Epson EcoTank L3250', marca: 'EPSON' },
];
const CON_ITEMS = { ...CAMPANA_MIGRADA, items: [{ item_id: 4172, monto_unit: '30.00' }] };

const abrirNueva = () =>
  render(<SellOutCampanaPanel campanaId={null} grupos={GRUPOS} puedeGestionar onSaved={() => {}} onClose={() => {}} />);
const abrirEdicion = () =>
  render(<SellOutCampanaPanel campanaId={55} grupos={GRUPOS} puedeGestionar onSaved={() => {}} onClose={() => {}} />);

async function completarNueva(user) {
  await user.type(screen.getByLabelText('Nombre'), 'Epson diciembre');
  await user.type(screen.getByLabelText('Monto por unidad'), '12');
  await user.type(screen.getByLabelText('Desde'), '2026-12-01');
  await user.type(screen.getByLabelText('Hasta'), '2026-12-31');
  await user.click(screen.getByRole('checkbox', { name: 'TP-Link redes' }));
}

async function agregar(user, texto, opcion) {
  const buscador = screen.getByRole('group', { name: 'Agregar producto' });
  await user.type(within(buscador).getByRole('searchbox'), texto);
  await user.click(await within(buscador).findByRole('button', { name: new RegExp(opcion) }));
}

beforeEach(() => {
  vi.clearAllMocks();
  sellOutAPI.consumos.mockResolvedValue({ data: CONSUMOS_USD });
  productosAPI.listar.mockResolvedValue({ data: { productos: PRODUCTOS, total: 2, page: 1, page_size: 10 } });
});

describe('SellOutCampanaPanel — per-product amounts (T22c)', () => {
  it('a new campaign: adds products with their amount, skips a repeated one, removes one, and sends items', async () => {
    const user = userEvent.setup();
    sellOutAPI.crear.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, id: 95 } });
    abrirNueva();
    await completarNueva(user);

    const seccion = screen.getByRole('region', { name: 'Montos por producto' });
    expect(within(seccion).getByText(/sin monto propio usan el monto por unidad/)).toBeInTheDocument();
    expect(within(seccion).getByText(/comparten el tope de la campaña/)).toBeInTheDocument();
    await agregar(user, 'L8180', 'C13T00R120 · Epson EcoTank L8180');
    await agregar(user, 'L8180', 'C13T00R120 · Epson EcoTank L8180');
    await agregar(user, 'L3250', 'C11CJ21301 · Epson EcoTank L3250');
    expect(within(seccion).getAllByRole('spinbutton')).toHaveLength(2);
    expect(within(seccion).getByText('Epson EcoTank L8180')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Monto de C13T00R120'), '30');
    await user.type(screen.getByLabelText('Monto de C11CJ21301'), '8.5');
    await user.click(screen.getByRole('button', { name: 'Quitar C11CJ21301' }));
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));

    expect(sellOutAPI.crear).toHaveBeenCalledWith(expect.objectContaining({ items: [{ item_id: 4172, monto_unit: '30' }] }));
  });

  it('a campaign without per-product amounts sends items: [] and the rest of its body as before', async () => {
    const user = userEvent.setup();
    sellOutAPI.crear.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, id: 95 } });
    abrirNueva();
    await completarNueva(user);
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));

    expect(sellOutAPI.crear).toHaveBeenCalledWith({
      nombre: 'Epson diciembre',
      descripcion: null,
      fecha_desde: '2026-12-01',
      fecha_hasta: '2026-12-31',
      tipo: 'por_unidad',
      monto_unit: '12',
      porcentaje: null,
      base_porcentaje: 'costo',
      moneda: 'USD',
      tc_modo: 'al_cobro',
      tipo_cambio: null,
      tope_unidades: null,
      tope_monto: null,
      acumulable: true,
      monto_incluye_iva: false,
      grupo_ids: [1],
      items: [],
    });
  });

  it('a product without a positive amount is listed as missing and nothing is sent', async () => {
    const user = userEvent.setup();
    abrirNueva();
    await completarNueva(user);
    await agregar(user, 'L8180', 'C13T00R120 · Epson EcoTank L8180');
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));

    expect(screen.getByRole('alert')).toHaveTextContent('Faltan datos: monto de cada producto.');
    expect(sellOutAPI.crear).not.toHaveBeenCalled();
  });

  it('editing loads the stored amounts and sends the changed ones', async () => {
    const user = userEvent.setup();
    sellOutAPI.detalle.mockResolvedValue({ data: CON_ITEMS });
    sellOutAPI.editar.mockResolvedValue({ data: { ...CON_ITEMS, items: [{ item_id: 4172, monto_unit: '28.00' }] } });
    abrirEdicion();

    const monto = await screen.findByLabelText('Monto de #4172');
    expect(monto).toHaveValue(30);
    await user.clear(monto);
    await user.type(monto, '28');
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));

    expect(sellOutAPI.editar).toHaveBeenCalledWith(55, expect.objectContaining({ monto_unit: '36.00', items: [{ item_id: 4172, monto_unit: '28' }] }));
  });

  it('switching to Porcentaje hides the amounts, says they are dropped on save, and sends items: []', async () => {
    const user = userEvent.setup();
    sellOutAPI.detalle.mockResolvedValue({ data: CON_ITEMS });
    sellOutAPI.editar.mockResolvedValue({ data: CON_ITEMS });
    abrirEdicion();
    await screen.findByLabelText('Monto de #4172');

    await user.click(screen.getByRole('button', { name: 'Porcentaje' }));
    await user.type(screen.getByLabelText('Porcentaje'), '2');
    expect(screen.queryByRole('region', { name: 'Montos por producto' })).not.toBeInTheDocument();
    expect(screen.getByText('Una campaña por porcentaje no lleva montos por producto: al guardar se quita 1 monto por producto.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));

    expect(sellOutAPI.editar).toHaveBeenCalledWith(55, expect.objectContaining({ tipo: 'porcentaje', items: [] }));
  });

  it("shows the backend's 422 message about a product", async () => {
    const user = userEvent.setup();
    sellOutAPI.detalle.mockResolvedValue({ data: CON_ITEMS });
    sellOutAPI.editar.mockRejectedValue({ response: { status: 422, data: { detail: 'El producto 4172 no está en los grupos de la campaña' } } });
    abrirEdicion();
    await screen.findByLabelText('Monto de #4172');
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('El producto 4172 no está en los grupos de la campaña');
  });

  it('the read-only view lists the per-product amounts; one without them shows no such section', async () => {
    sellOutAPI.detalle.mockResolvedValue({ data: CON_ITEMS });
    const { unmount } = render(<SellOutCampanaPanel campanaId={55} onClose={() => {}} />);
    const seccion = await screen.findByRole('region', { name: 'Montos por producto' });
    expect(within(seccion).getByText('#4172').closest('tr')).toHaveTextContent('USD 30,00');
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument();
    unmount();

    sellOutAPI.detalle.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, items: [] } });
    render(<SellOutCampanaPanel campanaId={55} onClose={() => {}} />);
    await screen.findByText('Activa');
    expect(screen.queryByRole('region', { name: 'Montos por producto' })).not.toBeInTheDocument();
  });
});

describe('SellOutCampanasTable — per-product amounts hint', () => {
  it('says how many products have their own amount; none says nothing', () => {
    const dos = { ...CON_ITEMS, items: [...CON_ITEMS.items, { item_id: 4173, monto_unit: '8.50' }] };
    render(<SellOutCampanasTable campanas={[dos, { ...CAMPANA_MIGRADA, id: 56, items: [] }]} selectedId={null} onSelect={() => {}} />);
    expect(screen.getAllByText('2 montos por producto')).toHaveLength(1);
    expect(screen.queryByText(/monto por producto/)).not.toBeInTheDocument();
  });
});
