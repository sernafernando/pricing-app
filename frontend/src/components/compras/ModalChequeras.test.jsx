import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import ModalChequeras from './ModalChequeras';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text and roles.

const { hookValue } = vi.hoisted(() => ({
  hookValue: {
    listarChequeras: vi.fn(),
    actualizarChequera: vi.fn(),
    crearChequera: vi.fn(),
  },
}));

vi.mock('../../hooks/useCheques', () => ({ default: () => hookValue }));
vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }));

const CHEQUERA = {
  id: 7,
  banco_empresa_id: 3,
  descripcion: 'Talonario principal',
  instrumento: 'fisico',
  numero_desde: 1,
  numero_hasta: 100,
  proximo_numero: 12,
  activa: true,
};

const elegirBanco = async (user) => {
  await user.selectOptions(await screen.findByLabelText(/^Banco$/i), '3');
  await screen.findByText('Talonario principal');
};

describe('ModalChequeras', () => {
  beforeEach(() => {
    hookValue.listarChequeras.mockReset().mockResolvedValue({ items: [CHEQUERA], total: 1 });
    hookValue.actualizarChequera.mockReset().mockResolvedValue({ ...CHEQUERA, activa: false });
    api.get.mockReset().mockResolvedValue({ data: { bancos: [{ id: 3, banco: 'Galicia' }] } });
  });

  it('el toggle manda sólo activa, sin arrastrar el resto de la fila', async () => {
    const user = userEvent.setup();
    render(<ModalChequeras onClose={() => {}} empresaId={9} />);
    await elegirBanco(user);

    await user.click(screen.getByLabelText(/Desactivar chequera Talonario principal/i));

    expect(hookValue.actualizarChequera).toHaveBeenCalledWith(7, { activa: false });
  });

  it('editar manda SÓLO los campos que cambiaron', async () => {
    // PATCH parcial de verdad: tocar la descripción no puede hacer que el
    // backend revalide un rango que el usuario no tocó.
    const user = userEvent.setup();
    render(<ModalChequeras onClose={() => {}} empresaId={9} />);
    await elegirBanco(user);

    await user.click(screen.getByLabelText(/Editar chequera Talonario principal/i));
    const descripcion = screen.getByLabelText('Descripción');
    await user.clear(descripcion);
    await user.type(descripcion, 'Talonario agotado');
    await user.click(screen.getByLabelText('Guardar cambios'));

    expect(hookValue.actualizarChequera).toHaveBeenCalledWith(7, {
      descripcion: 'Talonario agotado',
    });
  });

  it('permite borrar la descripción (manda "", no null)', async () => {
    // Con null, Pydantic no lo distingue de "no enviado" y el body caía en el
    // validador de body vacío: el usuario nunca podía limpiar la descripción.
    const user = userEvent.setup();
    render(<ModalChequeras onClose={() => {}} empresaId={9} />);
    await elegirBanco(user);

    await user.click(screen.getByLabelText(/Editar chequera Talonario principal/i));
    await user.clear(screen.getByLabelText('Descripción'));
    await user.click(screen.getByLabelText('Guardar cambios'));

    expect(hookValue.actualizarChequera).toHaveBeenCalledWith(7, { descripcion: '' });
  });

  it('sin cambios no llama al backend', async () => {
    const user = userEvent.setup();
    render(<ModalChequeras onClose={() => {}} empresaId={9} />);
    await elegirBanco(user);

    await user.click(screen.getByLabelText(/Editar chequera Talonario principal/i));
    await user.click(screen.getByLabelText('Guardar cambios'));

    expect(hookValue.actualizarChequera).not.toHaveBeenCalled();
  });

  it('vaciar un número avisa en vez de descartar la edición en silencio', async () => {
    const user = userEvent.setup();
    render(<ModalChequeras onClose={() => {}} empresaId={9} />);
    await elegirBanco(user);

    await user.click(screen.getByLabelText(/Editar chequera Talonario principal/i));
    await user.clear(screen.getByLabelText('Número hasta'));
    await user.click(screen.getByLabelText('Guardar cambios'));

    expect(screen.getByText(/no puede quedar vacío/i)).toBeInTheDocument();
    expect(hookValue.actualizarChequera).not.toHaveBeenCalled();
    // La fila sigue en edición, no cierra fingiendo que guardó.
    expect(screen.getByLabelText('Número hasta')).toBeInTheDocument();
  });

  it('un rechazo del backend deja la fila abierta y muestra el motivo', async () => {
    const user = userEvent.setup();
    hookValue.actualizarChequera.mockRejectedValue({
      response: { data: { detail: 'numero_hasta=40 dejaría fuera al cheque 50, ya emitido.' } },
    });
    render(<ModalChequeras onClose={() => {}} empresaId={9} />);
    await elegirBanco(user);

    await user.click(screen.getByLabelText(/Editar chequera Talonario principal/i));
    const hasta = screen.getByLabelText('Número hasta');
    await user.clear(hasta);
    await user.type(hasta, '40');
    await user.click(screen.getByLabelText('Guardar cambios'));

    expect(await screen.findByText(/dejaría fuera al cheque 50/i)).toBeInTheDocument();
    // La fila NO cierra: el usuario tiene que poder corregir lo que escribió.
    expect(screen.getByLabelText('Número hasta')).toBeInTheDocument();
  });

  it('avisa cuando la lista viene truncada en vez de esconder filas', async () => {
    const user = userEvent.setup();
    hookValue.listarChequeras.mockResolvedValue({ items: [CHEQUERA], total: 250 });
    render(<ModalChequeras onClose={() => {}} empresaId={9} />);
    await elegirBanco(user);

    expect(screen.getByText(/Mostrando 1 de 250 chequeras/i)).toBeInTheDocument();
  });
});
