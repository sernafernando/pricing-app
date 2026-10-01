/**
 * Tests for the user-resizable column widths on VentasML (T1).
 * Widths persist per browser under `ventasml:colsizing`, reuse the shared
 * `useColumnSizing` hook, never go under each column's minimum and can be reset.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import VentasML from './VentasML';
import api from '../services/api';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: () => true, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

beforeEach(() => {
  api.get.mockReset();
  api.get.mockImplementation((url) =>
    Promise.resolve({
      data:
        url === '/ml-ventas-ops/sales'
          ? { sales: [], total: 0, facets: { operation_status: {}, goods_status: {} } }
          : {},
    }),
  );
  localStorage.clear();
});

async function grips() {
  await renderWithRouter(<VentasML />);
  await screen.findByText('Ventas ML');
  return screen.findAllByRole('separator');
}

function widthOfCol(index) {
  const cols = document.querySelectorAll('table colgroup col');
  return parseFloat(cols[index].style.width);
}

describe('column resize grips', () => {
  it('renders a grip on every resizable header but not on the last visible one', async () => {
    const found = await grips();
    const headers = document.querySelectorAll('table thead th');
    // alerta is fixed-width and the last column has no right neighbour.
    expect(found.length).toBe(headers.length - 2);
    expect(found[0]).toHaveAccessibleName(/Redimensionar columna Producto/);
  });

  it('dragging a grip changes the colgroup shares and persists them', async () => {
    const [producto] = await grips();
    const before = widthOfCol(1);
    fireEvent.mouseDown(producto, { clientX: 200 });
    fireEvent.mouseMove(document, { clientX: 260 });
    fireEvent.mouseUp(document);
    await waitFor(() => expect(widthOfCol(1)).toBeGreaterThan(before));
    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem('ventasml:colsizing') || '{}');
      expect(Object.keys(saved)).toContain('producto');
    });
  });

  it('keyboard arrows resize a focused grip', async () => {
    const [producto] = await grips();
    const before = widthOfCol(1);
    producto.focus();
    fireEvent.keyDown(producto, { key: 'ArrowRight' });
    await waitFor(() => expect(widthOfCol(1)).toBeGreaterThan(before));
  });

  it('restores saved widths on load', async () => {
    localStorage.setItem('ventasml:colsizing', JSON.stringify({ producto: 900, orden: 100 }));
    await grips();
    expect(widthOfCol(1)).toBeGreaterThan(widthOfCol(2));
  });

  it('shows Restablecer columnas only when there is a custom width, and it clears them', async () => {
    const user = userEvent.setup();
    const [producto] = await grips();
    expect(screen.queryByRole('button', { name: /Restablecer columnas/ })).not.toBeInTheDocument();
    fireEvent.keyDown(producto, { key: 'ArrowRight' });
    const reset = await screen.findByRole('button', { name: /Restablecer columnas/ });
    await user.click(reset);
    await waitFor(() => expect(localStorage.getItem('ventasml:colsizing')).toBeNull());
    expect(screen.queryByRole('button', { name: /Restablecer columnas/ })).not.toBeInTheDocument();
  });

  it('survives a corrupted saved-width payload', async () => {
    localStorage.setItem('ventasml:colsizing', '{not json');
    expect((await grips()).length).toBeGreaterThan(0);
  });
});

describe('rows per page', () => {
  it('sends the chosen limit, resets to the first page and remembers it', async () => {
    api.get.mockImplementation((url) =>
      Promise.resolve({
        data:
          url === '/ml-ventas-ops/sales'
            ? { sales: [], total: 500, facets: { operation_status: {}, goods_status: {} } }
            : {},
      }),
    );
    await renderWithRouter(<VentasML />);
    await userEvent.click(await screen.findByRole('button', { name: 'Página 2' }));
    await userEvent.selectOptions(screen.getByLabelText('Filas por página'), '100');
    await waitFor(() => {
      const calls = api.get.mock.calls.filter((c) => c[0] === '/ml-ventas-ops/sales');
      expect(calls[calls.length - 1][1].params).toMatchObject({ limit: 100, offset: 0 });
    });
    expect(localStorage.getItem('ventasml:pagesize')).toBe('100');
  });
});
