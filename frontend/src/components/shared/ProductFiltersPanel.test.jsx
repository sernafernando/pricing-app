/**
 * Behavioural tests for `ProductFiltersPanel`'s dropdown dismissal
 * (`ventas-ml-filtros-producto`). jsdom runs with `css: false` (see
 * `vitest.config`), so nothing here asserts appearance — only that the
 * dropdown opens/closes and that closing it does not also fire an
 * unrelated Escape handler mounted higher up the tree (`VentasMLLayout`).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useEffect } from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductFiltersPanel from './ProductFiltersPanel';
import { productosAPI } from '../../services/api';
import api from '../../services/api';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn() },
  productosAPI: {
    marcas: vi.fn(),
    subcategorias: vi.fn(),
    obtenerMarcasPorPMs: vi.fn(),
    obtenerSubcategoriasPorPMs: vi.fn(),
  },
}));

function mockEndpoints() {
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['Sony', 'LG'] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
  api.get.mockResolvedValue({ data: [] });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockEndpoints();
});

describe('ProductFiltersPanel dropdown dismissal', () => {
  it('opens the Marca dropdown on click', async () => {
    render(<ProductFiltersPanel value={{ marcas: [], subcategorias: [], pms: [] }} onChange={() => {}} />);
    await userEvent.click(screen.getByText('Marca'));
    expect(await screen.findByText('Sony')).toBeInTheDocument();
  });

  it('closes the dropdown when Escape is pressed', async () => {
    render(<ProductFiltersPanel value={{ marcas: [], subcategorias: [], pms: [] }} onChange={() => {}} />);
    await userEvent.click(screen.getByText('Marca'));
    await screen.findByText('Sony');

    fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByText('Sony')).not.toBeInTheDocument());
  });

  it('closes the dropdown on an outside click', async () => {
    render(
      <div>
        <div data-testid="outside">afuera</div>
        <ProductFiltersPanel value={{ marcas: [], subcategorias: [], pms: [] }} onChange={() => {}} />
      </div>,
    );
    await userEvent.click(screen.getByText('Marca'));
    await screen.findByText('Sony');

    await userEvent.click(screen.getByTestId('outside'));

    await waitFor(() => expect(screen.queryByText('Sony')).not.toBeInTheDocument());
  });

  it('does not let a sibling Escape handler (e.g. a detail panel) also fire when the dropdown closes it', async () => {
    // Mirrors the real tree: `VentasMLLayout` is the PARENT of
    // `ProductFiltersPanel`, and React runs child effects before parent
    // effects on mount — registering this listener from a wrapping
    // component's own effect (instead of before `render`) reproduces that
    // real ordering, which is what makes `preventDefault()` an effective
    // signal here.
    const outerHandler = vi.fn();
    function OuterLayout({ children }) {
      useEffect(() => {
        const handleKeyDown = (e) => {
          if (e.key !== 'Escape' || e.defaultPrevented) return;
          outerHandler();
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
      }, []);
      return children;
    }

    render(
      <OuterLayout>
        <ProductFiltersPanel value={{ marcas: [], subcategorias: [], pms: [] }} onChange={() => {}} />
      </OuterLayout>,
    );
    await userEvent.click(screen.getByText('Marca'));
    await screen.findByText('Sony');

    fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByText('Sony')).not.toBeInTheDocument());
    expect(outerHandler).not.toHaveBeenCalled();
  });
});
