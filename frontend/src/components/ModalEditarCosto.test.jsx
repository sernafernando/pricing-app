import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../services/api';
import ModalEditarCosto from './ModalEditarCosto';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn() },
}));

const operacion = {
  metrica_id: 7,
  codigo_item: 'X-100',
  descripcion: 'Producto inventado',
  fecha: '2026-11-10',
  cantidad: 1,
  precio_unitario_sin_iva: 1000,
  costo_unitario: 500,
  costo_pesos_sin_iva: 500,
};

describe('ModalEditarCosto (restored, vpf-operaciones S4)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.get.mockResolvedValue({ data: {} });
  });

  it('saves the cost with the VARIOS markup on the same endpoint as before', async () => {
    api.put.mockResolvedValue({ data: {} });
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(<ModalEditarCosto mostrar operacion={operacion} onClose={onClose} onSave={onSave} />);
    await userEvent.click(screen.getByRole('button', { name: 'Guardar Costo' }));
    expect(api.put).toHaveBeenCalledWith('/ventas-fuera-ml/metricas/7/costo', { costo_unitario: 500 * 1.065 });
    expect(onSave).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('with guardarCosto, hands it the same value instead of the old PUT (vpf-operaciones S3e)', async () => {
    const guardarCosto = vi.fn().mockResolvedValue(undefined);
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(
      <ModalEditarCosto mostrar operacion={operacion} onClose={onClose} onSave={onSave} guardarCosto={guardarCosto} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Guardar Costo' }));
    expect(guardarCosto).toHaveBeenCalledWith(500 * 1.065);
    expect(api.put).not.toHaveBeenCalled();
    expect(onSave).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('with guardarCosto, a rejected save shows the same inline error and stays open', async () => {
    const guardarCosto = vi.fn().mockRejectedValue(new Error('boom'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const onClose = vi.fn();
    render(<ModalEditarCosto mostrar operacion={operacion} onClose={onClose} onSave={vi.fn()} guardarCosto={guardarCosto} />);
    await userEvent.click(screen.getByRole('button', { name: 'Guardar Costo' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Error al guardar el costo');
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows a save error inside the modal instead of a browser alert, and stays open', async () => {
    api.put.mockRejectedValue(new Error('boom'));
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const onClose = vi.fn();
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<ModalEditarCosto mostrar operacion={operacion} onClose={onClose} onSave={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Guardar Costo' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Error al guardar el costo');
    expect(alertSpy).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
