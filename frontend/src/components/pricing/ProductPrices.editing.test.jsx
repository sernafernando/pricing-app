/**
 * Editing a product's prices inline: the same endpoints and payloads
 * Productos uses (useProductosInlineEditing: /precios/set-rapido,
 * /precios/set-cuota) and the same negative-markup check, each control gated
 * by the permission set its endpoint enforces.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductPrices from './ProductPrices';
import { pricePermissions } from './productPricePermissions';
import { preciosAPI } from '../../services/api';
import { PRODUCTO } from './ProductPrices.fixtures';

vi.mock('../../services/api', () => ({
  preciosAPI: {
    obtenerProducto: vi.fn(),
    calcularMarkup: vi.fn(),
    setRapido: vi.fn(),
    setCuota: vi.fn(),
  },
}));

const ALL = pricePermissions(() => true);

const renderPrices = (props = {}) =>
  render(<ProductPrices productItemId={4101} permissions={ALL} onWritten={vi.fn()} {...props} />);

const rowOf = (label) => screen.findByRole('row', { name: new RegExp(`^${label}\\b`) });

async function editRow(user, label, value) {
  const row = await rowOf(label);
  await user.click(within(row).getByRole('button', { name: `Editar ${label}` }));
  const input = within(row).getByRole('textbox', { name: label });
  await user.clear(input);
  await user.type(input, value);
  await user.click(within(row).getByRole('button', { name: 'Guardar' }));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
  preciosAPI.calcularMarkup.mockResolvedValue({ data: { markup: 15.2 } });
  preciosAPI.setRapido.mockResolvedValue({ data: { item_id: 4101 } });
  preciosAPI.setCuota.mockResolvedValue({ data: { item_id: 4101 } });
});

describe('writing the ML list', () => {
  it('saves the clásica through set-rapido with the product item_id, re-reads the product and tells the caller', async () => {
    const user = userEvent.setup();
    const onWritten = vi.fn();
    renderPrices({ onWritten });
    await editRow(user, 'Clásica', '120000,5');
    await waitFor(() =>
      expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 4101, precio: 120000.5, recalcular_cuotas: true }),
    );
    expect(preciosAPI.calcularMarkup).toHaveBeenCalledWith({ item_id: 4101, precio: 120000.5, pricelist_id: 4 });
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
    expect(preciosAPI.obtenerProducto).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole('status')).toHaveTextContent('Precio guardado.');
  });

  it("honours the product's instalment recalculation setting, as Productos does", async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO, recalcular_cuotas_auto: false } });
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'Clásica', '120000');
    await waitFor(() =>
      expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 4101, precio: 120000, recalcular_cuotas: false }),
    );
  });

  it("falls back to the user's Productos preference when the product has no setting", async () => {
    window.localStorage.setItem('recalcularCuotasAuto', 'false');
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'Clásica', '120000');
    await waitFor(() =>
      expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 4101, precio: 120000, recalcular_cuotas: false }),
    );
  });

  it('saves an instalment through set-cuota on the ML list', async () => {
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, '6 cuotas', '130000');
    await waitFor(() =>
      expect(preciosAPI.setCuota).toHaveBeenCalledWith({ item_id: 4101, tipo_cuota: '6', precio: 130000, lista_tipo: 'web' }),
    );
    expect(preciosAPI.calcularMarkup).toHaveBeenCalledWith({ item_id: 4101, precio: 130000, pricelist_id: 14 });
  });
});

describe('reading again from outside (readAgain)', () => {
  it('re-reads the prices when the caller asks, keeping an open edit as it was typed', async () => {
    const user = userEvent.setup();
    const { rerender } = renderPrices({ readAgain: 0 });
    const row = await rowOf('Clásica');
    await user.click(within(row).getByRole('button', { name: 'Editar Clásica' }));
    const input = within(row).getByRole('textbox', { name: 'Clásica' });
    await user.clear(input);
    await user.type(input, '777');
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO, precio_3_cuotas: 111111 } });

    rerender(<ProductPrices productItemId={4101} permissions={ALL} onWritten={vi.fn()} readAgain={1} />);

    await waitFor(() => expect(preciosAPI.obtenerProducto).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole('row', { name: /^3 cuotas\b.*111\.111/ })).toBeInTheDocument();
    expect(within(await rowOf('Clásica')).getByRole('textbox', { name: 'Clásica' })).toHaveValue('777');
  });
});

describe('writing the PVP list', () => {
  it('saves the PVP clásica through set-rapido with lista_tipo pvp', async () => {
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'PVP clásica', '125000');
    await waitFor(() =>
      expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 4101, precio: 125000, recalcular_cuotas: true, lista_tipo: 'pvp' }),
    );
    expect(preciosAPI.calcularMarkup).toHaveBeenCalledWith({ item_id: 4101, precio: 125000, pricelist_id: 12 });
  });

  it('saves a PVP instalment through set-cuota with lista_tipo pvp', async () => {
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'PVP 3 cuotas', '140000');
    await waitFor(() =>
      expect(preciosAPI.setCuota).toHaveBeenCalledWith({ item_id: 4101, tipo_cuota: '3', precio: 140000, lista_tipo: 'pvp' }),
    );
    expect(preciosAPI.calcularMarkup).toHaveBeenCalledWith({ item_id: 4101, precio: 140000, pricelist_id: 18 });
  });
});

describe('guards', () => {
  it('asks inline before saving a negative markup and saves only when confirmed', async () => {
    preciosAPI.calcularMarkup.mockResolvedValue({ data: { markup: -3.5 } });
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'Clásica', '50000');
    const warning = await screen.findByRole('alert');
    expect(warning).toHaveTextContent('-3,50%');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
    await user.click(within(warning).getByRole('button', { name: 'Guardar de todas formas' }));
    await waitFor(() => expect(preciosAPI.setRapido).toHaveBeenCalledTimes(1));
  });

  it('cancelling the negative-markup warning keeps the edit open and writes nothing', async () => {
    preciosAPI.calcularMarkup.mockResolvedValue({ data: { markup: -1 } });
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, '3 cuotas', '100');
    await user.click(within(await screen.findByRole('alert')).getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(within(await rowOf('3 cuotas')).getByRole('textbox', { name: '3 cuotas' })).toBeInTheDocument();
    expect(preciosAPI.setCuota).not.toHaveBeenCalled();
  });

  it('a failed markup check does not block the save, as in Productos', async () => {
    preciosAPI.calcularMarkup.mockRejectedValue(new Error('network'));
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'Clásica', '120000');
    await waitFor(() => expect(preciosAPI.setRapido).toHaveBeenCalledTimes(1));
  });

  it('rejects a value that is not a number without calling the backend', async () => {
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'Clásica', 'abc');
    expect(await screen.findByRole('alert')).toHaveTextContent(/número válido/i);
    expect(preciosAPI.calcularMarkup).not.toHaveBeenCalled();
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
  });

  it('shows the backend error and keeps the edit open', async () => {
    preciosAPI.setCuota.mockRejectedValue({ response: { status: 403, data: { detail: 'No tienes permiso para editar este precio' } } });
    const user = userEvent.setup();
    const onWritten = vi.fn();
    renderPrices({ onWritten });
    await editRow(user, '3 cuotas', '100');
    expect(await screen.findByRole('alert')).toHaveTextContent('No tienes permiso para editar este precio');
    expect(within(await rowOf('3 cuotas')).getByRole('textbox', { name: '3 cuotas' })).toBeInTheDocument();
    expect(onWritten).not.toHaveBeenCalled();
  });

  it('Escape cancels the edit without saving', async () => {
    const user = userEvent.setup();
    renderPrices();
    const row = await rowOf('Clásica');
    await user.click(within(row).getByRole('button', { name: 'Editar Clásica' }));
    await user.keyboard('{Escape}');
    expect(within(row).queryByRole('textbox')).not.toBeInTheDocument();
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
  });
});

describe('permissions mirror the backend', () => {
  it('a Productos editor edits every price', async () => {
    renderPrices({ permissions: pricePermissions((code) => code === 'productos.toggle_rebate') });
    await rowOf('Clásica');
    for (const label of ['Clásica', '3 cuotas', '12 cuotas', 'PVP clásica', 'PVP 6 cuotas']) {
      expect(screen.getByRole('button', { name: `Editar ${label}` })).toBeInTheDocument();
    }
  });

  it('a Tienda editor edits only the ML instalments', async () => {
    renderPrices({ permissions: pricePermissions((code) => code === 'tienda.editar_precio_gremio') });
    await rowOf('Clásica');
    expect(screen.getByRole('button', { name: 'Editar 3 cuotas' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Editar 12 cuotas' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar Clásica' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar PVP clásica' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar PVP 3 cuotas' })).not.toBeInTheDocument();
  });

  it('without an edit permission the view stays read-only', async () => {
    renderPrices({ permissions: pricePermissions(() => false) });
    await rowOf('Clásica');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('reading the typed price strictly (es-AR)', () => {
  it.each([
    ['120.000', 120000],
    ['120.000,50', 120000.5],
  ])('saves %j as %d', async (typed, precio) => {
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'Clásica', typed);
    await waitFor(() => expect(preciosAPI.setRapido).toHaveBeenCalledWith(expect.objectContaining({ precio })));
  });

  it.each(['12abc', '120000.5', '120,5,5'])('rejects %j without calling the backend', async (typed) => {
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, '3 cuotas', typed);
    expect(await screen.findByRole('alert')).toHaveTextContent(/número válido/i);
    expect(preciosAPI.calcularMarkup).not.toHaveBeenCalled();
    expect(preciosAPI.setCuota).not.toHaveBeenCalled();
  });

  it('opens the editor with the stored price in es-AR, so saving it untouched keeps it', async () => {
    const user = userEvent.setup();
    renderPrices();
    const row = await rowOf('Clásica');
    await user.click(within(row).getByRole('button', { name: 'Editar Clásica' }));
    expect(within(row).getByRole('textbox', { name: 'Clásica' })).toHaveValue('98500,5');
    await user.click(within(row).getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(preciosAPI.setRapido).toHaveBeenCalledWith(expect.objectContaining({ precio: 98500.5 })));
  });
});

describe('a price of 0 clears it, as in Productos, after an inline confirmation', () => {
  it('asks before clearing the clásica (which clears the whole list) and sends 0 only when confirmed', async () => {
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'Clásica', '0');
    const warning = await screen.findByRole('alert');
    expect(warning).toHaveTextContent('Esto borra el precio de la lista');
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
    expect(preciosAPI.calcularMarkup).not.toHaveBeenCalled();
    await user.click(within(warning).getByRole('button', { name: 'Borrar el precio' }));
    await waitFor(() =>
      expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 4101, precio: 0, recalcular_cuotas: true }),
    );
  });

  it('asks before clearing one instalment and writes nothing when cancelled', async () => {
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'PVP 3 cuotas', '0');
    const warning = await screen.findByRole('alert');
    expect(warning).toHaveTextContent('Esto borra el precio de PVP 3 cuotas');
    await user.click(within(warning).getByRole('button', { name: 'Cancelar' }));
    expect(preciosAPI.setCuota).not.toHaveBeenCalled();
  });
});

describe('the warning always confirms what is on screen', () => {
  it('editing the value while a warning is open drops the warning, so the old value cannot be confirmed', async () => {
    preciosAPI.calcularMarkup.mockResolvedValueOnce({ data: { markup: -3 } }).mockResolvedValue({ data: { markup: 10 } });
    const user = userEvent.setup();
    renderPrices();
    await editRow(user, 'Clásica', '50000');
    await screen.findByRole('alert');
    const input = within(await rowOf('Clásica')).getByRole('textbox', { name: 'Clásica' });
    await user.clear(input);
    await user.type(input, '90000');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Guardar de todas formas' })).not.toBeInTheDocument();
    await user.type(input, '{Enter}');
    await waitFor(() => expect(preciosAPI.setRapido).toHaveBeenCalledWith(expect.objectContaining({ precio: 90000 })));
    expect(preciosAPI.setRapido).toHaveBeenCalledTimes(1);
  });
});

describe('switching product while a save is in flight', () => {
  it('does not re-read nor report the previous product once another one is shown', async () => {
    let resolveWrite;
    preciosAPI.setRapido.mockReturnValue(new Promise((resolve) => (resolveWrite = resolve)));
    const user = userEvent.setup();
    const onWritten = vi.fn();
    const { rerender } = render(<ProductPrices productItemId={4101} permissions={ALL} onWritten={onWritten} />);
    await editRow(user, 'Clásica', '120000');
    await waitFor(() => expect(preciosAPI.setRapido).toHaveBeenCalledTimes(1));

    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO, item_id: 4102, codigo: 'OTRO-4102' } });
    rerender(<ProductPrices productItemId={4102} permissions={ALL} onWritten={onWritten} />);
    expect(await screen.findByText('OTRO-4102')).toBeInTheDocument();

    resolveWrite({ data: { item_id: 4101 } });
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(preciosAPI.obtenerProducto).toHaveBeenCalledTimes(2);
    expect(preciosAPI.obtenerProducto).toHaveBeenLastCalledWith(4102);
    expect(onWritten).not.toHaveBeenCalled();
    expect(screen.getByText('OTRO-4102')).toBeInTheDocument();
    expect(screen.queryByText('Precio guardado.')).not.toBeInTheDocument();
  });
});
