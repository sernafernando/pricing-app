import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor, fireEvent, screen } from '@testing-library/react';
import Admin from './Admin';
import api from '../services/api';

/**
 * Focused test for the "Sincronizar IVA" button added next to "Sincronizar
 * Todo" in Admin.jsx > General > Sincronización de Datos.
 *
 * `services/api` is mocked globally (src/test/setup.js). Both buttons open a
 * ModalTesla confirmation dialog (no more window.confirm) before the sync
 * actually runs — the tests below open it, then confirm or cancel.
 */

// While running, a button's label switches to the shared "Sincronizando..."
// text (same as sincronizarTodo), so it can no longer be queried by its idle
// name once a sync starts — index into the sync row instead, which always
// renders exactly 2 buttons in this fixed order: Todo, then IVA.
const botonesSync = (container) => container.querySelectorAll('[class*="syncButtonRow"] button');
const botonTodo = (container) => botonesSync(container)[0];
const botonIva = (container) => botonesSync(container)[1];

const confirmarModal = async () => {
  const confirmBtn = await screen.findByRole('button', { name: 'Sincronizar' });
  fireEvent.click(confirmBtn);
};

const cancelarModal = async () => {
  const cancelBtn = await screen.findByRole('button', { name: 'Cancelar' });
  fireEvent.click(cancelBtn);
};

beforeEach(() => {
  // Admin.jsx renders `tipoCambio.fecha.split(...)` once /tipo-cambio/actual
  // resolves — give it a shape it can render instead of the default `{}`
  // stub from the global api mock, which crashes that section.
  api.get.mockResolvedValue({
    data: { compra: 1000, venta: 1010, fecha: '2026-09-14' },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Admin > Sincronización > IVA', () => {
  it('calls POST /sync-iva when the button is clicked and confirmed', async () => {
    api.post.mockResolvedValueOnce({ data: { insertados: 10, items_reemplazados: 4 } });

    const { container } = render(<Admin />);
    fireEvent.click(botonIva(container));
    await confirmarModal();

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/sync-iva', {});
    });
  });

  it('does not call POST /sync-iva when the confirmation modal is cancelled', async () => {
    const { container } = render(<Admin />);
    fireEvent.click(botonIva(container));
    await cancelarModal();

    expect(api.post).not.toHaveBeenCalledWith('/sync-iva', {});
  });

  it('disables both sync buttons while the IVA sync is running', async () => {
    let resolvePost;
    api.post.mockReturnValueOnce(
      new Promise((resolve) => {
        resolvePost = resolve;
      })
    );

    const { container } = render(<Admin />);
    fireEvent.click(botonIva(container));
    await confirmarModal();

    await waitFor(() => {
      expect(botonIva(container)).toBeDisabled();
    });
    expect(botonTodo(container)).toBeDisabled();

    resolvePost({ data: { insertados: 1, items_reemplazados: 1 } });

    await waitFor(() => {
      expect(botonTodo(container)).not.toBeDisabled();
    });
  });
});

describe('Admin > Sincronización > Todo', () => {
  it('does not call POST /sync when the confirmation modal is cancelled', async () => {
    const { container } = render(<Admin />);
    fireEvent.click(botonTodo(container));
    await cancelarModal();

    expect(api.post).not.toHaveBeenCalledWith('/sync-tipo-cambio', {});
    expect(api.post).not.toHaveBeenCalledWith('/sync', {});
  });

  it('runs the full sync sequence once confirmed', async () => {
    api.post.mockResolvedValue({ data: {} });

    const { container } = render(<Admin />);
    fireEvent.click(botonTodo(container));
    await confirmarModal();

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/sync-tipo-cambio', {});
    });
  });
});
