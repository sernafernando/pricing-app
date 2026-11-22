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

describe('SellInBonoForm — a cost bonus by total amount (S4)', () => {
  // sell-in-costo-si T5 PR A, L25: the server refuses a new lump sum, so the form only offers it to a stored one.
  it('never offers Monto total on a new cost bonus: its form is the % of the sale cost', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(within(screen.getByRole('group', { name: 'Base del bono' })).getByRole('button', { name: 'Sobre el costo de la venta' }));
    expect(screen.queryByRole('group', { name: 'Forma del monto' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Monto total' })).not.toBeInTheDocument();
    expect(screen.getByText('% del costo de la venta')).toBeInTheDocument();
    expect(screen.queryByLabelText('Monto total (ARS)')).not.toBeInTheDocument();
  });

  it('never offers Monto total when editing a stored % cost bonus', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({
      data: { ...BONO_MONTO_TOTAL, tipo: 'porcentaje', porcentaje: '3.0000', monto_total: null, reparto_criterio: null, repartos: [] },
    });
    renderPanel({ bonoId: 21 });
    await screen.findByRole('button', { name: 'Guardar cambios' });
    expect(screen.queryByRole('button', { name: 'Monto total' })).not.toBeInTheDocument();
    expect(screen.getByText('% del costo de la venta')).toBeInTheDocument();
  });

  it('a stored lump sum still edits as one, and may switch to a %', async () => {
    renderPanel({ bonoId: 21 });
    await screen.findByLabelText('Monto total (ARS)');
    const opciones = within(forma()).getAllByRole('button').map((b) => [b.textContent, b.getAttribute('aria-pressed')]);
    expect(opciones).toEqual([
      ['% del costo de la venta', 'false'],
      ['Monto total', 'true'],
    ]);
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
    expect(await screen.findByText(/El total se reparte según las unidades vendidas en las fechas de la línea/)).toBeInTheDocument();
    expect(screen.queryByRole('table', { name: 'Reparto del monto total' })).not.toBeInTheDocument();
  });
});
