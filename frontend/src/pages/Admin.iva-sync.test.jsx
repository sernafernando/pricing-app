import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor, fireEvent } from '@testing-library/react';
import Admin from './Admin';
import api from '../services/api';

/**
 * Focused test for the "Sincronizar IVA" button added next to "Sincronizar
 * Todo" in Admin.jsx > General > Sincronización de Datos.
 *
 * `services/api` is mocked globally (src/test/setup.js). Confirm dialog is
 * stubbed with vi.spyOn on window.confirm, same as sincronizarTodo needs it.
 */

// While running, a button's label switches to the shared "⏳ Sincronizando..."
// text (same as sincronizarTodo), so it can no longer be queried by its idle
// name once a sync starts — index into the sync row instead, which always
// renders exactly 2 buttons in this fixed order: Todo, then IVA.
const botonesSync = (container) => container.querySelectorAll('[class*="syncButtonRow"] button');
const botonTodo = (container) => botonesSync(container)[0];
const botonIva = (container) => botonesSync(container)[1];

beforeEach(() => {
  vi.spyOn(window, 'confirm').mockReturnValue(true);
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
  it('calls POST /sync-iva when the button is clicked', async () => {
    api.post.mockResolvedValueOnce({ data: { insertados: 10, items_reemplazados: 4 } });

    const { container } = render(<Admin />);
    fireEvent.click(botonIva(container));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/sync-iva', {});
    });
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
