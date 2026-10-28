import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInBonosAPI } from '../../services/sellInAPI';
import { ALCANCE, BONO, PRODUCTOS } from './sellInFixtures';
import SellInBonoPanel from './SellInBonoPanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInBonosAPI: { detalle: vi.fn(), alcance: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
  sellInAPI: { operaciones: vi.fn(), operacionProductos: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  productosAPI: { categorias: vi.fn(), listar: vi.fn() },
}));

const SW8 = 'SW-8 · Switch 8 bocas';
const BASE_BODY = { moneda: 'USD', fecha_desde: '2026-09-01', fecha_hasta: '2026-11-30', descripcion: null, tope_unidades: null, tope_monto: null };
const BONO_MODELOS = {
  ...BONO,
  alcance: 'modelos',
  marca: null,
  modelos: [
    { item_id: 4512, codigo: 'SW-8', descripcion: 'Switch 8 bocas', monto_unit: '4.00', porcentaje: null },
    { item_id: 999, codigo: null, descripcion: null, monto_unit: null, porcentaje: null },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO_MODELOS });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE });
  sellInBonosAPI.crear.mockResolvedValue({ data: { ...BONO_MODELOS, id: 9 } });
  sellInBonosAPI.editar.mockResolvedValue({ data: BONO_MODELOS });
  productosAPI.listar.mockResolvedValue({ data: { productos: PRODUCTOS, total: 2, page: 1, page_size: 10 } });
});

const renderPanel = (props = {}) => render(<SellInBonoPanel bonoId={null} marcas={[]} puedeGestionar onSaved={vi.fn()} onClose={vi.fn()} onVerCompra={vi.fn()} {...props} />);

/** A new models bonus with SW-8, USD 3 per unit and the invoice range. */
const nuevoConSw8 = async (user) => {
  renderPanel();
  await user.click(screen.getByRole('button', { name: 'Modelos' }));
  const buscador = screen.getByRole('group', { name: 'Agregar modelo' });
  await user.type(within(buscador).getByRole('searchbox'), 'switch');
  await user.click(await within(buscador).findByRole('button', { name: /SW-8/ }));
  await user.type(screen.getByLabelText('Monto por unidad'), '3');
  await user.type(screen.getByLabelText('Factura desde'), '2026-09-01');
  await user.type(screen.getByLabelText('Factura hasta'), '2026-11-30');
};

const guardar = (user) => user.click(screen.getByRole('button', { name: 'Guardar bono' }));

describe('SellInBonoForm — a value for each model (T23b)', () => {
  it('sends a model with its own amount per unit as an object', async () => {
    const user = userEvent.setup();
    await nuevoConSw8(user);
    expect(screen.getByText('Los modelos sin valor propio usan el del bono.')).toBeInTheDocument();
    await user.type(screen.getByLabelText(`Monto de ${SW8}`), '4.5');
    await guardar(user);
    expect(sellInBonosAPI.crear).toHaveBeenCalledWith({
      alcance: 'modelos',
      modelos: [{ item_id: 4512, monto_unit: '4.5' }],
      tipo: 'por_unidad',
      monto_unit: '3',
      ...BASE_BODY,
    });
  });

  it('sends a model left empty as an object without a value, so it uses the bonus one', async () => {
    const user = userEvent.setup();
    await nuevoConSw8(user);
    await guardar(user);
    expect(sellInBonosAPI.crear).toHaveBeenCalledWith(expect.objectContaining({ modelos: [{ item_id: 4512 }] }));
  });

  it('loads the stored values on edit and sends the changes', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: 3 });
    const monto = await screen.findByLabelText(`Monto de ${SW8}`);
    expect(monto).toHaveValue(4);
    expect(screen.getByLabelText('Monto de Item 999')).toHaveValue(null);
    await user.clear(monto);
    await user.type(monto, '5');
    await user.type(screen.getByLabelText('Monto de Item 999'), '2.25');
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));
    expect(sellInBonosAPI.editar).toHaveBeenCalledWith(
      3,
      expect.objectContaining({
        modelos: [
          { item_id: 4512, monto_unit: '5' },
          { item_id: 999, monto_unit: '2.25' },
        ],
      }),
    );
  });

  it('does not send the amounts of the other kind after a switch and says they are removed', async () => {
    const user = userEvent.setup();
    await nuevoConSw8(user);
    await user.type(screen.getByLabelText(`Monto de ${SW8}`), '4');
    await user.click(screen.getByRole('button', { name: '% de lo facturado' }));
    expect(screen.getByText('Un bono por porcentaje no lleva montos por unidad propios: al guardar se quita el de 1 modelo.')).toBeInTheDocument();
    expect(screen.getByLabelText(`Porcentaje de ${SW8}`)).toHaveValue(null);
    await user.type(screen.getByLabelText('Porcentaje'), '2');
    await guardar(user);
    expect(sellInBonosAPI.crear).toHaveBeenCalledWith(expect.objectContaining({ tipo: 'porcentaje', modelos: [{ item_id: 4512 }] }));
  });

  it('blocks saving a model value that is zero or a percentage over 100', async () => {
    const user = userEvent.setup();
    await nuevoConSw8(user);
    await user.type(screen.getByLabelText(`Monto de ${SW8}`), '0');
    await guardar(user);
    expect(screen.getByRole('alert')).toHaveTextContent(`El monto por unidad de ${SW8} debe ser mayor que cero.`);

    await user.click(screen.getByRole('button', { name: '% de lo facturado' }));
    await user.type(screen.getByLabelText('Porcentaje'), '2');
    await user.type(screen.getByLabelText(`Porcentaje de ${SW8}`), '120');
    await guardar(user);
    expect(screen.getByRole('alert')).toHaveTextContent(`El porcentaje de ${SW8} no puede superar 100.`);
    expect(sellInBonosAPI.crear).not.toHaveBeenCalled();
  });

  it('shows the backend refusal of a model value', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.crear.mockRejectedValue(
      Object.assign(new Error('422'), { response: { status: 422, data: { detail: 'El monto por unidad del modelo 4512 debe ser mayor que cero' } } }),
    );
    await nuevoConSw8(user);
    await user.type(screen.getByLabelText(`Monto de ${SW8}`), '0.001');
    await guardar(user);
    expect(await screen.findByRole('alert')).toHaveTextContent('El monto por unidad del modelo 4512 debe ser mayor que cero');
  });

  it('shows each model with its own value when the bonus is read only', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({
      data: {
        ...BONO_MODELOS,
        tipo: 'porcentaje',
        monto_unit: null,
        porcentaje: '2.5000',
        modelos: [
          { ...BONO_MODELOS.modelos[0], monto_unit: null, porcentaje: '3.5000' },
          BONO_MODELOS.modelos[1],
        ],
      },
    });
    renderPanel({ bonoId: 3, puedeGestionar: false });
    const lista = await screen.findByRole('list', { name: 'Modelos del bono' });
    await waitFor(() => expect(within(lista).getAllByRole('listitem').map((li) => li.textContent)).toEqual([`${SW8} · 3,5 %`, 'Item 999']));
    expect(within(lista).queryByRole('spinbutton')).not.toBeInTheDocument();
  });
});
