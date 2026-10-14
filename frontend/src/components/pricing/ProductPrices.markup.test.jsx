/**
 * Editing a price by its target markup: the row's pricelist goes to
 * POST /precios/calcular-por-markup (with adicional_markup 0, or the backend
 * adds its default 4%), the resulting price is shown, and only on confirmation
 * it is written through the same set-rapido / set-cuota path as a typed price.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductPrices from './ProductPrices';
import { pricePermissions } from './productPricePermissions';
import { preciosAPI } from '../../services/api';
import { PRODUCTO } from './ProductPrices.fixtures';

vi.mock('../../services/api', () => ({
  preciosAPI: {
    obtenerProducto: vi.fn(),
    tipoCambioActual: vi.fn(),
    calcularMarkup: vi.fn(),
    calcularPorMarkup: vi.fn(),
    setRapido: vi.fn(),
    setCuota: vi.fn(),
  },
}));

const ALL = pricePermissions(() => true);

const renderPrices = (props = {}) =>
  render(<ProductPrices productItemId={4101} permissions={ALL} onWritten={vi.fn()} {...props} />);

const rowOf = (label) => screen.findByRole('row', { name: new RegExp(`^${label}\\b`) });

async function openByMarkup(user, label) {
  const row = await rowOf(label);
  await user.click(within(row).getByRole('button', { name: `Editar ${label}` }));
  await user.click(within(row).getByRole('button', { name: 'Por markup' }));
  return row;
}

async function previewMarkup(user, label, value) {
  const row = await openByMarkup(user, label);
  const input = within(row).getByRole('textbox', { name: `${label} markup objetivo` });
  await user.clear(input);
  await user.type(input, value);
  await user.click(within(row).getByRole('button', { name: 'Guardar' }));
  return row;
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  preciosAPI.obtenerProducto.mockResolvedValue({ data: PRODUCTO });
  preciosAPI.calcularMarkup.mockResolvedValue({ data: { markup: 15.2 } });
  preciosAPI.calcularPorMarkup.mockResolvedValue({ data: { precio: 120000, markup_real: 25.01 } });
  preciosAPI.setRapido.mockResolvedValue({ data: { item_id: 4101 } });
  preciosAPI.setCuota.mockResolvedValue({ data: { item_id: 4101 } });
});

describe('the markup mode of the editor', () => {
  it('opens with the stored markup and goes back to the stored price', async () => {
    const user = userEvent.setup();
    renderPrices();
    const row = await openByMarkup(user, 'Clásica');
    expect(within(row).getByRole('button', { name: 'Por markup' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(row).getByRole('textbox', { name: 'Clásica markup objetivo' })).toHaveValue('18,4');
    await user.click(within(row).getByRole('button', { name: 'Por markup' }));
    expect(within(row).getByRole('textbox', { name: 'Clásica' })).toHaveValue('98500,5');
  });

  it('shows the resulting price and writes nothing until confirmed, then saves it like a typed price', async () => {
    const user = userEvent.setup();
    const onWritten = vi.fn();
    renderPrices({ onWritten });
    await previewMarkup(user, 'Clásica', '25');

    const preview = await screen.findByRole('status');
    expect(preview).toHaveTextContent('Precio resultante');
    expect(preview).toHaveTextContent('$ 120.000,00');
    expect(preview).toHaveTextContent('25,01%');
    expect(preciosAPI.calcularPorMarkup).toHaveBeenCalledWith({ item_id: 4101, pricelist_id: 4, markup_objetivo: 25, adicional_markup: 0 });
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();

    await user.click(within(preview).getByRole('button', { name: 'Guardar precio' }));
    await waitFor(() =>
      expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 4101, precio: 120000, recalcular_cuotas: true }),
    );
    await waitFor(() => expect(onWritten).toHaveBeenCalledTimes(1));
    expect(preciosAPI.obtenerProducto).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole('status')).toHaveTextContent('Precio guardado.');
  });

  it.each([
    ['3 cuotas', 17, { tipo_cuota: '3', lista_tipo: 'web' }],
    ['6 cuotas', 14, { tipo_cuota: '6', lista_tipo: 'web' }],
    ['9 cuotas', 13, { tipo_cuota: '9', lista_tipo: 'web' }],
    ['12 cuotas', 23, { tipo_cuota: '12', lista_tipo: 'web' }],
    ['PVP 3 cuotas', 18, { tipo_cuota: '3', lista_tipo: 'pvp' }],
    ['PVP 6 cuotas', 19, { tipo_cuota: '6', lista_tipo: 'pvp' }],
    ['PVP 9 cuotas', 20, { tipo_cuota: '9', lista_tipo: 'pvp' }],
    ['PVP 12 cuotas', 21, { tipo_cuota: '12', lista_tipo: 'pvp' }],
  ])('%s asks with pricelist %d and writes through set-cuota', async (label, pricelist, cuota) => {
    const user = userEvent.setup();
    renderPrices();
    await previewMarkup(user, label, '20,5');
    expect(preciosAPI.calcularPorMarkup).toHaveBeenCalledWith({ item_id: 4101, pricelist_id: pricelist, markup_objetivo: 20.5, adicional_markup: 0 });
    await user.click(within(await screen.findByRole('status')).getByRole('button', { name: 'Guardar precio' }));
    await waitFor(() => expect(preciosAPI.setCuota).toHaveBeenCalledWith({ item_id: 4101, precio: 120000, ...cuota }));
  });

  it('PVP clásica asks with pricelist 12 and writes through set-rapido with lista_tipo pvp', async () => {
    const user = userEvent.setup();
    renderPrices();
    await previewMarkup(user, 'PVP clásica', '30');
    expect(preciosAPI.calcularPorMarkup).toHaveBeenCalledWith({ item_id: 4101, pricelist_id: 12, markup_objetivo: 30, adicional_markup: 0 });
    await user.click(within(await screen.findByRole('status')).getByRole('button', { name: 'Guardar precio' }));
    await waitFor(() =>
      expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 4101, precio: 120000, recalcular_cuotas: true, lista_tipo: 'pvp' }),
    );
  });
});

describe('guards', () => {
  it('a negative target markup shows the negative warning with the resulting price before writing', async () => {
    preciosAPI.calcularPorMarkup.mockResolvedValue({ data: { precio: 60000, markup_real: -2.5 } });
    const user = userEvent.setup();
    renderPrices();
    await previewMarkup(user, 'Clásica', '-2,5');
    const warning = await screen.findByRole('alert');
    expect(warning).toHaveTextContent('Markup negativo en Clásica');
    expect(warning).toHaveTextContent('$ 60.000,00');
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
    await user.click(within(warning).getByRole('button', { name: 'Guardar de todas formas' }));
    await waitFor(() => expect(preciosAPI.setRapido).toHaveBeenCalledWith(expect.objectContaining({ precio: 60000 })));
  });

  it('warns when the resulting markup is negative even if the target was not', async () => {
    preciosAPI.calcularPorMarkup.mockResolvedValue({ data: { precio: 60000, markup_real: -0.2 } });
    const user = userEvent.setup();
    renderPrices();
    await previewMarkup(user, 'Clásica', '0');
    expect(await screen.findByRole('alert')).toHaveTextContent('Markup negativo');
  });

  it('cancelling the preview writes nothing and keeps the editor open', async () => {
    const user = userEvent.setup();
    renderPrices();
    const row = await previewMarkup(user, '3 cuotas', '25');
    await user.click(within(await screen.findByRole('status')).getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByText(/Precio resultante/)).not.toBeInTheDocument();
    expect(within(row).getByRole('textbox', { name: '3 cuotas markup objetivo' })).toBeInTheDocument();
    expect(preciosAPI.setCuota).not.toHaveBeenCalled();
  });

  it('typing again drops the preview, so a stale price cannot be confirmed', async () => {
    const user = userEvent.setup();
    renderPrices();
    const row = await previewMarkup(user, 'Clásica', '25');
    await screen.findByText(/Precio resultante/);
    await user.type(within(row).getByRole('textbox', { name: 'Clásica markup objetivo' }), '0');
    expect(screen.queryByText(/Precio resultante/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Guardar precio' })).not.toBeInTheDocument();
  });

  it.each(['25.5', 'abc', '25,555', '+3'])('rejects %j without calling the backend', async (typed) => {
    const user = userEvent.setup();
    renderPrices();
    await previewMarkup(user, 'Clásica', typed);
    expect(await screen.findByRole('alert')).toHaveTextContent(/markup debe ser un número válido/i);
    expect(preciosAPI.calcularPorMarkup).not.toHaveBeenCalled();
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
  });

  it('drops a preview that comes back after the editor changed, so it cannot write a price for another markup', async () => {
    // The input is disabled while the preview is asked; the change below
    // stands for any edit that still reaches the editor meanwhile.
    const user = userEvent.setup();
    let resolve;
    preciosAPI.calcularPorMarkup.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    renderPrices();
    const row = await previewMarkup(user, 'Clásica', '25');
    const input = within(row).getByRole('textbox', { name: 'Clásica markup objetivo' });
    fireEvent.change(input, { target: { value: '30' } });
    await act(async () => resolve({ data: { precio: 120000, markup_real: 25.01 } }));

    expect(screen.queryByRole('button', { name: 'Guardar precio' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Precio resultante/)).not.toBeInTheDocument();
    expect(input).toHaveValue('30');
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
  });

  it('drops a preview that comes back after the editor was cancelled', async () => {
    const user = userEvent.setup();
    let resolve;
    preciosAPI.calcularPorMarkup.mockReturnValueOnce(new Promise((r) => (resolve = r)));
    renderPrices();
    const row = await previewMarkup(user, 'Clásica', '25');
    fireEvent.keyDown(within(row).getByRole('textbox', { name: 'Clásica markup objetivo' }), { key: 'Escape' });
    await act(async () => resolve({ data: { precio: 120000, markup_real: 25.01 } }));
    expect(screen.queryByRole('button', { name: 'Guardar precio' })).not.toBeInTheDocument();
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
  });

  it('Enter in markup mode asks for the preview and never saves the typed markup as a price', async () => {
    const user = userEvent.setup();
    renderPrices();
    const row = await openByMarkup(user, 'Clásica');
    const input = within(row).getByRole('textbox', { name: 'Clásica markup objetivo' });
    await user.clear(input);
    await user.type(input, '25{Enter}');
    expect(await screen.findByRole('status')).toHaveTextContent('$ 120.000,00');
    expect(preciosAPI.calcularPorMarkup).toHaveBeenCalledWith({ item_id: 4101, pricelist_id: 4, markup_objetivo: 25, adicional_markup: 0 });
    expect(preciosAPI.calcularMarkup).not.toHaveBeenCalled();
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
    expect(preciosAPI.setCuota).not.toHaveBeenCalled();
  });

  it('shows the backend error and writes nothing', async () => {
    preciosAPI.calcularPorMarkup.mockRejectedValue({ response: { status: 400, data: { detail: 'No hay comisión configurada para lista 4 y grupo 1' } } });
    const user = userEvent.setup();
    renderPrices();
    await previewMarkup(user, 'Clásica', '25');
    expect(await screen.findByRole('alert')).toHaveTextContent('No hay comisión configurada');
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
  });

  it.each([0, -10, null, 'abc'])('refuses a resulting price of %j instead of clearing or writing it', async (precio) => {
    preciosAPI.calcularPorMarkup.mockResolvedValue({ data: { precio, markup_real: 25 } });
    const user = userEvent.setup();
    renderPrices();
    await previewMarkup(user, 'Clásica', '25');
    expect(await screen.findByRole('alert')).toHaveTextContent(/no se pudo calcular un precio/i);
    expect(screen.queryByRole('button', { name: 'Guardar precio' })).not.toBeInTheDocument();
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
  });

  it('a Tienda editor gets the markup mode only on the ML instalments it may write', async () => {
    const user = userEvent.setup();
    renderPrices({ permissions: pricePermissions((code) => code === 'tienda.editar_precio_gremio') });
    await openByMarkup(user, '3 cuotas');
    expect(screen.queryByRole('button', { name: 'Editar Clásica' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar PVP clásica' })).not.toBeInTheDocument();
  });
});
