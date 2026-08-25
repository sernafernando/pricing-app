import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FormChequera from './FormChequera';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text and roles.

// Referentially stable on purpose — the form memoizes nothing but the hook is
// re-read on every render.
const { hookValue } = vi.hoisted(() => ({
  hookValue: { crearChequera: vi.fn() },
}));

vi.mock('../../../hooks/useCheques', () => ({ default: () => hookValue }));

const crear = () => screen.getByRole('button', { name: /Crear chequera/i });

describe('FormChequera', () => {
  beforeEach(() => {
    hookValue.crearChequera.mockReset().mockResolvedValue({ id: 77 });
  });

  it('no deja crear sin banco', () => {
    render(<FormChequera bancoEmpresaId={null} />);
    expect(crear()).toBeDisabled();
  });

  it('rechaza un rango a medias', async () => {
    const user = userEvent.setup();
    render(<FormChequera bancoEmpresaId={3} />);

    await user.type(screen.getByLabelText(/Número desde/i), '1');
    await user.click(crear());

    expect(await screen.findByText(/los dos extremos del rango/i)).toBeInTheDocument();
    expect(hookValue.crearChequera).not.toHaveBeenCalled();
  });

  it('rechaza un rango invertido', async () => {
    const user = userEvent.setup();
    render(<FormChequera bancoEmpresaId={3} />);

    await user.type(screen.getByLabelText(/Número desde/i), '100');
    await user.type(screen.getByLabelText(/Número hasta/i), '50');
    await user.click(crear());

    expect(await screen.findByText(/no puede ser menor/i)).toBeInTheDocument();
    expect(hookValue.crearChequera).not.toHaveBeenCalled();
  });

  it('crea la chequera y avisa al caller', async () => {
    const user = userEvent.setup();
    const onCreada = vi.fn();
    render(<FormChequera bancoEmpresaId={3} onCreada={onCreada} />);

    await user.type(screen.getByLabelText(/Descripción/i), 'Talonario principal');
    await user.type(screen.getByLabelText(/Número desde/i), '1');
    await user.type(screen.getByLabelText(/Número hasta/i), '100');
    await user.click(crear());

    expect(hookValue.crearChequera).toHaveBeenCalledWith({
      banco_empresa_id: 3,
      descripcion: 'Talonario principal',
      instrumento: 'fisico',
      numero_desde: 1,
      numero_hasta: 100,
    });
    expect(onCreada).toHaveBeenCalledWith({ id: 77 });
  });

  it('manda el rango en null cuando no se carga, sin inventar 0', async () => {
    const user = userEvent.setup();
    render(<FormChequera bancoEmpresaId={3} />);

    await user.click(crear());

    expect(hookValue.crearChequera).toHaveBeenCalledWith(
      expect.objectContaining({ descripcion: null, numero_desde: null, numero_hasta: null }),
    );
  });

  it('muestra el error del backend sin tragárselo', async () => {
    const user = userEvent.setup();
    hookValue.crearChequera.mockRejectedValue({
      response: { data: { detail: 'El rango se pisa con otra chequera.' } },
    });
    const onCreada = vi.fn();
    render(<FormChequera bancoEmpresaId={3} onCreada={onCreada} />);

    await user.click(crear());

    expect(await screen.findByText('El rango se pisa con otra chequera.')).toBeInTheDocument();
    expect(onCreada).not.toHaveBeenCalled();
  });

  it('Enter crea la chequera sin dejar que el form padre se entere', async () => {
    // El form vive DENTRO del <form> de emisión de cheques: si Enter se propaga,
    // el usuario emite un cheque cuando sólo quería crear el talonario.
    const user = userEvent.setup();
    const onSubmitPadre = vi.fn((e) => e.preventDefault());
    render(
      <form onSubmit={onSubmitPadre}>
        <FormChequera bancoEmpresaId={3} />
        <button type="submit">Emitir cheque</button>
      </form>
    );

    await user.type(screen.getByLabelText(/Descripción/i), 'Talonario{Enter}');

    expect(hookValue.crearChequera).toHaveBeenCalledTimes(1);
    expect(onSubmitPadre).not.toHaveBeenCalled();
  });

  it('Enter sobre Cancelar cancela, no crea la chequera', async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<FormChequera bancoEmpresaId={3} onCancel={onCancel} />);

    screen.getByRole('button', { name: /Cancelar/i }).focus();
    await user.keyboard('{Enter}');

    expect(hookValue.crearChequera).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalled();
  });

  it('sólo ofrece elegir instrumento cuando el caller lo permite', async () => {
    const { rerender } = render(<FormChequera bancoEmpresaId={3} />);
    expect(screen.queryByLabelText(/Instrumento/i)).not.toBeInTheDocument();

    rerender(<FormChequera bancoEmpresaId={3} permitirInstrumento />);
    expect(screen.getByLabelText(/Instrumento/i)).toBeInTheDocument();
  });
});
