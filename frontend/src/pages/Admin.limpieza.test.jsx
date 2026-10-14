import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Admin from './Admin';
import api from '../services/api';

/**
 * "Limpieza Masiva de Precios" (Admin > General): the bulk rebate / web
 * transferencia cleanup. The backend requires admin.limpieza_masiva, so the
 * section must only render for users who hold it, and its feedback goes
 * through the app toast instead of blocking alert() dialogs.
 *
 * The global setup stubs usePermisos() to grant everything; this file
 * overrides it with a configurable set of granted codes.
 */

const permisos = vi.hoisted(() => ({ granted: new Set() }));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [...permisos.granted],
    rol: null,
    tienePermiso: (codigo) => permisos.granted.has(codigo),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const TITULO = 'Limpieza Masiva de Precios';

const abrirModalRebate = () => {
  fireEvent.click(screen.getByRole('button', { name: /Limpiar Rebate/ }));
};

const escribirPalabra = (palabra) => {
  fireEvent.change(screen.getByPlaceholderText('Escribe la palabra aquí'), { target: { value: palabra } });
};

const palabraObjetivo = (container) => container.querySelector('[class*="modalWord"]').textContent;

beforeEach(() => {
  permisos.granted = new Set(['admin.ver_panel']);
  api.get.mockResolvedValue({ data: { compra: 1000, venta: 1010, fecha: '2026-09-14' } });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Admin > Limpieza Masiva de Precios', () => {
  it('is hidden without admin.limpieza_masiva', () => {
    render(<Admin />);

    expect(screen.queryByText(TITULO)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Limpiar Rebate/ })).not.toBeInTheDocument();
  });

  it('is shown with admin.limpieza_masiva', () => {
    permisos.granted.add('admin.limpieza_masiva');

    render(<Admin />);

    expect(screen.getByText(TITULO)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Limpiar Rebate/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Limpiar Web Transferencia/ })).toBeInTheDocument();
  });

  it('reports a wrong verification word with a toast, not an alert, and does not call the API', async () => {
    permisos.granted.add('admin.limpieza_masiva');
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});

    render(<Admin />);
    abrirModalRebate();
    escribirPalabra('NOPE');
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar Limpieza' }));

    expect(await screen.findByText('La palabra de verificación no coincide')).toBeInTheDocument();
    expect(alertSpy).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalledWith('/productos/limpiar-rebate', {});
  });

  it('reports a successful cleanup with a toast, not an alert', async () => {
    permisos.granted.add('admin.limpieza_masiva');
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    api.post.mockResolvedValueOnce({
      data: { mensaje: 'Rebate desactivado en todos los productos', productos_actualizados: 12 },
    });

    const { container } = render(<Admin />);
    abrirModalRebate();
    escribirPalabra(palabraObjetivo(container));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar Limpieza' }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/productos/limpiar-rebate', {});
    });
    expect(
      await screen.findByText('Rebate desactivado en todos los productos. Productos actualizados: 12'),
    ).toBeInTheDocument();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('reports a failed cleanup with an error toast, not an alert', async () => {
    permisos.granted.add('admin.limpieza_masiva');
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
    api.post.mockRejectedValueOnce(new Error('boom'));

    const { container } = render(<Admin />);
    abrirModalRebate();
    escribirPalabra(palabraObjetivo(container));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar Limpieza' }));

    expect(await screen.findByText('Error al realizar la limpieza')).toBeInTheDocument();
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it('uses an icon instead of an emoji on the cleanup buttons', () => {
    permisos.granted.add('admin.limpieza_masiva');

    render(<Admin />);

    for (const name of [/Limpiar Rebate/, /Limpiar Web Transferencia/]) {
      const boton = screen.getByRole('button', { name });
      expect(boton.textContent).not.toContain('🧹');
      expect(boton.querySelector('svg')).not.toBeNull();
    }
  });
});
