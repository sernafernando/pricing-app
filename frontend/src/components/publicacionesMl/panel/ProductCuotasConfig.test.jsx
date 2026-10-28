/**
 * A product's own instalment settings (publicaciones-ml-paridad-productos S12b), the ones Productos edits from its
 * gear: whether instalments are recalculated (global / always / never) and the extra markup for Web and PVP
 * instalments (empty follows the global one). Editable with `productos.editar_precio_cuotas`, the server's check too.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductCuotasConfig from './ProductCuotasConfig';
import { preciosAPI, productosAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  preciosAPI: { obtenerProducto: vi.fn() },
  productosAPI: { configCuotas: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

let granted = new Set(['productos.editar_precio_cuotas']);
vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

const httpError = (status, detail) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail } } });

const product = (overrides = {}) => ({
  data: {
    item_id: 4101,
    recalcular_cuotas_auto: null,
    markup_adicional_cuotas_custom: 6.5,
    markup_adicional_cuotas_pvp_custom: null,
    ...overrides,
  },
});

const renderConfig = () => render(<ProductCuotasConfig productItemId={4101} />);
// `Field` is a dt/dd pair: the value is the label's next sibling.
const field = (label) => screen.getByText(label).nextElementSibling;

beforeEach(() => {
  granted = new Set(['productos.editar_precio_cuotas']);
  preciosAPI.obtenerProducto.mockReset();
  preciosAPI.obtenerProducto.mockResolvedValue(product());
  productosAPI.configCuotas.mockReset();
  productosAPI.configCuotas.mockResolvedValue({ data: { mensaje: 'Configuración actualizada' } });
});

describe('what it shows', () => {
  it("reads the product's settings, an empty one following the global", async () => {
    renderConfig();
    expect(await screen.findByText('Usar la configuración global')).toBeInTheDocument();
    expect(preciosAPI.obtenerProducto).toHaveBeenCalledWith(4101);
    expect(field('Markup adicional cuotas Web')).toHaveTextContent('6,5 %');
    expect(field('Markup adicional cuotas PVP')).toHaveTextContent('Global');
  });

  it.each([
    [true, 'Siempre recalcular'],
    [false, 'Nunca recalcular'],
  ])('recalcular %s reads %s', async (value, text) => {
    preciosAPI.obtenerProducto.mockResolvedValue(product({ recalcular_cuotas_auto: value }));
    renderConfig();
    expect(await screen.findByText(text)).toBeInTheDocument();
  });

  it('without the permission it only reads', async () => {
    granted = new Set();
    renderConfig();
    await screen.findByText('Usar la configuración global');
    expect(screen.queryByRole('button', { name: 'Editar cuotas' })).not.toBeInTheDocument();
  });

  it('a failed read says so and retries', async () => {
    preciosAPI.obtenerProducto.mockRejectedValueOnce(httpError(500));
    const user = userEvent.setup();
    renderConfig();
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo cargar la configuración de cuotas.');
    await user.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByText('Usar la configuración global')).toBeInTheDocument();
  });
});

describe('editing', () => {
  async function openForm(user) {
    renderConfig();
    await user.click(await screen.findByRole('button', { name: 'Editar cuotas' }));
  }

  it('starts from the stored settings and saves all three, an empty markup as the global', async () => {
    const user = userEvent.setup();
    await openForm(user);
    expect(screen.getByLabelText('Recalcular cuotas')).toHaveValue('global');
    expect(screen.getByLabelText('Markup adicional cuotas Web (%)')).toHaveValue('6.5');
    expect(screen.getByLabelText('Markup adicional cuotas PVP (%)')).toHaveValue('');

    await user.selectOptions(screen.getByLabelText('Recalcular cuotas'), 'never');
    await user.clear(screen.getByLabelText('Markup adicional cuotas Web (%)'));
    await user.type(screen.getByLabelText('Markup adicional cuotas PVP (%)'), '3');
    preciosAPI.obtenerProducto.mockResolvedValue(
      product({ recalcular_cuotas_auto: false, markup_adicional_cuotas_custom: null, markup_adicional_cuotas_pvp_custom: 3 }),
    );
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(productosAPI.configCuotas).toHaveBeenCalledWith(4101, {
      recalcular_cuotas_auto: false,
      markup_adicional_cuotas_custom: null,
      markup_adicional_cuotas_pvp_custom: 3,
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Guardado.');
    // What is shown after saving is the stored setting, read again.
    expect(await screen.findByText('Nunca recalcular')).toBeInTheDocument();
    expect(field('Markup adicional cuotas PVP')).toHaveTextContent('3 %');
    expect(preciosAPI.obtenerProducto).toHaveBeenCalledTimes(2);
  });

  it('a saved 0 markup reads "0 %", starts the field at 0 and is sent back as 0, never as the global', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue(product({ markup_adicional_cuotas_custom: 0, markup_adicional_cuotas_pvp_custom: 0 }));
    const user = userEvent.setup();
    renderConfig();
    expect(await screen.findByText('Markup adicional cuotas Web')).toBeInTheDocument();
    expect(field('Markup adicional cuotas Web')).toHaveTextContent('0 %');
    expect(field('Markup adicional cuotas PVP')).toHaveTextContent('0 %');
    await user.click(screen.getByRole('button', { name: 'Editar cuotas' }));
    expect(screen.getByLabelText('Markup adicional cuotas Web (%)')).toHaveValue('0');
    await user.selectOptions(screen.getByLabelText('Recalcular cuotas'), 'always');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(productosAPI.configCuotas).toHaveBeenCalledWith(4101, {
      recalcular_cuotas_auto: true,
      markup_adicional_cuotas_custom: 0,
      markup_adicional_cuotas_pvp_custom: 0,
    });
  });

  it('"Siempre" sends true', async () => {
    const user = userEvent.setup();
    await openForm(user);
    await user.selectOptions(screen.getByLabelText('Recalcular cuotas'), 'always');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(productosAPI.configCuotas).toHaveBeenCalledWith(4101, expect.objectContaining({ recalcular_cuotas_auto: true }));
  });

  it('a markup outside 0-100 is not sent', async () => {
    const user = userEvent.setup();
    await openForm(user);
    await user.clear(screen.getByLabelText('Markup adicional cuotas Web (%)'));
    await user.type(screen.getByLabelText('Markup adicional cuotas Web (%)'), '150');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(screen.getByRole('alert')).toHaveTextContent('El markup adicional tiene que ser un número de 0 a 100.');
    expect(productosAPI.configCuotas).not.toHaveBeenCalled();
  });

  it('a markup typed with a comma is saved as that number', async () => {
    const user = userEvent.setup();
    await openForm(user);
    await user.clear(screen.getByLabelText('Markup adicional cuotas Web (%)'));
    await user.type(screen.getByLabelText('Markup adicional cuotas Web (%)'), '7,25');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(productosAPI.configCuotas).toHaveBeenCalledWith(4101, expect.objectContaining({ markup_adicional_cuotas_custom: 7.25 }));
  });

  it('a markup that is not a number is refused, never saved as the global one', async () => {
    const user = userEvent.setup();
    await openForm(user);
    await user.clear(screen.getByLabelText('Markup adicional cuotas Web (%)'));
    await user.type(screen.getByLabelText('Markup adicional cuotas Web (%)'), '6,5,1');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(screen.getByRole('alert')).toHaveTextContent('El markup adicional tiene que ser un número de 0 a 100.');
    expect(productosAPI.configCuotas).not.toHaveBeenCalled();
  });

  it('a read missing a setting offers no edit, so saving cannot overwrite what it did not see', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { item_id: 4101, recalcular_cuotas_auto: null, markup_adicional_cuotas_custom: 6.5 } });
    renderConfig();
    expect(await screen.findByText('No se pudo leer la configuración completa, así que no se puede editar.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar cuotas' })).not.toBeInTheDocument();
  });

  it('a failed read after saving says so, without claiming it was saved', async () => {
    const user = userEvent.setup();
    await openForm(user);
    preciosAPI.obtenerProducto.mockRejectedValue(httpError(500));
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo cargar la configuración de cuotas.');
    expect(screen.queryByText(/Guardado\./)).not.toBeInTheDocument();
  });

  it('Cancelar sends nothing', async () => {
    const user = userEvent.setup();
    await openForm(user);
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(productosAPI.configCuotas).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Editar cuotas' })).toBeInTheDocument();
  });

  it('a 403 names the permission and keeps the form', async () => {
    productosAPI.configCuotas.mockRejectedValue(httpError(403, 'No tienes permiso'));
    const user = userEvent.setup();
    await openForm(user);
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No tenés permiso para editar la configuración de cuotas.');
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeEnabled();
  });

  it("another failure shows the server's reason", async () => {
    productosAPI.configCuotas.mockRejectedValue(httpError(400, 'Markup web debe estar entre 0 y 100'));
    const user = userEvent.setup();
    await openForm(user);
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Markup web debe estar entre 0 y 100');
  });
});
