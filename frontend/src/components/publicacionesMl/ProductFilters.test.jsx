import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductFilters from './ProductFilters';
import { productosAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn() },
  productosAPI: { marcas: vi.fn(), categorias: vi.fn(), subcategorias: vi.fn(), pms: vi.fn() },
}));

const filters = (overrides = {}) => ({ marcas: [], categorias: [], subcategorias: [], pms: [], ...overrides });

beforeEach(() => {
  productosAPI.marcas.mockReset().mockResolvedValue({ data: { marcas: ['TP,LINK', 'Gauss'] } });
  productosAPI.categorias.mockReset().mockResolvedValue({ data: { categorias: ['Redes'] } });
  productosAPI.subcategorias
    .mockReset()
    .mockResolvedValue({ data: { categorias: [{ nombre: 'Redes', subcategorias: [{ id: 12, nombre: 'Routers' }] }] } });
  productosAPI.pms.mockReset().mockResolvedValue({ data: [{ id: 7, nombre: 'Ana' }] });
});

describe('ProductFilters', () => {
  it('offers the Marca, Categoría, Subcategoría and PM pickers under "Producto:"', async () => {
    render(<ProductFilters filters={filters()} setFilters={vi.fn()} />);
    expect(screen.getByText('Producto:')).toBeInTheDocument();
    for (const name of ['Marca', 'Categoría', 'Subcategoría', 'PM']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
    await waitFor(() => expect(productosAPI.pms).toHaveBeenCalled());
  });

  it('writes a picked brand to the URL keyed like the backend (a comma escaped)', async () => {
    const setFilters = vi.fn();
    render(<ProductFilters filters={filters()} setFilters={setFilters} />);
    await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
    await userEvent.click(await screen.findByLabelText('TP,LINK'));
    expect(setFilters).toHaveBeenCalledWith({ marcas: ['TP%2CLINK'], categorias: [], subcategorias: [], pms: [] });
  });

  it('writes a picked PM and subcategory as ids', async () => {
    const setFilters = vi.fn();
    render(<ProductFilters filters={filters({ subcategorias: ['12'] })} setFilters={setFilters} />);
    await userEvent.click(screen.getByRole('button', { name: /^PM/ }));
    await userEvent.click(await screen.findByLabelText('Ana'));
    expect(setFilters).toHaveBeenCalledWith({ marcas: [], categorias: [], subcategorias: ['12'], pms: ['7'] });
  });

  it('narrows the brands by the picked subcategories and PMs, and the subcategories by the brands and PMs', async () => {
    render(<ProductFilters filters={filters({ marcas: ['TP%2CLINK'], subcategorias: ['12'], pms: ['7'] })} setFilters={vi.fn()} />);
    await waitFor(() => expect(productosAPI.marcas).toHaveBeenCalledWith({ subcategorias: '12', pms: '7' }));
    expect(productosAPI.subcategorias).toHaveBeenCalledWith({ marcas: 'TP,LINK', pms: '7' });
  });

  it('shows one chip per active value; a chip removes its value', async () => {
    const setFilters = vi.fn();
    render(<ProductFilters filters={filters({ marcas: ['A', 'B'], pms: ['7'] })} setFilters={setFilters} />);
    expect(screen.getByRole('button', { name: 'Quitar Marca: A' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Quitar PM: Ana' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Quitar Marca: A' }));
    expect(setFilters).toHaveBeenCalledWith({ marcas: ['B'] });
  });

  it('clears the four product filters at once, and only them', async () => {
    const setFilters = vi.fn();
    render(<ProductFilters filters={filters({ categorias: ['Redes'] })} setFilters={setFilters} />);
    await userEvent.click(screen.getByRole('button', { name: 'Limpiar producto' }));
    expect(setFilters).toHaveBeenCalledWith({ marcas: [], categorias: [], subcategorias: [], pms: [] });
  });

  it('has no chips and no clear control without product filters', async () => {
    render(<ProductFilters filters={filters()} setFilters={vi.fn()} />);
    await waitFor(() => expect(productosAPI.pms).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: 'Limpiar producto' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Quitar/ })).not.toBeInTheDocument();
  });

  it('keeps the pickers usable when an option list fails to load', async () => {
    productosAPI.marcas.mockRejectedValue(new Error('down'));
    const setFilters = vi.fn();
    render(<ProductFilters filters={filters({ marcas: ['Gauss'] })} setFilters={setFilters} />);
    await userEvent.click(screen.getByRole('button', { name: /^Marca/ }));
    // The selected brand still shows, so it can be unticked.
    await userEvent.click(await screen.findByLabelText('Gauss'));
    expect(setFilters).toHaveBeenCalledWith({ marcas: [], categorias: [], subcategorias: [], pms: [] });
  });
});
