import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInBonosAPI } from '../../services/sellInAPI';
import { ALCANCE, BONO } from './sellInFixtures';
import SellInBonoPanel from './SellInBonoPanel';

vi.mock('../../services/sellInAPI', () => ({
  sellInBonosAPI: { detalle: vi.fn(), alcance: vi.fn(), crear: vi.fn(), editar: vi.fn(), anular: vi.fn() },
  sellInAPI: { operaciones: vi.fn(), operacionProductos: vi.fn() },
}));

vi.mock('../../services/api', () => ({
  productosAPI: { categorias: vi.fn(), listar: vi.fn() },
}));

const NO_ACUMULABLE = { ...BONO, acumulable: false };

beforeEach(() => {
  vi.clearAllMocks();
  sellInBonosAPI.detalle.mockResolvedValue({ data: NO_ACUMULABLE });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE });
  sellInBonosAPI.crear.mockResolvedValue({ data: { ...BONO, id: 9 } });
  sellInBonosAPI.editar.mockResolvedValue({ data: NO_ACUMULABLE });
  productosAPI.categorias.mockResolvedValue({ data: { categorias: [] } });
});

const renderPanel = (props = {}) =>
  render(<SellInBonoPanel bonoId={3} marcas={['TP-LINK']} puedeGestionar onSaved={vi.fn()} onClose={vi.fn()} onVerCompra={vi.fn()} {...props} />);

const CHECK = 'Acumulable con otros bonos';

describe('SellInBonoForm — acumulable (T27c)', () => {
  it('a new bonus is acumulable by default and sends the unticked box as false', async () => {
    const user = userEvent.setup();
    renderPanel({ bonoId: null });
    await user.selectOptions(screen.getByLabelText('Marca'), 'TP-LINK');
    await user.type(screen.getByLabelText('Monto por unidad'), '3');
    await user.type(screen.getByLabelText('Factura desde'), '2026-09-01');
    await user.type(screen.getByLabelText('Factura hasta'), '2026-11-30');
    expect(screen.getByLabelText(CHECK)).toBeChecked();

    await user.click(screen.getByLabelText(CHECK));
    await user.click(screen.getByRole('button', { name: 'Guardar bono' }));

    expect(sellInBonosAPI.crear).toHaveBeenCalledWith(expect.objectContaining({ acumulable: false }));
  });

  it('shows the stored flag and keeps it on an edit', async () => {
    const user = userEvent.setup();
    renderPanel();
    expect(await screen.findByLabelText(CHECK)).not.toBeChecked();

    await user.type(screen.getByLabelText('Descripción'), ' x');
    await user.click(screen.getByRole('button', { name: /Guardar/ }));

    expect(sellInBonosAPI.editar).toHaveBeenCalledWith(3, expect.objectContaining({ acumulable: false }));
  });

  it('a read-only viewer sees the flag but cannot change it', async () => {
    renderPanel({ puedeGestionar: false });
    expect(await screen.findByLabelText(CHECK)).toBeDisabled();
  });
});
