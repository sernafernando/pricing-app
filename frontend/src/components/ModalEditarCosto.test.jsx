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

  it('the old screen still starts from the VARIOS % of the pricing constants', async () => {
    api.get.mockImplementation((url) =>
      Promise.resolve({ data: url === '/pricing-constants/actual' ? { varios_porcentaje: 7.2 } : {} }),
    );
    api.put.mockResolvedValue({ data: {} });
    render(<ModalEditarCosto mostrar operacion={operacion} onClose={vi.fn()} onSave={vi.fn()} />);
    expect(await screen.findByDisplayValue('7.2')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Guardar Costo' }));
    expect(api.put.mock.calls[0][1].costo_unitario).toBeCloseTo(500 * 1.072, 6);
  });

  it('with guardarCosto, hands it the cost instead of the old PUT (vpf-operaciones S3e)', async () => {
    const guardarCosto = vi.fn().mockResolvedValue(undefined);
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(
      <ModalEditarCosto mostrar operacion={operacion} onClose={onClose} onSave={onSave} guardarCosto={guardarCosto} />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Guardar Costo' }));
    expect(guardarCosto).toHaveBeenCalledWith(500);
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

  describe('Operaciones por Fuera (guardarCosto, owner L4)', () => {
    const sinCosto = { ...operacion, costo_unitario: 0, precio_final_sin_iva: 12000 };

    beforeEach(() => {
      api.get.mockImplementation((url) =>
        Promise.resolve({ data: url === '/pricing-constants/actual' ? { varios_porcentaje: 7.2 } : {} }),
      );
    });

    const abrir = (guardarCosto) =>
      render(<ModalEditarCosto mostrar operacion={sinCosto} onClose={vi.fn()} onSave={vi.fn()} guardarCosto={guardarCosto} />);

    it('the optional % starts at 0: 10000 typed -> 10000 saved, Costo D 10.650,00 shown live', async () => {
      const guardarCosto = vi.fn().mockResolvedValue(undefined);
      abrir(guardarCosto);
      const porcentaje = screen.getByLabelText(/Markup Costo \(%\)/);
      expect(porcentaje).toHaveValue(0);
      expect(screen.getByText(/opcional hasta la decisión de gerencia/i)).toBeInTheDocument();

      await userEvent.type(screen.getByLabelText(/Costo Unitario Total/), '10000');

      expect(screen.getByTestId('costo-guardado-preview')).toHaveTextContent('Se guarda $ 10.000,00 · Costo D $ 10.650,00');
      // The preview's profit uses Costo D like the list: 12000 - 10650 = 1350.
      expect(screen.getByText('Costo D Total:').parentElement).toHaveTextContent('$ 10.650');
      expect(screen.getByText('Ganancia:').parentElement).toHaveTextContent('$ 1.350');
      // No stray "0" from the hidden reset button (the original % is 0 here).
      expect(screen.queryByTitle('Restaurar markup original')).not.toBeInTheDocument();
      expect(porcentaje.parentElement.parentElement.textContent).not.toMatch(/\)0$/);
      await userEvent.click(screen.getByRole('button', { name: 'Guardar Costo' }));
      expect(guardarCosto).toHaveBeenCalledWith(10000);
    });

    it('typing 7.2 -> 10720 saved, Costo D 11.416,80', async () => {
      const guardarCosto = vi.fn().mockResolvedValue(undefined);
      abrir(guardarCosto);
      await userEvent.type(screen.getByLabelText(/Costo Unitario Total/), '10000');
      const porcentaje = screen.getByLabelText(/Markup Costo \(%\)/);
      await userEvent.clear(porcentaje);
      await userEvent.type(porcentaje, '7.2');

      expect(screen.getByTestId('costo-guardado-preview')).toHaveTextContent('Se guarda $ 10.720,00 · Costo D $ 11.416,80');
      await userEvent.click(screen.getByRole('button', { name: 'Guardar Costo' }));
      expect(guardarCosto.mock.calls[0][0]).toBeCloseTo(10720, 6);
    });
  });
});
