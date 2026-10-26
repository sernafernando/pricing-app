/**
 * Editing the product's copied data (publicaciones-ml-producto-propio T7): title, description, the copied pictures
 * (remove, reorder) and the copied attributes (edit the value, remove), saved whole through `PUT /datos`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductDataForm from './ProductDataForm';
import { productosPropiosAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  productosPropiosAPI: { saveDatos: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

// The app's error envelope: a reason in words comes as `error.message`; FastAPI's own 422 keeps its `detail` list.
const httpError = (status, detail) =>
  Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: typeof detail === 'string' ? { error: { code: 'error', message: detail } } : { detail } },
  });

const DATOS = {
  fuente_mla: 'MLA1',
  titulo: 'Router TP-Link Archer AX55',
  descripcion: 'Router WiFi 6',
  fotos: [
    { id: 'P1', url: 'https://x/p1.webp' },
    { id: 'P2', url: 'https://x/p2.webp' },
    { id: 'P3', url: 'https://x/p3.webp' },
  ],
  atributos: [
    { id: 'BRAND', name: 'Marca', value_name: 'TP-Link' },
    { id: 'MODEL', name: 'Modelo', value_name: 'Archer AX55' },
  ],
  copiado_at: '2026-10-26T15:00:00Z',
};

const UNCHANGED = {
  titulo: DATOS.titulo,
  descripcion: DATOS.descripcion,
  fotos: ['P1', 'P2', 'P3'],
  atributos: [
    { id: 'BRAND', value_name: 'TP-Link' },
    { id: 'MODEL', value_name: 'Archer AX55' },
  ],
};

const renderForm = (datos = DATOS) => {
  const onSaved = vi.fn();
  const onCancel = vi.fn();
  render(<ProductDataForm itemId={70} datos={datos} onSaved={onSaved} onCancel={onCancel} />);
  return { onSaved, onCancel };
};

const pictureSources = () => screen.getAllByRole('img').map((img) => img.getAttribute('src'));

beforeEach(() => {
  productosPropiosAPI.saveDatos.mockReset();
});

describe('saving', () => {
  it('starts from the copy and saves the edited title and description with everything else as it was', async () => {
    const user = userEvent.setup();
    const saved = { item_id: 70, datos: { ...DATOS, titulo: 'Router AX55' } };
    productosPropiosAPI.saveDatos.mockResolvedValue({ data: saved });
    const { onSaved } = renderForm();

    const titulo = screen.getByLabelText('Título');
    expect(titulo).toHaveValue(DATOS.titulo);
    expect(screen.getByLabelText('Descripción')).toHaveValue(DATOS.descripcion);
    await user.clear(titulo);
    await user.type(titulo, 'Router AX55');
    await user.type(screen.getByLabelText('Descripción'), ' dual band');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(productosPropiosAPI.saveDatos).toHaveBeenCalledWith(70, {
      ...UNCHANGED,
      titulo: 'Router AX55',
      descripcion: 'Router WiFi 6 dual band',
    });
    expect(onSaved).toHaveBeenCalledWith(saved);
  });

  it('a blank description is saved as none', async () => {
    const user = userEvent.setup();
    productosPropiosAPI.saveDatos.mockResolvedValue({ data: {} });
    renderForm();

    await user.clear(screen.getByLabelText('Descripción'));
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(productosPropiosAPI.saveDatos).toHaveBeenCalledWith(70, { ...UNCHANGED, descripcion: null });
  });

  it('moves and removes pictures, and saves them in the new order', async () => {
    const user = userEvent.setup();
    productosPropiosAPI.saveDatos.mockResolvedValue({ data: {} });
    renderForm();

    expect(screen.getByRole('button', { name: 'Subir foto 1' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Bajar foto 3' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Subir foto 3' }));
    expect(pictureSources()).toEqual(['https://x/p1.webp', 'https://x/p3.webp', 'https://x/p2.webp']);
    await user.click(screen.getByRole('button', { name: 'Bajar foto 1' }));
    await user.click(screen.getByRole('button', { name: 'Quitar foto 3' }));
    expect(pictureSources()).toEqual(['https://x/p3.webp', 'https://x/p1.webp']);
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(productosPropiosAPI.saveDatos).toHaveBeenCalledWith(70, { ...UNCHANGED, fotos: ['P3', 'P1'] });
  });

  it('edits an attribute value and removes another', async () => {
    const user = userEvent.setup();
    productosPropiosAPI.saveDatos.mockResolvedValue({ data: {} });
    renderForm();

    const marca = screen.getByLabelText('Marca');
    await user.clear(marca);
    await user.type(marca, 'TP-LINK');
    await user.click(screen.getByRole('button', { name: 'Quitar Modelo' }));
    expect(screen.queryByLabelText('Modelo')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(productosPropiosAPI.saveDatos).toHaveBeenCalledWith(70, {
      ...UNCHANGED,
      atributos: [{ id: 'BRAND', value_name: 'TP-LINK' }],
    });
  });

  it('says when nothing is left to show', async () => {
    const user = userEvent.setup();
    renderForm({ ...DATOS, fotos: [DATOS.fotos[0]], atributos: [DATOS.atributos[0]] });

    await user.click(screen.getByRole('button', { name: 'Quitar foto 1' }));
    await user.click(screen.getByRole('button', { name: 'Quitar Marca' }));

    expect(screen.getByText('Sin fotos.')).toBeInTheDocument();
    expect(screen.getByText('Sin atributos.')).toBeInTheDocument();
  });

  it('locks the form while saving', async () => {
    const user = userEvent.setup();
    productosPropiosAPI.saveDatos.mockReturnValue(new Promise(() => {}));
    renderForm();

    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(screen.getByLabelText('Título')).toBeDisabled();
    expect(screen.getByLabelText('Marca')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Quitar foto 1' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled();
  });

  it('Cancelar leaves without saving', async () => {
    const user = userEvent.setup();
    const { onCancel } = renderForm();

    await user.type(screen.getByLabelText('Título'), ' X');
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));

    expect(onCancel).toHaveBeenCalled();
    expect(productosPropiosAPI.saveDatos).not.toHaveBeenCalled();
  });
});

describe('what cannot be saved', () => {
  it.each([
    ['Título', 'El título no puede quedar vacío.'],
    ['Marca', 'Completá el valor de Marca o quitalo.'],
  ])('a blank %s says so and sends nothing', async (label, message) => {
    const user = userEvent.setup();
    renderForm();

    await user.clear(screen.getByLabelText(label));
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(screen.getByRole('alert')).toHaveTextContent(message);
    expect(productosPropiosAPI.saveDatos).not.toHaveBeenCalled();
  });

  it('a copied picture ML gave no id cannot be kept: says so and sends nothing', async () => {
    const user = userEvent.setup();
    productosPropiosAPI.saveDatos.mockResolvedValue({ data: {} });
    renderForm({ ...DATOS, fotos: [DATOS.fotos[0], { id: null, url: 'https://x/sin-id.webp' }] });

    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(screen.getByRole('alert')).toHaveTextContent('La foto 2 vino de ML sin identificador y no se puede guardar: quitala.');
    expect(productosPropiosAPI.saveDatos).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Quitar foto 2' }));
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(productosPropiosAPI.saveDatos).toHaveBeenCalledWith(70, { ...UNCHANGED, fotos: ['P1'] });
  });

  it.each([
    [409, 'Elegí primero la publicación de la que se copian los datos.', 'Elegí primero la publicación de la que se copian los datos.'],
    [422, 'Fotos que no se copiaron de la publicación: P9.', 'Fotos que no se copiaron de la publicación: P9.'],
    [422, [{ msg: 'too long' }], 'Revisá los datos: el título y cada valor, hasta 255 caracteres.'],
    [403, undefined, 'No tenés permiso para editar los datos del producto.'],
    [500, undefined, 'No se pudieron guardar los datos. Probá de nuevo.'],
  ])('a %s keeps the form with what was typed and says why', async (status, detail, message) => {
    const user = userEvent.setup();
    productosPropiosAPI.saveDatos.mockRejectedValue(httpError(status, detail));
    const { onSaved } = renderForm();

    await user.type(screen.getByLabelText('Título'), ' X');
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.getByLabelText('Título')).toHaveValue(`${DATOS.titulo} X`);
    expect(screen.getByLabelText('Título')).toBeEnabled();
    expect(onSaved).not.toHaveBeenCalled();
  });
});
