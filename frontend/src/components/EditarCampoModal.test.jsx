import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EditarCampoModal from './EditarCampoModal';

describe('EditarCampoModal (old Ventas por Fuera dashboard, vpf-operaciones S4)', () => {
  it('renders nothing while closed', () => {
    const { container } = render(<EditarCampoModal edicion={null} onClose={vi.fn()} onSave={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('saves the typed text with Enter, keyboard only', async () => {
    const onSave = vi.fn();
    render(<EditarCampoModal edicion={{ label: 'Cliente', valor: 'Viejo', numerico: false }} onClose={vi.fn()} onSave={onSave} />);
    const input = screen.getByLabelText('Cliente');
    expect(input).toHaveValue('Viejo');
    await userEvent.clear(input);
    await userEvent.type(input, 'Cliente Inventado{Enter}');
    expect(onSave).toHaveBeenCalledWith('Cliente Inventado');
  });

  it('sends numbers for numeric fields, accepting a decimal comma', async () => {
    const onSave = vi.fn();
    render(<EditarCampoModal edicion={{ label: 'Cantidad', valor: 2, numerico: true }} onClose={vi.fn()} onSave={onSave} />);
    const input = screen.getByLabelText('Cantidad');
    await userEvent.clear(input);
    await userEvent.type(input, '3,5');
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(onSave).toHaveBeenCalledWith(3.5);
  });

  it('sends null when a numeric field is left empty (clears the override)', async () => {
    const onSave = vi.fn();
    render(<EditarCampoModal edicion={{ label: 'Costo unitario', valor: 10, numerico: true }} onClose={vi.fn()} onSave={onSave} />);
    await userEvent.clear(screen.getByLabelText('Costo unitario'));
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(onSave).toHaveBeenCalledWith(null);
  });

  it('blocks saving a non-numeric value in a numeric field', async () => {
    const onSave = vi.fn();
    render(<EditarCampoModal edicion={{ label: 'Precio unitario', valor: '', numerico: true }} onClose={vi.fn()} onSave={onSave} />);
    await userEvent.type(screen.getByLabelText('Precio unitario'), 'abc{Enter}');
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('cancel closes without saving', async () => {
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(<EditarCampoModal edicion={{ label: 'Código', valor: 'X1', numerico: false }} onClose={onClose} onSave={onSave} />);
    await userEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(onClose).toHaveBeenCalled();
    expect(onSave).not.toHaveBeenCalled();
  });
});
