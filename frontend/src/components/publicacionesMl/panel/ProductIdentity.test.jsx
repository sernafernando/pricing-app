/**
 * SKU and EAN of our own product in the product panel (publicaciones-ml-producto-propio T6): the values the server
 * computes (EAN from the ERP code, SKU from the linked publications) or the manual ones, the candidates when the
 * publications disagree, and the edit for who has `ml_publicaciones.editar_producto`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductIdentity from './ProductIdentity';
import { productosPropiosAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productosPropiosAPI: { get: vi.fn(), save: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });

const product = (overrides = {}) => ({
  item_id: 70,
  codigo: '7791234567890',
  descripcion: 'Router',
  ean: '7791234567890',
  ean_manual: false,
  sku: 'TL-WR840N',
  sku_manual: false,
  sku_candidatos: ['TL-WR840N'],
  can_edit: false,
  ...overrides,
});

const renderWith = async (data) => {
  productosPropiosAPI.get.mockResolvedValue({ data });
  render(<ProductIdentity productItemId={70} />);
  await screen.findByText('EAN');
};

beforeEach(() => {
  productosPropiosAPI.get.mockReset();
  productosPropiosAPI.save.mockReset();
});

describe('reading', () => {
  it('shows the EAN and the SKU the server computed, and asks for this product', async () => {
    await renderWith(product());

    expect(productosPropiosAPI.get).toHaveBeenCalledWith(70);
    expect(screen.getByText('7791234567890')).toBeInTheDocument();
    expect(screen.getByText('TL-WR840N')).toBeInTheDocument();
    expect(screen.queryByText('manual')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
  });

  it('marks the manual values', async () => {
    await renderWith(product({ sku: 'MIO', sku_manual: true, ean: '123', ean_manual: true }));

    expect(screen.getAllByText('manual')).toHaveLength(2);
  });

  it('says the publications disagree and lists their SKUs when there is no SKU', async () => {
    await renderWith(product({ sku: null, sku_candidatos: ['SKU-A', 'SKU-B'] }));

    expect(screen.getByText('Las publicaciones tienen SKUs distintos: SKU-A, SKU-B')).toBeInTheDocument();
  });

  it('says it is loading until the values arrive', () => {
    productosPropiosAPI.get.mockReturnValue(new Promise(() => {}));
    render(<ProductIdentity productItemId={70} />);

    expect(screen.getByText('Cargando SKU y EAN…')).toBeInTheDocument();
  });

  it('says so when it cannot load, and Reintentar asks again', async () => {
    const user = userEvent.setup();
    productosPropiosAPI.get.mockRejectedValueOnce(httpError(500)).mockResolvedValueOnce({ data: product() });
    render(<ProductIdentity productItemId={70} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar el SKU y el EAN.');
    await user.click(screen.getByRole('button', { name: 'Reintentar' }));

    expect(await screen.findByText('TL-WR840N')).toBeInTheDocument();
    expect(productosPropiosAPI.get).toHaveBeenCalledTimes(2);
  });
});

describe('editing', () => {
  it('starts from the manual values (blank when computed) and saves what was typed', async () => {
    const user = userEvent.setup();
    await renderWith(product({ can_edit: true, ean: '123', ean_manual: true }));
    productosPropiosAPI.save.mockResolvedValue({
      data: product({ can_edit: true, sku: 'NUEVO', sku_manual: true, ean: '123', ean_manual: true }),
    });

    await user.click(screen.getByRole('button', { name: 'Editar' }));
    const sku = screen.getByLabelText('SKU');
    const ean = screen.getByLabelText('EAN');
    expect(sku).toHaveValue('');
    expect(sku).toHaveAttribute('placeholder', 'TL-WR840N');
    expect(ean).toHaveValue('123');
    expect(ean).toHaveAttribute('placeholder', '7791234567890'); // blank goes back to the ERP code

    await user.type(sku, 'NUEVO');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(productosPropiosAPI.save).toHaveBeenCalledWith(70, { sku: 'NUEVO', ean: '123' });
    expect(await screen.findByRole('status')).toHaveTextContent('Guardado.');
    expect(screen.getByText('NUEVO')).toBeInTheDocument();
    expect(screen.queryByLabelText('SKU')).not.toBeInTheDocument();
  });

  it('offers the linked publications SKUs as suggestions', async () => {
    const user = userEvent.setup();
    await renderWith(product({ can_edit: true, sku: null, sku_candidatos: ['SKU-A', 'SKU-B'] }));

    await user.click(screen.getByRole('button', { name: 'Editar' }));

    const listId = screen.getByLabelText('SKU').getAttribute('list');
    const options = [...document.getElementById(listId).querySelectorAll('option')].map((option) => option.value);
    expect(options).toEqual(['SKU-A', 'SKU-B']);
  });

  it('Cancelar leaves the values as they were without saving', async () => {
    const user = userEvent.setup();
    await renderWith(product({ can_edit: true }));

    await user.click(screen.getByRole('button', { name: 'Editar' }));
    await user.type(screen.getByLabelText('SKU'), 'X');
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));

    expect(productosPropiosAPI.save).not.toHaveBeenCalled();
    expect(screen.getByText('TL-WR840N')).toBeInTheDocument();
  });

  it('locks the fields while saving, so nothing typed meanwhile is lost', async () => {
    const user = userEvent.setup();
    await renderWith(product({ can_edit: true }));
    productosPropiosAPI.save.mockReturnValue(new Promise(() => {}));

    await user.click(screen.getByRole('button', { name: 'Editar' }));
    await user.type(screen.getByLabelText('SKU'), 'X');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(screen.getByLabelText('SKU')).toBeDisabled();
    expect(screen.getByLabelText('EAN')).toBeDisabled();
  });

  it.each([
    [403, 'No tenés permiso para editar el SKU y el EAN.'],
    [422, 'Revisá los valores: hasta 100 caracteres cada uno.'],
    [500, 'No se pudo guardar. Probá de nuevo.'],
  ])('a %s keeps the form open and says why', async (status, message) => {
    const user = userEvent.setup();
    await renderWith(product({ can_edit: true }));
    productosPropiosAPI.save.mockRejectedValue(httpError(status));

    await user.click(screen.getByRole('button', { name: 'Editar' }));
    await user.type(screen.getByLabelText('SKU'), 'X');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    await waitFor(() => expect(screen.getByLabelText('SKU')).toHaveValue('X'));
  });
});
