import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInBonosAPI } from '../../services/sellInAPI';
import { ALCANCE, BONO } from './sellInFixtures';
import SellInBonoPanel from './SellInBonoPanel';
import SellInBonosTable from './SellInBonosTable';

vi.mock('../../services/sellInAPI', () => ({
  sellInBonosAPI: { detalle: vi.fn(), alcance: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
  sellInAPI: { operaciones: vi.fn(), operacionProductos: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  productosAPI: { categorias: vi.fn(), listar: vi.fn() },
}));

// Owner, 2026-10-28: "tablets y notebooks lenovo que aplica hasta 3000 USD entre los dos".
const BONO_TOPE = {
  ...BONO,
  tope_unidades: 1200,
  tope_monto: '3000.00',
  tope_unidades_restantes: 160,
  tope_monto_restante: '0.00',
};

beforeEach(() => {
  vi.clearAllMocks();
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO_TOPE });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE });
  sellInBonosAPI.crear.mockResolvedValue({ data: { ...BONO_TOPE, id: 9 } });
  sellInBonosAPI.editar.mockResolvedValue({ data: BONO_TOPE });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: [] } });
});

const renderPanel = (props = {}) =>
  render(<SellInBonoPanel bonoId={3} marcas={['TP-LINK']} puedeGestionar onSaved={vi.fn()} onClose={vi.fn()} onVerCompra={vi.fn()} {...props} />);

const nuevo = async (user) => {
  renderPanel({ bonoId: null });
  await user.selectOptions(screen.getByLabelText('Marca'), 'TP-LINK');
  await user.type(screen.getByLabelText('Monto por unidad'), '3');
  await user.type(screen.getByLabelText('Factura desde'), '2026-09-01');
  await user.type(screen.getByLabelText('Factura hasta'), '2026-11-30');
};

const guardar = (user, name = 'Guardar bono') => user.click(screen.getByRole('button', { name }));

describe('SellInBonoForm — the shared cap (T24d)', () => {
  it('sends both caps, and no cap as null', async () => {
    const user = userEvent.setup();
    await nuevo(user);
    await guardar(user);
    expect(sellInBonosAPI.crear).toHaveBeenLastCalledWith(expect.objectContaining({ tope_unidades: null, tope_monto: null }));

    await user.type(screen.getByLabelText('Tope de unidades (opcional)'), '500');
    await user.type(screen.getByLabelText('Tope de monto en USD (opcional)'), '3000');
    expect(screen.getByText(/El tope es uno solo para todos los productos y compras del bono/)).toBeInTheDocument();
    await guardar(user);
    expect(sellInBonosAPI.crear).toHaveBeenLastCalledWith(expect.objectContaining({ tope_unidades: '500', tope_monto: '3000' }));
  });

  it.each([
    ['Tope de unidades (opcional)', '0', 'El tope de unidades debe ser un número entero mayor que cero.'],
    ['Tope de unidades (opcional)', '2.5', 'El tope de unidades debe ser un número entero mayor que cero.'],
    ['Tope de monto en USD (opcional)', '0', 'El tope de monto debe ser mayor que cero.'],
  ])('refuses %s = %s before sending it', async (campo, valor, mensaje) => {
    const user = userEvent.setup();
    await nuevo(user);
    await user.type(screen.getByLabelText(campo), valor);
    await guardar(user);
    expect(screen.getByRole('alert')).toHaveTextContent(mensaje);
    expect(sellInBonosAPI.crear).not.toHaveBeenCalled();
  });

  it('loads the stored caps and shows what is left of them', async () => {
    renderPanel();
    expect(await screen.findByLabelText('Tope de unidades (opcional)')).toHaveValue(1200);
    expect(screen.getByLabelText('Tope de monto en USD (opcional)')).toHaveValue(3000);
    expect(screen.getByText('Tope: quedan 160 u de 1.200 · USD 0,00 de USD 3.000,00')).toBeInTheDocument();
  });

  it('empties the money cap when the currency changes, so it is entered again in the new one', async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByLabelText('Tope de monto en USD (opcional)');
    await user.click(screen.getByRole('button', { name: 'ARS' }));
    expect(screen.getByLabelText('Tope de monto en ARS (opcional)')).toHaveValue(null);
    await guardar(user, 'Guardar cambios');
    await waitFor(() => expect(sellInBonosAPI.editar).toHaveBeenCalledWith(3, expect.objectContaining({ moneda: 'ARS', tope_unidades: '1200', tope_monto: null })));
  });

  it('lists what is left of each cap in the bonuses table, and nothing without one', () => {
    render(<SellInBonosTable bonos={[BONO_TOPE, { ...BONO, id: 4 }]} selectedId={null} onSelect={vi.fn()} />);
    expect(screen.getAllByText(/^Tope: quedan/)).toHaveLength(1);
    expect(screen.getByText('Tope: quedan 160 u de 1.200 · USD 0,00 de USD 3.000,00')).toBeInTheDocument();
  });
});
