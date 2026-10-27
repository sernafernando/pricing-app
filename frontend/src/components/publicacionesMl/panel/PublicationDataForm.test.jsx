/**
 * Editing a publication's override (publicaciones-ml-producto-propio T8b): the form starts from the data that applies
 * and saves, field by field, only what differs from ML's original (an unchanged field follows ML). Never writes ML.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PublicationDataForm from './PublicationDataForm';
import { mlItemOverridesAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  mlItemOverridesAPI: { get: vi.fn(), save: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

// The app's error envelope: a reason in words comes as `error.message`.
const httpError = (status, message) =>
  Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { error: { code: 'error', message } } } });

const ORIGINAL = {
  titulo: 'Router TP-Link Archer AX55',
  descripcion: 'Router WiFi 6',
  fotos: [
    { id: 'P1', url: 'https://x/p1.webp' },
    { id: 'P2', url: 'https://x/p2.webp' },
  ],
  atributos: [
    { id: 'BRAND', name: 'Marca', value_name: 'TP-Link' },
    { id: 'MODEL', name: 'Modelo', value_name: 'Archer AX55' },
  ],
};

const FOLLOWS_ML = { titulo: null, descripcion: null, fotos: null, atributos: null };

const renderForm = (aplicado = ORIGINAL) => {
  const onSaved = vi.fn();
  const onCancel = vi.fn();
  render(<PublicationDataForm itemId="MLA1" aplicado={aplicado} original={ORIGINAL} onSaved={onSaved} onCancel={onCancel} />);
  return { onSaved, onCancel };
};

const save = () => userEvent.click(screen.getByRole('button', { name: 'Guardar' }));

beforeEach(() => {
  mlItemOverridesAPI.save.mockReset();
  mlItemOverridesAPI.save.mockResolvedValue({ data: { item_id: 'MLA1' } });
});

describe('what is saved', () => {
  it('a changed title is the only overridden field; the rest follows ML', async () => {
    const { onSaved } = renderForm();
    const title = screen.getByLabelText('Título');
    await userEvent.clear(title);
    await userEvent.type(title, 'Router Archer AX55');
    await save();

    expect(mlItemOverridesAPI.save).toHaveBeenCalledWith('MLA1', { ...FOLLOWS_ML, titulo: 'Router Archer AX55' });
    expect(onSaved).toHaveBeenCalledWith({ item_id: 'MLA1' });
  });

  it('a removed picture overrides the pictures with the ones kept, in order', async () => {
    renderForm();
    await userEvent.click(screen.getByRole('button', { name: 'Quitar foto 1' }));
    await save();

    expect(mlItemOverridesAPI.save).toHaveBeenCalledWith('MLA1', { ...FOLLOWS_ML, fotos: ['P2'] });
  });

  it('an edited attribute overrides the attributes whole', async () => {
    renderForm();
    const model = screen.getByLabelText('Modelo');
    await userEvent.clear(model);
    await userEvent.type(model, 'AX55 Pro');
    await save();

    expect(mlItemOverridesAPI.save).toHaveBeenCalledWith('MLA1', {
      ...FOLLOWS_ML,
      atributos: [
        { id: 'BRAND', value_name: 'TP-Link' },
        { id: 'MODEL', value_name: 'AX55 Pro' },
      ],
    });
  });

  it('a cleared description overrides ML with none', async () => {
    renderForm();
    await userEvent.clear(screen.getByLabelText('Descripción'));
    await save();

    expect(mlItemOverridesAPI.save).toHaveBeenCalledWith('MLA1', { ...FOLLOWS_ML, descripcion: '' });
  });

  it('starts from the applied data, and keeps what is still overridden', async () => {
    renderForm({ ...ORIGINAL, titulo: 'Router Archer AX55', fotos: [ORIGINAL.fotos[1]] });

    expect(screen.getByLabelText('Título')).toHaveValue('Router Archer AX55');
    expect(screen.getAllByRole('img')).toHaveLength(1);
    await save();

    expect(mlItemOverridesAPI.save).toHaveBeenCalledWith('MLA1', { ...FOLLOWS_ML, titulo: 'Router Archer AX55', fotos: ['P2'] });
  });

  it('"Volver al original" puts back ML data, and saving it drops the override', async () => {
    renderForm({ ...ORIGINAL, titulo: 'Router Archer AX55', fotos: [ORIGINAL.fotos[1]] });
    await userEvent.click(screen.getByRole('button', { name: 'Volver al original' }));

    expect(screen.getByLabelText('Título')).toHaveValue(ORIGINAL.titulo);
    expect(screen.getAllByRole('img')).toHaveLength(2);
    await save();

    expect(mlItemOverridesAPI.save).toHaveBeenCalledWith('MLA1', FOLLOWS_ML);
  });
});

describe('what is refused', () => {
  it('a blank title is not sent', async () => {
    renderForm();
    await userEvent.clear(screen.getByLabelText('Título'));
    await save();

    expect(screen.getByRole('alert')).toHaveTextContent('El título no puede quedar vacío.');
    expect(mlItemOverridesAPI.save).not.toHaveBeenCalled();
  });

  it("shows the server's reason for a 409 and stays open", async () => {
    mlItemOverridesAPI.save.mockRejectedValue(httpError(409, 'La publicación MLA1 está eliminada: no se puede editar.'));
    const { onSaved } = renderForm();
    await save();

    expect(await screen.findByRole('alert')).toHaveTextContent('La publicación MLA1 está eliminada: no se puede editar.');
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeEnabled();
  });

  it('a 403 names the publication permission', async () => {
    mlItemOverridesAPI.save.mockRejectedValue(httpError(403, 'forbidden'));
    renderForm();
    await save();

    expect(await screen.findByRole('alert')).toHaveTextContent('No tenés permiso para editar los datos de la publicación.');
  });

  it('Cancelar sends nothing', async () => {
    const { onCancel } = renderForm();
    await userEvent.click(screen.getByRole('button', { name: 'Cancelar' }));

    expect(onCancel).toHaveBeenCalled();
    expect(mlItemOverridesAPI.save).not.toHaveBeenCalled();
  });
});
