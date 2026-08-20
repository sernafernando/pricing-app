/**
 * Contrato del auto-focus de ModalTesla.
 *
 * El focus-trap enfoca el primer elemento focuseable 100 ms DESPUÉS de montar.
 * Ese timer no miraba dónde estaba el foco, así que le robaba el campo a quien
 * ya estuviera escribiendo dentro del modal: el usuario que clickea un input en
 * los primeros 100 ms pierde las teclas que siguen, y en los tests cualquier
 * `user.type` que tarde más de 100 ms (runner cargado) queda a mitad de camino.
 * Era la causa del test intermitente de HorariosDocumentoModal en CI.
 *
 * NOTA: vite.config.js corre la suite con `css: false`; no asertar sobre
 * className, solo sobre roles y foco.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import ModalTesla from './ModalTesla';

const AUTOFOCUS_DELAY_MS = 100;

const abrirModal = (props = {}) =>
  render(
    <ModalTesla isOpen onClose={vi.fn()} title="Modal de prueba" {...props}>
      <input aria-label="Buscar" />
      <input aria-label="Comentario" />
    </ModalTesla>,
  );

/** Deja pasar la ventana del auto-focus. */
const correrElAutoFocus = async () => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(AUTOFOCUS_DELAY_MS + 10);
  });
};

describe('ModalTesla — auto-focus', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('enfoca el primer elemento cuando nadie tomó el foco dentro del modal', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    abrirModal();

    await correrElAutoFocus();

    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cerrar modal' }));
  });

  it('NO le roba el foco a un campo del modal que el usuario ya enfocó', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    abrirModal();

    // El usuario clickea un campo antes de que venza la ventana de 100 ms.
    const buscar = screen.getByLabelText('Buscar');
    act(() => buscar.focus());

    await correrElAutoFocus();

    expect(document.activeElement).toBe(buscar);
  });

  it('el texto tipeado antes del auto-focus no se pierde ni se parte', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    abrirModal();

    const buscar = screen.getByLabelText('Buscar');
    act(() => buscar.focus());
    // Primera mitad del tipeo, todavía dentro de la ventana del timer.
    act(() => {
      buscar.value = 'pér';
    });

    await correrElAutoFocus();

    // El resto de las teclas sigue yendo al mismo campo, no al botón de cerrar.
    act(() => {
      buscar.value = 'pérez';
    });
    expect(document.activeElement).toBe(buscar);
    expect(buscar.value).toBe('pérez');
  });

  it('tampoco pisa el foco de un campo que no es el primero', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    abrirModal();

    const comentario = screen.getByLabelText('Comentario');
    act(() => comentario.focus());

    await correrElAutoFocus();

    expect(document.activeElement).toBe(comentario);
  });

  it('sí toma el foco si lo que estaba enfocado está FUERA del modal', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const externo = document.createElement('button');
    externo.textContent = 'Fuera del modal';
    document.body.appendChild(externo);
    externo.focus();

    abrirModal();
    await correrElAutoFocus();

    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cerrar modal' }));
    externo.remove();
  });
});
