/**
 * Behavioural tests for `ProductFiltersPanel` (`ventas-ml-filtros-producto`,
 * `metricas-ml-filtros-dinamicos`): the marca / categoría / subcategoría / PM
 * dropdowns offer exactly the `options` the screen's own response carries
 * (already cross-filtered by the server: every other active filter narrows each
 * list, never its own), and they dismiss cleanly. jsdom runs with `css: false`
 * (see `vitest.config`), so nothing here asserts appearance.
 */
import { describe, it, expect, vi } from 'vitest';
import { useEffect } from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductFiltersPanel from './ProductFiltersPanel';

vi.mock('../../services/api', () => {
  throw new Error('ProductFiltersPanel must not load its own options: they come from the screen response');
});

const EMPTY = { marcas: [], categorias: [], subcategorias: [], pms: [] };
const OPTIONS = {
  marcas: ['Sony', 'LG'],
  categorias: ['Audio', 'Video'],
  subcategorias: [
    { nombre: 'Audio', subcategorias: [{ id: 3, nombre: 'Parlantes' }] },
    { nombre: 'Video', subcategorias: [{ id: 7, nombre: 'Televisores' }] },
  ],
  pms: [{ id: 10, nombre: 'Ana' }],
};

function panel(props = {}) {
  return <ProductFiltersPanel value={EMPTY} onChange={() => {}} options={OPTIONS} {...props} />;
}

