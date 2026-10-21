import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { sellInAPI } from '../../services/sellInAPI';
import { operacionesFake, PRODUCTOS_OPERACION } from './sellInFixtures';
import SellInOperacionPicker from './SellInOperacionPicker';

vi.mock('../../services/sellInAPI', () => ({ sellInAPI: { operaciones: vi.fn(), operacionProductos: vi.fn() } }));

const LABEL = 'Pedido de compra (N°)';

beforeEach(() => {
  vi.clearAllMocks();
  sellInAPI.operaciones.mockImplementation(operacionesFake);
  sellInAPI.operacionProductos.mockResolvedValue({ data: PRODUCTOS_OPERACION });
});

const renderPicker = (props = {}) => {
  const onPick = vi.fn();
  render(<SellInOperacionPicker label={LABEL} excluir={[]} restriccion={null} onPick={onPick} {...props} />);
  return { onPick, input: screen.getByLabelText(LABEL) };
};

describe('SellInOperacionPicker', () => {
  it('searches as the user types, debounced, and shows what identifies each operation', async () => {
    const user = userEvent.setup();
    const { input } = renderPicker();
    await user.type(input, 'tp-link');

    const opciones = await screen.findAllByRole('option');
    expect(opciones).toHaveLength(2);
    expect(sellInAPI.operaciones).toHaveBeenCalledTimes(1);
    expect(sellInAPI.operaciones).toHaveBeenCalledWith({ q: 'tp-link', excluir: [] });
    const nueva = opciones[0];
    expect(nueva).toHaveTextContent('N° 16');
    expect(nueva).toHaveTextContent('P-00016');
    expect(nueva).toHaveTextContent('TP-Link');
    expect(nueva).toHaveTextContent('3/10/2026');
    expect(nueva).toHaveTextContent('USD 5.000,50');
    expect(nueva).toHaveTextContent('Recibido');
    expect(nueva).toHaveTextContent('Factura A-0001-00001234');
  });

  it('opening the box with no text offers the newest operations', async () => {
    const user = userEvent.setup();
    const { input } = renderPicker();
    await user.click(input);

    expect(await screen.findAllByRole('option')).toHaveLength(3);
    expect(sellInAPI.operaciones).toHaveBeenCalledWith({ q: '', excluir: [] });
  });

  it('clicking an option picks it, clears the box and closes the list', async () => {
    const user = userEvent.setup();
    const { onPick, input } = renderPicker();
    await user.type(input, 'mercu');
    await user.click(await screen.findByRole('option', { name: /N° 20/ }));

    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 20, proveedor_id: 9, moneda: 'ARS' }));
    expect(input).toHaveValue('');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('once an operation is linked, asks only for its supplier and currency, without the linked ones', async () => {
    const user = userEvent.setup();
    const { input } = renderPicker({ excluir: [15], restriccion: { proveedorId: 7, proveedorNombre: 'TP-Link', moneda: 'USD' } });
    expect(screen.getByText('Solo se ofrecen operaciones de TP-Link en USD.')).toBeInTheDocument();
    await user.type(input, 'p-');

    const opciones = await screen.findAllByRole('option');
    expect(opciones).toHaveLength(1);
    expect(opciones[0]).toHaveTextContent('N° 16');
    expect(sellInAPI.operaciones).toHaveBeenLastCalledWith({ q: 'p-', excluir: [15], proveedor_id: 7, moneda: 'USD' });
  });

  it('arrow keys move through the options and Enter picks the highlighted one', async () => {
    const user = userEvent.setup();
    const { onPick, input } = renderPicker();
    await user.type(input, 'p-');
    await screen.findAllByRole('option');

    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}{ArrowUp}');
    expect(screen.getByRole('option', { name: /N° 16/ })).toHaveAttribute('aria-selected', 'true');
    expect(input).toHaveAttribute('aria-activedescendant', screen.getByRole('option', { name: /N° 16/ }).id);
    await user.keyboard('{Enter}');

    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 16 }));
  });

  it('Escape closes the list without picking', async () => {
    const user = userEvent.setup();
    const { onPick, input } = renderPicker();
    await user.type(input, 'p-');
    await screen.findAllByRole('listbox');

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    expect(onPick).not.toHaveBeenCalled();
    expect(input).toHaveValue('p-');
  });

  it('Enter on a typed number adds it at once when exactly one operation has it', async () => {
    const user = userEvent.setup();
    const { onPick, input } = renderPicker();
    await user.type(input, '15{Enter}');

    await waitFor(() => expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 15, numero: 'P-00015' })));
    expect(input).toHaveValue('');
  });

  it('Enter on text that is no single operation number picks nothing', async () => {
    const user = userEvent.setup();
    const { onPick, input } = renderPicker();
    await user.type(input, 'tp-link{Enter}');

    await screen.findAllByRole('option');
    expect(onPick).not.toHaveBeenCalled();
    expect(input).toHaveValue('tp-link');
  });

  it('says so when the search fails', async () => {
    sellInAPI.operaciones.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    const { input } = renderPicker();
    await user.type(input, 'tp');

    expect(await screen.findByText('No se pudieron buscar operaciones.')).toBeInTheDocument();
  });

  it('a failed search stops being reported once the list is closed with Escape', async () => {
    sellInAPI.operaciones.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();
    const { input } = renderPicker();
    await user.type(input, 'tp');
    await screen.findByText('No se pudieron buscar operaciones.');

    await user.keyboard('{Escape}');

    expect(screen.queryByText('No se pudieron buscar operaciones.')).not.toBeInTheDocument();
  });

  it('a failed search stops being reported once a later search picks an operation', async () => {
    sellInAPI.operaciones.mockRejectedValueOnce(new Error('boom'));
    const user = userEvent.setup();
    const { onPick, input } = renderPicker();
    await user.type(input, 'zz');
    await screen.findByText('No se pudieron buscar operaciones.');

    await user.clear(input);
    await user.type(input, 'mercu');
    await user.click(await screen.findByRole('option', { name: /N° 20/ }));

    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ id: 20 }));
    expect(screen.queryByText('No se pudieron buscar operaciones.')).not.toBeInTheDocument();
  });

  it('a failed Enter fast path with the list closed opens it to show the error', async () => {
    const user = userEvent.setup();
    const { onPick, input } = renderPicker();
    await user.type(input, '15');
    await screen.findByRole('listbox');
    await user.keyboard('{Escape}');
    sellInAPI.operaciones.mockRejectedValue(new Error('boom'));

    await user.keyboard('{Enter}');

    expect(await screen.findByText('No se pudieron buscar operaciones.')).toBeInTheDocument();
    expect(onPick).not.toHaveBeenCalled();
  });

  it('points aria-controls at the listbox only while it is shown', async () => {
    const user = userEvent.setup();
    const { input } = renderPicker();
    expect(input).not.toHaveAttribute('aria-controls');

    await user.type(input, 'p-');
    const lista = await screen.findByRole('listbox');
    expect(input).toHaveAttribute('aria-controls', lista.id);

    await user.keyboard('{Escape}');
    expect(input).not.toHaveAttribute('aria-controls');
  });

  it('an empty answer says nothing matched', async () => {
    const user = userEvent.setup();
    const { input } = renderPicker();
    await user.type(input, 'nada');

    expect(await screen.findByText('Ninguna operación coincide.')).toBeInTheDocument();
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
  });

  it('is disabled when no more operations fit', () => {
    const { input } = renderPicker({ deshabilitado: true });
    expect(input).toBeDisabled();
  });

  describe('products of the operation under the pointer', () => {
    const pausa = () => new Promise((resolve) => setTimeout(resolve, 300)); // longer than the hover delay

    const abrirLista = async (user, input) => {
      await user.click(input);
      return screen.findAllByRole('option');
    };

    it('hovering an option shows its products, ordered and received, after a short pause', async () => {
      let resolver;
      sellInAPI.operacionProductos.mockReturnValue(new Promise((resolve) => (resolver = resolve)));
      const user = userEvent.setup();
      const { input } = renderPicker();
      const opcion = (await abrirLista(user, input))[1];

      await user.hover(opcion);

      const popover = await screen.findByRole('tooltip');
      expect(popover).toHaveTextContent('Productos de la operación N° 16');
      expect(popover).toHaveTextContent('Cargando productos…');
      expect(opcion).toHaveAttribute('aria-describedby', popover.id);
      resolver({ data: PRODUCTOS_OPERACION });
      const fila = await within(popover).findByRole('row', { name: /SW-8/ });
      expect(within(fila).getAllByRole('cell').map((celda) => celda.textContent)).toEqual(['SW-8Switch 8 bocas', '12', '10']);
      expect(within(popover).getAllByRole('columnheader').map((th) => th.textContent)).toEqual(['Producto', 'Pedidas', 'Recibidas']);
      expect(within(popover).getByRole('row', { name: /SW-16/ })).toHaveTextContent('Switch 16 bocas');
      expect(sellInAPI.operacionProductos).toHaveBeenCalledWith(16);
    });

    it('sweeping the pointer across the list asks only for the row it rests on', async () => {
      const user = userEvent.setup();
      const { input } = renderPicker();
      const opciones = await abrirLista(user, input);

      await user.hover(opciones[0]);
      await user.hover(opciones[1]);
      await user.hover(opciones[2]);

      expect(await screen.findByRole('tooltip')).toHaveTextContent('N° 15');
      expect(sellInAPI.operacionProductos).toHaveBeenCalledTimes(1);
      expect(sellInAPI.operacionProductos).toHaveBeenCalledWith(15);
    });

    it('asks once per operation and hides when the pointer leaves the list', async () => {
      const user = userEvent.setup();
      const { input } = renderPicker();
      const opcion = (await abrirLista(user, input))[1];

      await user.hover(opcion);
      await screen.findByRole('row', { name: /SW-8/ });
      await user.unhover(opcion);
      await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument());
      await user.hover(opcion);
      await pausa();

      expect(screen.getByRole('row', { name: /SW-8/ })).toBeInTheDocument();
      expect(sellInAPI.operacionProductos).toHaveBeenCalledTimes(1);
    });

    it('the option highlighted with the arrow keys shows its products too', async () => {
      const user = userEvent.setup();
      const { input } = renderPicker();
      await abrirLista(user, input);

      await user.keyboard('{ArrowDown}{ArrowDown}');

      expect(await screen.findByRole('tooltip')).toHaveTextContent('N° 16');
      expect(sellInAPI.operacionProductos).toHaveBeenCalledWith(16);
    });

    it('says so when the operation has no products or they cannot be read', async () => {
      sellInAPI.operacionProductos.mockImplementation((id) =>
        id === 16 ? Promise.resolve({ data: { items: [] } }) : Promise.reject(new Error('boom')),
      );
      const user = userEvent.setup();
      const { input } = renderPicker();
      const opciones = await abrirLista(user, input);

      await user.hover(opciones[1]);
      expect(await screen.findByText('La operación no tiene productos en sus órdenes de compra.')).toBeInTheDocument();
      await user.hover(opciones[2]);
      expect(await screen.findByText('No se pudieron leer los productos.')).toBeInTheDocument();
    });

    it('shows the first twelve products and counts the rest, since a hover card cannot scroll', async () => {
      const items = Array.from({ length: 14 }, (_, i) => ({ item_id: i + 1, codigo: `C-${i + 1}`, descripcion: 'X', pedida: 1, recibida: 0 }));
      sellInAPI.operacionProductos.mockResolvedValue({ data: { items } });
      const user = userEvent.setup();
      const { input } = renderPicker();
      await user.hover((await abrirLista(user, input))[1]);

      expect(await screen.findByText('y 2 productos más')).toBeInTheDocument();
      expect(within(screen.getByRole('tooltip')).getAllByRole('row')).toHaveLength(13); // header + 12
    });

    it('closes with the list', async () => {
      const user = userEvent.setup();
      const { input } = renderPicker();
      await user.hover((await abrirLista(user, input))[1]);
      await screen.findByRole('tooltip');

      await user.keyboard('{Escape}');

      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });

    it('closes when the list or the page scrolls, since its position would go stale', async () => {
      const user = userEvent.setup();
      const { input } = renderPicker();
      await user.hover((await abrirLista(user, input))[1]);
      await screen.findByRole('tooltip');

      fireEvent.scroll(screen.getByRole('listbox')); // scroll does not bubble: only a capture listener sees it

      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
      await pausa();
      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });

    it('closes when the window is resized', async () => {
      const user = userEvent.setup();
      const { input } = renderPicker();
      await user.hover((await abrirLista(user, input))[1]);
      await screen.findByRole('tooltip');

      fireEvent(window, new Event('resize'));

      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });

    it('after closing the list, resting on the same operation again measures it anew instead of reusing the old card', async () => {
      const user = userEvent.setup();
      const { input } = renderPicker();
      const opcion = (await abrirLista(user, input))[1];
      await user.hover(opcion);
      await screen.findByRole('tooltip');
      await user.keyboard('{Escape}');

      await user.hover((await abrirLista(user, input))[1]);

      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument(); // not at once, with a stale position
      expect(await screen.findByRole('tooltip')).toHaveTextContent('N° 16');
    });

    it('reopening the list from the keyboard does not bring back the last hovered card', async () => {
      const user = userEvent.setup();
      const { input } = renderPicker();
      await user.hover((await abrirLista(user, input))[1]);
      await screen.findByRole('tooltip');
      await user.keyboard('{Escape}');

      await user.keyboard('{ArrowDown}');
      await screen.findAllByRole('option');
      await pausa();

      expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    });
  });
});
