import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInBonosAPI } from '../../services/sellInAPI';
import { ALCANCE, ALCANCE_VACIO, BONO } from './sellInFixtures';
import SellInBonoPanel from './SellInBonoPanel';
import SellInBonosTable from './SellInBonosTable';

vi.mock('../../services/sellInAPI', () => ({
  sellInBonosAPI: { detalle: vi.fn(), alcance: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
  sellInAPI: { operaciones: vi.fn(), operacionProductos: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  productosAPI: { categorias: vi.fn(), listar: vi.fn() },
}));

// A bonus over the sale's cost (T25d): % in ARS, its units/amount come from its sales, no purchases.
const BONO_COSTO = {
  ...BONO,
  id: 12,
  tipo: 'porcentaje',
  monto_unit: null,
  porcentaje: '2.7100',
  moneda: 'ARS',
  descripcion: 'TP 3% xQ',
  compras_activas: 0,
  unidades: 250,
  monto_generado: '125000.00',
  montos_generados: [{ moneda: 'ARS', monto: '125000.00' }],
  base: 'costo_venta',
  incluye_iva: false,
  offset_origen_id: null,
};

const MARCAS = ['MERCUSYS', 'TP-LINK'];

beforeEach(() => {
  vi.clearAllMocks();
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO_COSTO });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE_VACIO });
  sellInBonosAPI.crear.mockResolvedValue({ data: BONO_COSTO });
  sellInBonosAPI.editar.mockResolvedValue({ data: { ...BONO_COSTO, incluye_iva: true } });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: ['Routers', 'Switches'] } });
  productosAPI.listar.mockResolvedValue({ data: { productos: [], total: 0, page: 1, page_size: 10 } });
});

const renderPanel = (props = {}) => {
  const handlers = { onSaved: vi.fn(), onClose: vi.fn(), onVerCompra: vi.fn() };
  render(<SellInBonoPanel bonoId={12} marcas={MARCAS} puedeGestionar {...handlers} {...props} />);
  return handlers;
};

const base = () => screen.getByRole('group', { name: 'Base del bono' });

