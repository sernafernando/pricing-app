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
  it('offers the Marca, Categoría, Subcategoría and PM pickers under "Producto"', async () => {
    render(<ProductFilters filters={filters()} setFilters={vi.fn()} />);
    expect(screen.getByText('Producto')).toBeInTheDocument();
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

  it('a category header in Subcategoría writes all its subcategorías (pubml-filtros S2)', async () => {
    const setFilters = vi.fn();
    render(<ProductFilters filters={filters()} setFilters={setFilters} />);
    await userEvent.click(screen.getByRole('button', { name: 'Subcategoría' }));
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Redes' }));
    expect(setFilters).toHaveBeenCalledWith({ marcas: [], categorias: [], subcategorias: ['12'], pms: [] });
  });

  it('shows the commission group of a subcategoría and the email of a PM, like Productos', async () => {
    productosAPI.subcategorias.mockResolvedValue({
      data: { categorias: [{ nombre: 'Redes', subcategorias: [{ id: 12, nombre: 'Routers', grupo_id: 3 }] }] },
    });
    productosAPI.pms.mockResolvedValue({ data: [{ id: 7, nombre: 'Ana', email: 'ana@example.com' }] });
    render(<ProductFilters filters={filters()} setFilters={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: 'Subcategoría' }));
    expect(await screen.findByText('G3')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'PM' }));
    expect(await screen.findByText('Ana (ana@example.com)')).toBeInTheDocument();
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

  describe('with the screen facet (pubml-filtros S2: lists narrowed by every active filter)', () => {
    const facet = { marcas: ['TP,LINK', 'Epson'], subcategorias: [12] };

    beforeEach(() => {
      productosAPI.subcategorias.mockResolvedValue({
        data: {
          categorias: [
            { nombre: 'Redes', subcategorias: [{ id: 12, nombre: 'Routers' }, { id: 13, nombre: 'Switches' }] },
            { nombre: 'Audio', subcategorias: [{ id: 40, nombre: 'Parlantes' }] },
          ],
        },
      });
    });

    it('offers the facet brands instead of the catalog ones, and asks the catalog for none', async () => {
      render(<ProductFilters filters={filters()} setFilters={vi.fn()} facet={facet} />);
      await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
      expect(await screen.findByLabelText('Epson')).toBeInTheDocument();
      expect(screen.queryByLabelText('Gauss')).not.toBeInTheDocument();
      expect(productosAPI.marcas).not.toHaveBeenCalled();
    });

    it('a facet brand is written to the URL with the same key as a catalog one', async () => {
      const setFilters = vi.fn();
      render(<ProductFilters filters={filters()} setFilters={setFilters} facet={facet} />);
      await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
      await userEvent.click(await screen.findByLabelText('TP,LINK'));
      expect(setFilters).toHaveBeenCalledWith({ marcas: ['TP%2CLINK'], categorias: [], subcategorias: [], pms: [] });
    });

    it('offers only the catalog subcategorías the facet lists, named and grouped by the catalog', async () => {
      render(<ProductFilters filters={filters({ marcas: ['Epson'] })} setFilters={vi.fn()} facet={facet} />);
      await userEvent.click(screen.getByRole('button', { name: /^Subcategor/ }));
      expect(await screen.findByLabelText('Routers')).toBeInTheDocument();
      expect(screen.queryByLabelText('Switches')).not.toBeInTheDocument();
      expect(screen.queryByText('Audio')).not.toBeInTheDocument();
      // the whole catalog, not one narrowed by the picked brands: the facet already narrows it
      expect(productosAPI.subcategorias).toHaveBeenCalledWith({});
    });

    it('without the facet (before the first response, or on failure) the catalog lists stay', async () => {
      render(<ProductFilters filters={filters({ pms: ['7'] })} setFilters={vi.fn()} facet={null} />);
      await userEvent.click(screen.getByRole('button', { name: /^Marca/ }));
      expect(await screen.findByLabelText('Gauss')).toBeInTheDocument();
      expect(productosAPI.marcas).toHaveBeenCalledWith({ pms: '7' });
    });
  });
});