describe('ProductFiltersPanel options', () => {
  it('has a button per filter, Categoría included', () => {
    render(panel());
    for (const name of ['Marca', 'Categoría', 'Subcategoría', 'PM']) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument();
    }
  });

  it.each([
    ['Marca', ['Sony', 'LG']],
    ['Categoría', ['Audio', 'Video']],
    ['Subcategoría', ['Parlantes', 'Televisores']],
    ['PM', ['Ana']],
  ])('%s offers the options it was given', async (button, labels) => {
    render(panel());
    await userEvent.click(screen.getByRole('button', { name: button }));
    for (const label of labels) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
  });

  it('shows the narrowed lists it receives (a new `options` replaces the old ones)', async () => {
    const { rerender } = render(panel());
    await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
    expect(await screen.findByText('LG')).toBeInTheDocument();

    rerender(panel({ options: { ...OPTIONS, marcas: ['Sony'] } }));

    expect(screen.getByText('Sony')).toBeInTheDocument();
    expect(screen.queryByText('LG')).not.toBeInTheDocument();
  });

  it('copes with options that have not arrived yet', async () => {
    render(panel({ options: undefined }));
    await userEvent.click(screen.getByRole('button', { name: 'Categoría' }));
    expect(screen.getByPlaceholderText('Buscar categoría...')).toBeInTheDocument();
  });

  it('toggles a categoría through onChange, keeping the other selections', async () => {
    const onChange = vi.fn();
    render(panel({ onChange, value: { ...EMPTY, marcas: ['Sony'] } }));
    await userEvent.click(screen.getByRole('button', { name: 'Categoría' }));
    await userEvent.click(await screen.findByText('Audio'));
    expect(onChange).toHaveBeenCalledWith({ marcas: ['Sony'], categorias: ['Audio'], subcategorias: [], pms: [] });
  });

  it('un-ticks a selected categoría', async () => {
    const onChange = vi.fn();
    render(panel({ onChange, value: { ...EMPTY, categorias: ['Audio', 'Video'] } }));
    await userEvent.click(screen.getByRole('button', { name: /Categoría/ }));
    await userEvent.click(await screen.findByLabelText('Audio'));
    expect(onChange).toHaveBeenCalledWith({ marcas: [], categorias: ['Video'], subcategorias: [], pms: [] });
  });

  it('keeps a selected value visible even if the options no longer list it', async () => {
    render(panel({ value: { ...EMPTY, marcas: ['Philips'] }, options: { ...OPTIONS, marcas: ['Sony'] } }));
    await userEvent.click(screen.getByRole('button', { name: /Marca/ }));
    expect(await screen.findByLabelText('Philips')).toBeChecked();
  });

  it('shows a selection spelled differently from the server once, checked, under the server spelling', async () => {
    render(panel({ value: { ...EMPTY, marcas: ['sony'], categorias: ['AUDIO'] } }));
    await userEvent.click(screen.getByRole('button', { name: /Marca/ }));
    expect(await screen.findAllByLabelText(/^sony$/i)).toHaveLength(1);
    expect(screen.getByLabelText('Sony')).toBeChecked();
    await userEvent.click(screen.getByRole('button', { name: /Categoría/ }));
    expect(await screen.findAllByLabelText(/^audio$/i)).toHaveLength(1);
    expect(screen.getByLabelText('Audio')).toBeChecked();
  });

  it('un-ticking the server spelling removes the differently spelled selection', async () => {
    const onChange = vi.fn();
    render(panel({ onChange, value: { ...EMPTY, marcas: ['sony', 'LG'] } }));
    await userEvent.click(screen.getByRole('button', { name: /Marca/ }));
    await userEvent.click(await screen.findByLabelText('Sony'));
    expect(onChange).toHaveBeenCalledWith({ marcas: ['LG'], categorias: [], subcategorias: [], pms: [] });
  });

  it.each([
    ['before the first response', undefined],
    ['when the request failed (empty lists)', EMPTY],
  ])('keeps a selected subcategoría and PM visible %s', async (_label, options) => {
    render(panel({ options, value: { ...EMPTY, subcategorias: [99], pms: [55] } }));
    await userEvent.click(screen.getByRole('button', { name: /Subcategoría/ }));
    expect(await screen.findByLabelText('Subcategoría #99')).toBeChecked();
    await userEvent.click(screen.getByRole('button', { name: /PM/ }));
    expect(await screen.findByLabelText('PM #55')).toBeChecked();
  });

  it('keeps a selected subcategoría and PM the lists no longer hold, without duplicating listed ones', async () => {
    render(panel({ value: { ...EMPTY, subcategorias: [3, 99], pms: [10, 55] } }));
    await userEvent.click(screen.getByRole('button', { name: /Subcategoría/ }));
    expect(await screen.findByLabelText('Subcategoría #99')).toBeChecked();
    expect(screen.getAllByLabelText('Parlantes')).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: /PM/ }));
    expect(await screen.findByLabelText('PM #55')).toBeChecked();
    expect(screen.getAllByLabelText('Ana')).toHaveLength(1);
  });

  it('shows the selected count in each button badge', () => {
    render(
      panel({ value: { marcas: ['Sony', 'LG'], categorias: ['Audio'], subcategorias: [3], pms: [10] } }),
    );
    expect(within(screen.getByRole('button', { name: /Marca/ })).getByText('2')).toBeInTheDocument();
    expect(within(screen.getByRole('button', { name: /Categoría/ })).getByText('1')).toBeInTheDocument();
  });

  it('filters the lists by the typed search', async () => {
    render(panel());
    await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
    await userEvent.type(screen.getByPlaceholderText('Buscar marca...'), 'so');
    expect(screen.getByText('Sony')).toBeInTheDocument();
    expect(screen.queryByText('LG')).not.toBeInTheDocument();
  });

  it('clears one filter without touching the others', async () => {
    const onChange = vi.fn();
    render(panel({ onChange, value: { marcas: ['Sony'], categorias: ['Audio'], subcategorias: [], pms: [] } }));
    await userEvent.click(screen.getByRole('button', { name: /Categoría/ }));
    await userEvent.click(screen.getByRole('button', { name: /Limpiar filtros/ }));
    expect(onChange).toHaveBeenCalledWith({ marcas: ['Sony'], categorias: [], subcategorias: [], pms: [] });
  });
});

describe('ProductFiltersPanel dropdown dismissal', () => {
  it('opens the Marca dropdown on click', async () => {
    render(<ProductFiltersPanel value={EMPTY} onChange={() => {}} options={OPTIONS} />);
    await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
    expect(await screen.findByText('Sony')).toBeInTheDocument();
  });

  it('closes the dropdown when Escape is pressed', async () => {
    render(<ProductFiltersPanel value={EMPTY} onChange={() => {}} options={OPTIONS} />);
    await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
    await screen.findByText('Sony');

    fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByText('Sony')).not.toBeInTheDocument());
  });

  it('closes the dropdown on an outside click', async () => {
    render(
      <div>
        <div data-testid="outside">afuera</div>
        <ProductFiltersPanel value={EMPTY} onChange={() => {}} options={OPTIONS} />
      </div>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
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
        <ProductFiltersPanel value={EMPTY} onChange={() => {}} options={OPTIONS} />
      </OuterLayout>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Marca' }));
    await screen.findByText('Sony');

    fireEvent.keyDown(window, { key: 'Escape' });

    await waitFor(() => expect(screen.queryByText('Sony')).not.toBeInTheDocument());
    expect(outerHandler).not.toHaveBeenCalled();
  });
});
