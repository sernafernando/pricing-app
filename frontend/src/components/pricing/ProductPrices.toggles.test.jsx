/**
 * Rebate, best offer, web transferencia and "fuera de tarjetas": shown and
 * edited as Productos does (useProductosToggles: same endpoints, payloads,
 * defaults and validation), each control gated by the permission its
 * endpoint enforces. Every save re-reads the product, like a price write.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductPrices from './ProductPrices';
import { pricePermissions } from './productPricePermissions';
import { preciosAPI } from '../../services/api';
import { PRODUCTO, PRODUCTO_CON_REBATE_Y_OFERTA } from './ProductPrices.fixtures';

vi.mock('../../services/api', () => ({
  preciosAPI: {
    obtenerProducto: vi.fn(),
    setRebate: vi.fn(),
    setWebTransferencia: vi.fn(),
    setOutOfCards: vi.fn(),
  },
}));

const ALL = pricePermissions(() => true);
const NONE = pricePermissions(() => false);

const renderPrices = (props = {}) =>
  render(<ProductPrices productItemId={4101} permissions={ALL} onWritten={vi.fn()} {...props} />);

const rowOf = (label) => screen.findByRole('row', { name: new RegExp(`^${label}\\b`) });

beforeEach(() => {
  vi.clearAllMocks();
  preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO_CON_REBATE_Y_OFERTA });
  preciosAPI.setRebate.mockResolvedValue({ data: {} });
  preciosAPI.setWebTransferencia.mockResolvedValue({ data: {} });
  preciosAPI.setOutOfCards.mockResolvedValue({ data: {} });
});

describe('showing them', () => {
  it('shows the rebate price, its percentage and markup_rebate', async () => {
    renderPrices({ permissions: NONE });
    const rebate = await rowOf('Rebate');
    expect(rebate).toHaveTextContent('$ 102.391,37');
    expect(rebate).toHaveTextContent('3,8% de rebate');
    expect(rebate).toHaveTextContent('21,30%');
  });

  it('shows the best offer as Productos does: price, Meli share, rebate amount, end date, PVP and markup', async () => {
    renderPrices({ permissions: NONE });
    const oferta = await rowOf('Mejor oferta');
    expect(oferta).toHaveTextContent('$ 92.000,00');
    expect(oferta).toHaveTextContent('Aporte 4,17%');
    expect(oferta).toHaveTextContent('Rebate $ 4.000,00');
    // The date as stored, never shifted a day by the time zone.
    expect(oferta).toHaveTextContent('Hasta 31/12');
    expect(oferta).toHaveTextContent('PVP $ 96.000,00');
    // mejor_oferta_markup is a ratio: shown as a percentage.
    expect(oferta).toHaveTextContent('12,34%');
  });

  it('shows the web transferencia price, its real markup and the added percentage', async () => {
    renderPrices({ permissions: NONE });
    const web = await rowOf('Web transferencia');
    expect(web).toHaveTextContent('$ 95.000,00');
    expect(web).toHaveTextContent('24,40%');
    expect(web).toHaveTextContent('+6% sobre la clásica');
    expect(web).not.toHaveTextContent('% fijo');
  });

  it('marks a web transferencia percentage kept in bulk changes', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, preservar_porcentaje_web: true } });
    renderPrices({ permissions: NONE });
    expect(await rowOf('Web transferencia')).toHaveTextContent('% fijo');
  });

  it('says so when there is no rebate, offer or web transferencia, and offers no "fuera de tarjetas"', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
    renderPrices();
    expect(await rowOf('Rebate')).toHaveTextContent('Sin rebate');
    expect(await rowOf('Mejor oferta')).toHaveTextContent('—');
    expect(await rowOf('Web transferencia')).toHaveTextContent('—');
    // Productos only shows the checkbox on a product with a priced rebate.
    expect(screen.queryByRole('checkbox', { name: 'Fuera de tarjetas' })).not.toBeInTheDocument();
  });

  it('the out-of-cards rebate is the best offer: no Meli share, no end date', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({
      data: {
        ...PRODUCTO_CON_REBATE_Y_OFERTA,
        out_of_cards: true,
        mejor_oferta_precio: 102391.37,
        mejor_oferta_pvp_seller: 102391.37,
        mejor_oferta_markup: 0.213,
        mejor_oferta_porcentaje_rebate: null,
        mejor_oferta_monto_rebate: null,
        mejor_oferta_fecha_hasta: null,
      },
    });
    renderPrices({ permissions: NONE });
    const oferta = await rowOf('Mejor oferta');
    expect(oferta).toHaveTextContent('$ 102.391,37');
    expect(oferta).not.toHaveTextContent('Aporte');
    expect(oferta).not.toHaveTextContent('Hasta');
  });

  it('is read-only without edit permission: no edit buttons, the checkbox disabled', async () => {
    renderPrices({ permissions: NONE });
    await rowOf('Rebate');
    expect(screen.queryByRole('button', { name: 'Editar rebate' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar web transferencia' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Fuera de tarjetas' })).toBeDisabled();
  });

  it('gates each control by its own permission', async () => {
    renderPrices({ permissions: pricePermissions((code) => code === 'productos.toggle_rebate') });
    await rowOf('Rebate');
    expect(screen.getByRole('button', { name: 'Editar rebate' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar web transferencia' })).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Fuera de tarjetas' })).toBeDisabled();
  });
});

describe('editing the rebate', () => {
  it('saves participation and percentage, re-reads the product and tells the caller', async () => {
    const user = userEvent.setup();
    const onWritten = vi.fn();
    renderPrices({ onWritten });
    await user.click(await screen.findByRole('button', { name: 'Editar rebate' }));
    const editor = screen.getByRole('group', { name: 'Rebate' });
    expect(within(editor).getByRole('checkbox', { name: 'Participa' })).toBeChecked();
    const pct = within(editor).getByRole('textbox', { name: '% de rebate' });
    expect(pct).toHaveValue('3,8');
    await user.clear(pct);
    await user.type(pct, '4,5');
    await user.click(within(editor).getByRole('button', { name: 'Guardar' }));

    await waitFor(() => expect(preciosAPI.setRebate).toHaveBeenCalledWith(4101, { participa_rebate: true, porcentaje_rebate: 4.5 }));
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
    expect(preciosAPI.obtenerProducto).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole('status')).toHaveTextContent('Rebate guardado.');
    expect(screen.queryByRole('group', { name: 'Rebate' })).not.toBeInTheDocument();
  });

  it('turns it off keeping the stored percentage', async () => {
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('button', { name: 'Editar rebate' }));
    const editor = screen.getByRole('group', { name: 'Rebate' });
    await user.click(within(editor).getByRole('checkbox', { name: 'Participa' }));
    // As in Productos, the percentage is only editable while participating.
    expect(within(editor).queryByRole('textbox', { name: '% de rebate' })).not.toBeInTheDocument();
    await user.click(within(editor).getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(preciosAPI.setRebate).toHaveBeenCalledWith(4101, { participa_rebate: false, porcentaje_rebate: 3.8 }));
  });

  it('saves "no participa" whatever the hidden percentage holds, with the stored percentage', async () => {
    // As Productos turning a rebate off (r / toggleRebateRapido): the stored % is sent, the typed one is not.
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('button', { name: 'Editar rebate' }));
    const editor = screen.getByRole('group', { name: 'Rebate' });
    const pct = within(editor).getByRole('textbox', { name: '% de rebate' });
    await user.clear(pct);
    await user.type(pct, '150');
    await user.click(within(editor).getByRole('checkbox', { name: 'Participa' }));
    await user.click(within(editor).getByRole('button', { name: 'Guardar' }));

    await waitFor(() => expect(preciosAPI.setRebate).toHaveBeenCalledWith(4101, { participa_rebate: false, porcentaje_rebate: 3.8 }));
    expect(await screen.findByRole('status')).toHaveTextContent('Rebate guardado.');
  });

  it('says the rebate was saved and still tells the caller when the re-read fails', async () => {
    preciosAPI.obtenerProducto
      .mockResolvedValueOnce({ data: PRODUCTO_CON_REBATE_Y_OFERTA })
      .mockRejectedValueOnce(new Error('Network Error'));
    const user = userEvent.setup();
    const onWritten = vi.fn();
    renderPrices({ onWritten });
    await user.click(await screen.findByRole('button', { name: 'Editar rebate' }));
    await user.click(within(screen.getByRole('group', { name: 'Rebate' })).getByRole('button', { name: 'Guardar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Rebate guardado, pero no se pudieron releer los precios.');
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
  });

  it('starts a product without a rebate at 3,8%', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO, participa_rebate: false, porcentaje_rebate: null } });
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('button', { name: 'Editar rebate' }));
    const editor = screen.getByRole('group', { name: 'Rebate' });
    await user.click(within(editor).getByRole('checkbox', { name: 'Participa' }));
    expect(within(editor).getByRole('textbox', { name: '% de rebate' })).toHaveValue('3,8');
  });

  it.each(['150', '-1', 'abc'])('rejects %s: the percentage must be between 0 and 100', async (value) => {
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('button', { name: 'Editar rebate' }));
    const editor = screen.getByRole('group', { name: 'Rebate' });
    const pct = within(editor).getByRole('textbox', { name: '% de rebate' });
    await user.clear(pct);
    await user.type(pct, value);
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('El porcentaje de rebate debe ser un número entre 0 y 100.');
    expect(preciosAPI.setRebate).not.toHaveBeenCalled();
  });

  it('shows the backend reason when the save is refused, and keeps the editor open', async () => {
    preciosAPI.setRebate.mockRejectedValue({ response: { status: 403, data: { detail: 'No tienes permiso para gestionar rebate' } } });
    const user = userEvent.setup();
    const onWritten = vi.fn();
    renderPrices({ onWritten });
    await user.click(await screen.findByRole('button', { name: 'Editar rebate' }));
    await user.click(within(screen.getByRole('group', { name: 'Rebate' })).getByRole('button', { name: 'Guardar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No tienes permiso para gestionar rebate');
    expect(screen.getByRole('group', { name: 'Rebate' })).toBeInTheDocument();
    expect(onWritten).not.toHaveBeenCalled();
  });

  it('Escape cancels the edit without saving', async () => {
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('button', { name: 'Editar rebate' }));
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('group', { name: 'Rebate' })).not.toBeInTheDocument();
    expect(preciosAPI.setRebate).not.toHaveBeenCalled();
  });
});

describe('editing web transferencia', () => {
  it('saves participation, percentage and the bulk-change lock as query params, then re-reads', async () => {
    const user = userEvent.setup();
    const onWritten = vi.fn();
    renderPrices({ onWritten });
    await user.click(await screen.findByRole('button', { name: 'Editar web transferencia' }));
    const editor = screen.getByRole('group', { name: 'Web transferencia' });
    const pct = within(editor).getByRole('textbox', { name: '% sobre la clásica' });
    expect(pct).toHaveValue('6');
    await user.clear(pct);
    await user.type(pct, '7,5');
    await user.click(within(editor).getByRole('checkbox', { name: 'Conservar el % en cambios masivos' }));
    await user.click(within(editor).getByRole('button', { name: 'Guardar' }));

    await waitFor(() =>
      expect(preciosAPI.setWebTransferencia).toHaveBeenCalledWith(4101, { participa: true, porcentaje_markup: 7.5, preservar_porcentaje: true }),
    );
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
    expect(preciosAPI.obtenerProducto).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole('status')).toHaveTextContent('Web transferencia guardada.');
  });

  it('starts a product without one at 6%, not participating', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('button', { name: 'Editar web transferencia' }));
    const editor = screen.getByRole('group', { name: 'Web transferencia' });
    expect(within(editor).getByRole('checkbox', { name: 'Participa' })).not.toBeChecked();
    expect(within(editor).getByRole('textbox', { name: '% sobre la clásica' })).toHaveValue('6');
    await user.click(within(editor).getByRole('checkbox', { name: 'Participa' }));
    await user.click(within(editor).getByRole('button', { name: 'Guardar' }));
    await waitFor(() =>
      expect(preciosAPI.setWebTransferencia).toHaveBeenCalledWith(4101, { participa: true, porcentaje_markup: 6, preservar_porcentaje: false }),
    );
  });

  it('keeps a stored 0%: saving untouched sends 0, not the 6% default', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, porcentaje_markup_web: 0 } });
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('button', { name: 'Editar web transferencia' }));
    const editor = screen.getByRole('group', { name: 'Web transferencia' });
    expect(within(editor).getByRole('textbox', { name: '% sobre la clásica' })).toHaveValue('0');
    await user.click(within(editor).getByRole('button', { name: 'Guardar' }));
    await waitFor(() =>
      expect(preciosAPI.setWebTransferencia).toHaveBeenCalledWith(4101, { participa: true, porcentaje_markup: 0, preservar_porcentaje: false }),
    );
  });

  it('sends an unreadable percentage as 0, as Productos does', async () => {
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('button', { name: 'Editar web transferencia' }));
    const editor = screen.getByRole('group', { name: 'Web transferencia' });
    const pct = within(editor).getByRole('textbox', { name: '% sobre la clásica' });
    await user.clear(pct);
    await user.click(within(editor).getByRole('button', { name: 'Guardar' }));
    await waitFor(() =>
      expect(preciosAPI.setWebTransferencia).toHaveBeenCalledWith(4101, { participa: true, porcentaje_markup: 0, preservar_porcentaje: false }),
    );
  });
});

describe('fuera de tarjetas', () => {
  it('marks it on a product with a priced rebate and re-reads', async () => {
    const user = userEvent.setup();
    const onWritten = vi.fn();
    renderPrices({ onWritten });
    const box = await screen.findByRole('checkbox', { name: 'Fuera de tarjetas' });
    expect(box).not.toBeChecked();
    await user.click(box);
    await waitFor(() => expect(preciosAPI.setOutOfCards).toHaveBeenCalledWith(4101, true));
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
    expect(preciosAPI.obtenerProducto).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole('status')).toHaveTextContent('Fuera de tarjetas guardado.');
  });

  it('unmarks it', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, out_of_cards: true } });
    const user = userEvent.setup();
    renderPrices();
    const box = await screen.findByRole('checkbox', { name: 'Fuera de tarjetas' });
    expect(box).toBeChecked();
    await user.click(box);
    await waitFor(() => expect(preciosAPI.setOutOfCards).toHaveBeenCalledWith(4101, false));
  });

  it('keeps the written value when the re-read fails, instead of snapping back to the stale one', async () => {
    preciosAPI.obtenerProducto
      .mockResolvedValueOnce({ data: PRODUCTO_CON_REBATE_Y_OFERTA })
      .mockRejectedValueOnce(new Error('Network Error'));
    const user = userEvent.setup();
    const onWritten = vi.fn();
    renderPrices({ onWritten });
    const box = await screen.findByRole('checkbox', { name: 'Fuera de tarjetas' });
    await user.click(box);

    expect(await screen.findByRole('alert')).toHaveTextContent('Fuera de tarjetas guardado, pero no se pudieron releer los precios.');
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('checkbox', { name: 'Fuera de tarjetas' })).toBeChecked();
  });

  it('shows the next successful read, not the kept value', async () => {
    preciosAPI.obtenerProducto
      .mockResolvedValueOnce({ data: PRODUCTO_CON_REBATE_Y_OFERTA })
      .mockRejectedValueOnce(new Error('Network Error'))
      .mockResolvedValue({ data: { ...PRODUCTO_CON_REBATE_Y_OFERTA, participa_web_transferencia: false } });
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('checkbox', { name: 'Fuera de tarjetas' }));
    await screen.findByRole('alert');
    expect(screen.getByRole('checkbox', { name: 'Fuera de tarjetas' })).toBeChecked();

    // Another save re-reads successfully: the stored value (still off here) is shown again.
    await user.click(screen.getByRole('button', { name: 'Editar web transferencia' }));
    await user.click(within(screen.getByRole('group', { name: 'Web transferencia' })).getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(screen.getByRole('row', { name: /^Web transferencia\b/ })).toHaveTextContent('—'));
    expect(screen.getByRole('checkbox', { name: 'Fuera de tarjetas' })).not.toBeChecked();
  });

  it('shows the backend reason when it fails', async () => {
    preciosAPI.setOutOfCards.mockRejectedValue({ response: { status: 404, data: { detail: 'Producto no encontrado' } } });
    const user = userEvent.setup();
    renderPrices();
    await user.click(await screen.findByRole('checkbox', { name: 'Fuera de tarjetas' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Producto no encontrado');
  });
});
