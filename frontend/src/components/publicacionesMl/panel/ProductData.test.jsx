/**
 * The product's data copied from one of its publications (publicaciones-ml-producto-propio T7): what was copied
 * (title, description, pictures, attributes, from which MLA) and, for who has `ml_publicaciones.editar_producto`,
 * choosing the publication to copy from, after a confirmation when it replaces an earlier copy.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductData from './ProductData';
import { productosPropiosAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productosPropiosAPI: { chooseSource: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const httpError = (status, detail) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail } } });

const DATOS = {
  fuente_mla: 'MLA1',
  titulo: 'Router TP-Link Archer AX55',
  descripcion: 'Router WiFi 6\nDual band',
  fotos: [
    { id: 'P1', url: 'https://x/p1.webp' },
    { id: 'P2', url: 'https://x/p2.webp' },
  ],
  atributos: [
    { id: 'BRAND', name: 'Marca', value_name: 'TP-Link' },
    { id: 'MODEL', name: 'Modelo', value_name: 'Archer AX55' },
  ],
  copiado_at: '2026-10-26T15:00:00Z',
};

const PUBLICATIONS = [
  { item_id: 'MLA1', title: 'Router Archer AX55', status: 'active' },
  { item_id: 'MLA2', title: 'Router Archer AX55 catálogo', status: 'active' },
  { item_id: 'MLA3', title: 'Eliminada', status: 'closed', gone: true },
  { item_id: 'MLA4', title: 'Eliminada en ML', status: 'closed', sub_status: ['deleted'] },
];

const product = (overrides = {}) => ({ item_id: 70, datos: null, can_edit: false, ...overrides });

const renderData = (props = {}) => {
  const onSaved = vi.fn();
  render(<ProductData product={product()} publications={PUBLICATIONS} onSaved={onSaved} {...props} />);
  return onSaved;
};

beforeEach(() => {
  productosPropiosAPI.chooseSource.mockReset();
});

describe('reading', () => {
  it('says nothing was copied yet, and offers no choice without the permission', () => {
    renderData();

    expect(screen.getByText('Todavía no se copiaron datos de ninguna publicación.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Publicación de origen')).not.toBeInTheDocument();
  });

  it('shows the copied title, description, pictures and attributes, and where they came from', () => {
    renderData({ product: product({ datos: DATOS }) });

    expect(screen.getByText(/Copiados de MLA1/)).toBeInTheDocument();
    expect(screen.getByText('Router TP-Link Archer AX55')).toBeInTheDocument();
    expect(screen.getByText(/Router WiFi 6/)).toBeInTheDocument();
    expect(screen.getAllByRole('img').map((img) => img.getAttribute('src'))).toEqual(['https://x/p1.webp', 'https://x/p2.webp']);
    expect(screen.getByText('Marca')).toBeInTheDocument();
    expect(screen.getByText('Archer AX55')).toBeInTheDocument();
  });

  it('says when the source had no description, pictures or attributes', () => {
    renderData({ product: product({ datos: { ...DATOS, descripcion: null, fotos: [], atributos: [] } }) });

    expect(screen.getByText('Sin descripción.')).toBeInTheDocument();
    expect(screen.getByText('Sin fotos.')).toBeInTheDocument();
    expect(screen.getByText('Sin atributos.')).toBeInTheDocument();
  });
});

describe('choosing the source', () => {
  it('offers only the live publications and copies the chosen one', async () => {
    const user = userEvent.setup();
    const copied = product({ datos: DATOS, can_edit: true });
    productosPropiosAPI.chooseSource.mockResolvedValue({ data: copied });
    const onSaved = renderData({ product: product({ can_edit: true }) });

    const select = screen.getByLabelText('Publicación de origen');
    const options = within(select).getAllByRole('option').map((option) => option.value);
    expect(options).toEqual(['', 'MLA1', 'MLA2']);
    expect(screen.getByRole('button', { name: 'Copiar datos' })).toBeDisabled();

    await user.selectOptions(select, 'MLA2');
    await user.click(screen.getByRole('button', { name: 'Copiar datos' }));

    expect(productosPropiosAPI.chooseSource).toHaveBeenCalledWith(70, 'MLA2');
    expect(onSaved).toHaveBeenCalledWith(copied);
  });

  it('asks before replacing an earlier copy, and Cancelar leaves it', async () => {
    const user = userEvent.setup();
    renderData({ product: product({ datos: DATOS, can_edit: true }) });

    await user.click(screen.getByRole('button', { name: 'Cambiar publicación' }));
    await user.selectOptions(screen.getByLabelText('Publicación de origen'), 'MLA2');
    await user.click(screen.getByRole('button', { name: 'Copiar datos' }));

    expect(productosPropiosAPI.chooseSource).not.toHaveBeenCalled();
    expect(screen.getByText('Se reemplazan los datos copiados y lo editado. ¿Copiar de MLA2?')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByLabelText('Publicación de origen')).not.toBeInTheDocument();
    expect(screen.getByText(/Copiados de MLA1/)).toBeInTheDocument();
  });

  it('replaces the copy once confirmed', async () => {
    const user = userEvent.setup();
    productosPropiosAPI.chooseSource.mockResolvedValue({ data: product({ datos: { ...DATOS, fuente_mla: 'MLA2' }, can_edit: true }) });
    const onSaved = renderData({ product: product({ datos: DATOS, can_edit: true }) });

    await user.click(screen.getByRole('button', { name: 'Cambiar publicación' }));
    await user.selectOptions(screen.getByLabelText('Publicación de origen'), 'MLA2');
    await user.click(screen.getByRole('button', { name: 'Copiar datos' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar' }));

    expect(productosPropiosAPI.chooseSource).toHaveBeenCalledWith(70, 'MLA2');
    expect(onSaved).toHaveBeenCalled();
  });

  it.each([
    [409, 'La publicación MLA2 no es una publicación vigente de este producto.', 'La publicación MLA2 no es una publicación vigente de este producto.'],
    [403, undefined, 'No tenés permiso para copiar los datos del producto.'],
    [500, undefined, 'No se pudieron copiar los datos. Probá de nuevo.'],
  ])('a %s says why and copies nothing', async (status, detail, message) => {
    const user = userEvent.setup();
    productosPropiosAPI.chooseSource.mockRejectedValue(httpError(status, detail));
    const onSaved = renderData({ product: product({ can_edit: true }) });

    await user.selectOptions(screen.getByLabelText('Publicación de origen'), 'MLA2');
    await user.click(screen.getByRole('button', { name: 'Copiar datos' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(onSaved).not.toHaveBeenCalled();
  });
});