describe('SellInBonoForm — base of a new bonus', () => {
  it('starts on "Sobre facturas" with no IVA checkbox', () => {
    renderPanel({ bonoId: null });
    expect(within(base()).getByRole('button', { name: 'Sobre facturas' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(base()).getByRole('button', { name: 'Sobre el costo de la venta' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByRole('checkbox', { name: 'Incluye IVA' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Factura desde')).toBeInTheDocument();
  });

  it('on the cost base forces % and ARS, hides the invoice scope and dates the sales', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.click(within(base()).getByRole('button', { name: 'Sobre el costo de la venta' }));

    expect(screen.queryByRole('button', { name: 'Monto por unidad' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'USD' })).not.toBeInTheDocument();
    expect(screen.getByText('% del costo de la venta')).toBeInTheDocument();
    expect(screen.getByText(/siempre un porcentaje en pesos/)).toBeInTheDocument();
    expect(within(screen.getByRole('group', { name: 'Alcance' })).queryByRole('button', { name: 'Factura' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('Porcentaje')).toBeInTheDocument();
    expect(screen.getByLabelText('Venta desde')).toBeInTheDocument();
    expect(screen.getByLabelText('Venta hasta')).toBeInTheDocument();
    const iva = screen.getByRole('checkbox', { name: 'Incluye IVA' });
    expect(iva).not.toBeChecked();
    expect(screen.getByText(/se divide por el IVA de cada producto/)).toBeInTheDocument();
  });

  it('moves an invoice-scope bonus to brand when the cost base is chosen', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.click(within(screen.getByRole('group', { name: 'Alcance' })).getByRole('button', { name: 'Factura' }));
    await user.click(within(base()).getByRole('button', { name: 'Sobre el costo de la venta' }));
    expect(within(screen.getByRole('group', { name: 'Alcance' })).getByRole('button', { name: 'Marca' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('creates a cost bonus with its base and the IVA flag', async () => {
    const user = userEvent.setup();
    const { onSaved } = renderPanel({ bonoId: null });
    await user.click(within(base()).getByRole('button', { name: 'Sobre el costo de la venta' }));
    await user.selectOptions(screen.getByLabelText('Marca'), 'TP-LINK');
    await user.type(screen.getByLabelText('Porcentaje'), '3');
    await user.type(screen.getByLabelText('Venta desde'), '2026-01-01');
    await user.type(screen.getByLabelText('Venta hasta'), '2026-12-31');
    await user.click(screen.getByRole('checkbox', { name: 'Incluye IVA' }));
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));

    expect(sellInBonosAPI.crear).toHaveBeenCalledWith({
      alcance: 'marca',
      marca: 'TP-LINK',
      tipo: 'porcentaje',
      porcentaje: '3',
      moneda: 'ARS',
      fecha_desde: '2026-01-01',
      fecha_hasta: '2026-12-31',
      descripcion: null,
      tope_unidades: null,
      tope_monto: null,
      base: 'costo_venta',
      incluye_iva: true,
    });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(BONO_COSTO));
  });

  it('goes back to the invoice bonus as it was when "Sobre facturas" is chosen again', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.click(within(base()).getByRole('button', { name: 'Sobre el costo de la venta' }));
    await user.click(within(base()).getByRole('button', { name: 'Sobre facturas' }));
    expect(screen.getByRole('button', { name: 'Monto por unidad' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'USD' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByRole('checkbox', { name: 'Incluye IVA' })).not.toBeInTheDocument();
  });
});

describe('SellInBonoPanel — a stored cost bonus', () => {
  it('shows the base read-only and saves the IVA flag without the base', async () => {
    const user = userEvent.setup();
    renderPanel();
    const iva = await screen.findByRole('checkbox', { name: 'Incluye IVA' });
    expect(screen.queryByRole('group', { name: 'Base del bono' })).not.toBeInTheDocument();
    expect(screen.getByText('Sobre el costo de la venta')).toBeInTheDocument();
    await user.click(iva);
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));

    expect(sellInBonosAPI.editar).toHaveBeenCalledWith(12, expect.objectContaining({ tipo: 'porcentaje', moneda: 'ARS', incluye_iva: true }));
    expect(sellInBonosAPI.editar.mock.calls[0][1]).not.toHaveProperty('base');
  });

  it('shows what its sales generated and explains its scope instead of empty purchase groups', async () => {
    renderPanel();
    expect(await screen.findByText('250 u vendidas · $ 125.000,00 aplicados en ventas')).toBeInTheDocument();
    expect(screen.queryByText(/compras ·/)).not.toBeInTheDocument();
    expect(await screen.findByText(/Se aplica a las ventas de su alcance/)).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Compras alcanzadas/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: /Pendientes de factura/ })).not.toBeInTheDocument();
  });

  it('labels a bonus migrated from a legacy offset', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: { ...BONO_COSTO, offset_origen_id: 9 } });
    renderPanel();
    expect(await screen.findByText('Migrado del offset #9')).toBeInTheDocument();
  });

  it('keeps the purchase groups of an invoice bonus', async () => {
    sellInBonosAPI.detalle.mockResolvedValue({ data: { ...BONO, base: 'factura', incluye_iva: false, offset_origen_id: null } });
    sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE });
    renderPanel({ bonoId: 3 });
    expect(await screen.findByRole('region', { name: 'Compras alcanzadas (18)' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Incluye IVA' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Migrado del offset/)).not.toBeInTheDocument();
  });
});

describe('SellInBonosTable — cost bonuses', () => {
  it('tags a cost bonus and shows what its sales generated', () => {
    render(<SellInBonosTable bonos={[BONO, { ...BONO_COSTO, offset_origen_id: 9 }]} selectedId={null} onSelect={vi.fn()} />);
    const fila = screen.getByText('TP 3% xQ').closest('tr');
    expect(within(fila).getByText('Sobre costo')).toBeInTheDocument();
    expect(within(fila).getByText('2,71 % del costo')).toBeInTheDocument();
    expect(within(fila).getByText('250 u en ventas')).toBeInTheDocument();
    expect(within(fila).getByText('Migrado del offset #9')).toBeInTheDocument();
    expect(within(fila).getByText('Fecha de venta')).toBeInTheDocument();
    const invoice = screen.getByText('Bono TP-Link USD 3/u').closest('tr');
    expect(within(invoice).queryByText('Sobre costo')).not.toBeInTheDocument();
    expect(within(invoice).getByText('18 compras · 1.040 u')).toBeInTheDocument();
  });
});
