/**
 * A publication's data in its panel (publicaciones-ml-producto-propio T8b): the data that applies and, when someone
 * overrode it here, the original ML has beside it. The override never changes ML.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DatosTab from './DatosTab';
import { mlItemOverridesAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  mlItemOverridesAPI: { get: vi.fn(), save: vi.fn(), pushToMl: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const ORIGINAL = {
  titulo: 'Router TP-Link Archer AX55',
  descripcion: 'Router WiFi 6',
  fotos: [
    { id: 'P1', url: 'https://x/p1.webp' },
    { id: 'P2', url: 'https://x/p2.webp' },
  ],
  atributos: [{ id: 'BRAND', name: 'Marca', value_name: 'TP-Link' }],
};

const read = (overrides = {}) => ({
  item_id: 'MLA1',
  original: ORIGINAL,
  override: null,
  aplicado: ORIGINAL,
  editable: true,
  updated_at: null,
  can_edit: false,
  ...overrides,
});

const OVERRIDDEN = read({
  override: { titulo: 'Router Archer AX55 WiFi 6', descripcion: null, fotos: [{ id: 'P2', url: 'https://x/p2.webp' }], atributos: null },
  aplicado: { ...ORIGINAL, titulo: 'Router Archer AX55 WiFi 6', fotos: [{ id: 'P2', url: 'https://x/p2.webp' }] },
  updated_at: '2026-10-27T15:00:00Z',
});

const region = (name) => screen.getByRole('region', { name });

beforeEach(() => {
  mlItemOverridesAPI.get.mockReset();
  mlItemOverridesAPI.save.mockReset();
});

describe('reading', () => {
  it('asks the server for the publication it was opened on', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: read() });
    render(<DatosTab itemId="MLA1" />);

    await screen.findByRole('region', { name: 'Datos de la publicación' });
    expect(mlItemOverridesAPI.get).toHaveBeenCalledWith('MLA1');
  });

  it('without an override shows ML data once and says nothing was overridden', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: read() });
    render(<DatosTab itemId="MLA1" />);

    const datos = await screen.findByRole('region', { name: 'Datos de la publicación' });
    expect(within(datos).getByText('Sin cambios locales: se usan los datos de Mercado Libre.')).toBeInTheDocument();
    expect(within(datos).getByText('Router TP-Link Archer AX55')).toBeInTheDocument();
    expect(within(datos).getByText('Router WiFi 6')).toBeInTheDocument();
    expect(within(datos).getAllByRole('img').map((img) => img.getAttribute('src'))).toEqual(['https://x/p1.webp', 'https://x/p2.webp']);
    expect(within(datos).getByText('TP-Link')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Original en Mercado Libre' })).not.toBeInTheDocument();
  });

  it('with an override shows the applied data, which fields were overridden, and the original beside it', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: OVERRIDDEN });
    render(<DatosTab itemId="MLA1" />);

    const aplicado = await screen.findByRole('region', { name: 'Datos que se usan' });
    expect(within(aplicado).getByText(/Sobrescritos el .*: título y fotos\. No se cambian en Mercado Libre\./)).toBeInTheDocument();
    expect(within(aplicado).getByText('Router Archer AX55 WiFi 6')).toBeInTheDocument();
    expect(within(aplicado).getAllByRole('img').map((img) => img.getAttribute('src'))).toEqual(['https://x/p2.webp']);
    // A field that follows ML shows ML's value in the applied data too.
    expect(within(aplicado).getByText('Router WiFi 6')).toBeInTheDocument();

    const original = region('Original en Mercado Libre');
    expect(within(original).getByText('Router TP-Link Archer AX55')).toBeInTheDocument();
    expect(within(original).getAllByRole('img')).toHaveLength(2);
  });

  it('an override with a blank description reads as no description in the applied data', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({
      data: read({ override: { titulo: null, descripcion: '', fotos: null, atributos: null }, aplicado: { ...ORIGINAL, descripcion: null } }),
    });
    render(<DatosTab itemId="MLA1" />);

    const aplicado = await screen.findByRole('region', { name: 'Datos que se usan' });
    expect(within(aplicado).getByText(/: descripción\./)).toBeInTheDocument();
    expect(within(aplicado).getByText('Sin descripción.')).toBeInTheDocument();
    expect(within(region('Original en Mercado Libre')).getByText('Router WiFi 6')).toBeInTheDocument();
  });

  it('selecting another publication never shows the previous one while it loads', async () => {
    mlItemOverridesAPI.get.mockResolvedValueOnce({ data: read() }).mockReturnValueOnce(new Promise(() => {}));
    const { rerender } = render(<DatosTab itemId="MLA1" />);
    await screen.findByText('Router TP-Link Archer AX55');

    rerender(<DatosTab itemId="MLA2" />);

    expect(screen.getByText('Cargando datos…')).toBeInTheDocument();
    expect(screen.queryByText('Router TP-Link Archer AX55')).not.toBeInTheDocument();
    expect(mlItemOverridesAPI.get).toHaveBeenLastCalledWith('MLA2');
  });

  it('a failed read does not stick: back on that publication, a good read shows its data', async () => {
    mlItemOverridesAPI.get
      .mockRejectedValueOnce(new Error('HTTP 500'))
      .mockResolvedValueOnce({ data: read({ item_id: 'MLA2' }) })
      .mockResolvedValueOnce({ data: read() });
    const { rerender } = render(<DatosTab itemId="MLA1" />);
    await screen.findByRole('alert');

    rerender(<DatosTab itemId="MLA2" />);
    await screen.findByText('Router TP-Link Archer AX55');
    rerender(<DatosTab itemId="MLA1" />);

    await screen.findByText('Router TP-Link Archer AX55');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says so while loading', () => {
    mlItemOverridesAPI.get.mockReturnValue(new Promise(() => {}));
    render(<DatosTab itemId="MLA1" />);

    expect(screen.getByText('Cargando datos…')).toBeInTheDocument();
  });

  it('a failed read says so and Reintentar reads again', async () => {
    mlItemOverridesAPI.get.mockRejectedValueOnce(new Error('HTTP 500')).mockResolvedValueOnce({ data: read() });
    render(<DatosTab itemId="MLA1" />);

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los datos de la publicación.');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));

    await screen.findByRole('region', { name: 'Datos de la publicación' });
    expect(mlItemOverridesAPI.get).toHaveBeenCalledTimes(2);
  });
});

describe('editing', () => {
  it('without the permission offers no edit', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: read() });
    render(<DatosTab itemId="MLA1" />);

    await screen.findByRole('region', { name: 'Datos de la publicación' });
    expect(screen.queryByRole('button', { name: 'Editar datos' })).not.toBeInTheDocument();
  });

  it('a deleted publication says it cannot be edited', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: read({ can_edit: true, editable: false }) });
    render(<DatosTab itemId="MLA1" />);

    expect(await screen.findByText('La publicación está eliminada: sus datos no se pueden editar.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Editar datos' })).not.toBeInTheDocument();
  });

  it('Editar datos opens the form on the applied data; saving shows what the server answered', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: read({ can_edit: true }) });
    mlItemOverridesAPI.save.mockResolvedValue({ data: { ...OVERRIDDEN, can_edit: true } });
    render(<DatosTab itemId="MLA1" />);

    await userEvent.click(await screen.findByRole('button', { name: 'Editar datos' }));
    const title = screen.getByLabelText('Título');
    await userEvent.clear(title);
    await userEvent.type(title, 'Router Archer AX55 WiFi 6');
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(mlItemOverridesAPI.save).toHaveBeenCalledWith('MLA1', { titulo: 'Router Archer AX55 WiFi 6', descripcion: null, fotos: null, atributos: null });
    const aplicado = await screen.findByRole('region', { name: 'Datos que se usan' });
    expect(within(aplicado).getByText('Router Archer AX55 WiFi 6')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Guardado. No se cambió nada en Mercado Libre.');
  });

  it('Cancelar closes the form and keeps the data', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: read({ can_edit: true }) });
    render(<DatosTab itemId="MLA1" />);

    await userEvent.click(await screen.findByRole('button', { name: 'Editar datos' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancelar' }));

    expect(screen.queryByLabelText('Título')).not.toBeInTheDocument();
    expect(screen.getByText('Router TP-Link Archer AX55')).toBeInTheDocument();
    expect(mlItemOverridesAPI.save).not.toHaveBeenCalled();
  });
});

describe('Actualizar en ML', () => {
  it('is offered only for an override the user may edit', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: read({ can_edit: true }) });
    const { unmount } = render(<DatosTab itemId="MLA1" />);
    await screen.findByRole('button', { name: 'Editar datos' });
    expect(screen.queryByRole('button', { name: 'Actualizar en ML' })).not.toBeInTheDocument();
    unmount();

    mlItemOverridesAPI.get.mockResolvedValue({ data: OVERRIDDEN });
    const second = render(<DatosTab itemId="MLA1" />);
    await screen.findByRole('region', { name: 'Datos que se usan' });
    expect(screen.queryByRole('button', { name: 'Actualizar en ML' })).not.toBeInTheDocument();
    second.unmount();

    mlItemOverridesAPI.get.mockResolvedValue({ data: { ...OVERRIDDEN, can_edit: true } });
    render(<DatosTab itemId="MLA1" />);
    expect(await screen.findByRole('button', { name: 'Actualizar en ML' })).toBeInTheDocument();
  });

  it('after a push that may have landed, reads the publication again', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: { ...OVERRIDDEN, can_edit: true } });
    mlItemOverridesAPI.pushToMl.mockResolvedValue({ data: { status: 'sent', message: null, partes: [{ campo: 'titulo', estado: 'submitted', motivo: null }] } });
    render(<DatosTab itemId="MLA1" />);

    await userEvent.click(await screen.findByRole('button', { name: 'Actualizar en ML' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirmar' }));

    await screen.findByText('Título: enviado a Mercado Libre.');
    expect(mlItemOverridesAPI.get).toHaveBeenCalledTimes(2);
    // The result outlives the re-read.
    expect(screen.getByText('Título: enviado a Mercado Libre.')).toBeInTheDocument();
  });

  it('the result stays when the re-read finds the override gone, and the button goes', async () => {
    mlItemOverridesAPI.get.mockResolvedValueOnce({ data: { ...OVERRIDDEN, can_edit: true } }).mockResolvedValueOnce({ data: read({ can_edit: true }) });
    mlItemOverridesAPI.pushToMl.mockResolvedValue({ data: { status: 'sent', message: null, partes: [{ campo: 'titulo', estado: 'submitted', motivo: null }] } });
    render(<DatosTab itemId="MLA1" />);

    await userEvent.click(await screen.findByRole('button', { name: 'Actualizar en ML' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirmar' }));

    await screen.findByText('Sin cambios locales: se usan los datos de Mercado Libre.');
    expect(screen.getByText('Título: enviado a Mercado Libre.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Actualizar en ML' })).not.toBeInTheDocument();
  });

  it('saving an edit clears an earlier push result', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: { ...OVERRIDDEN, can_edit: true } });
    mlItemOverridesAPI.pushToMl.mockResolvedValue({ data: { status: 'sent', message: null, partes: [{ campo: 'titulo', estado: 'submitted', motivo: null }] } });
    mlItemOverridesAPI.save.mockResolvedValue({ data: { ...OVERRIDDEN, can_edit: true } });
    render(<DatosTab itemId="MLA1" />);

    await userEvent.click(await screen.findByRole('button', { name: 'Actualizar en ML' }));
    await userEvent.click(screen.getByRole('button', { name: 'Confirmar' }));
    await screen.findByText('Título: enviado a Mercado Libre.');
    await userEvent.click(screen.getByRole('button', { name: 'Editar datos' }));
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));

    await screen.findByText('Guardado. No se cambió nada en Mercado Libre.');
    expect(screen.queryByText('Título: enviado a Mercado Libre.')).not.toBeInTheDocument();
  });

  it('the confirmation warns about pictures only when the override has them', async () => {
    mlItemOverridesAPI.get.mockResolvedValue({ data: { ...OVERRIDDEN, can_edit: true } });
    render(<DatosTab itemId="MLA1" />);

    await userEvent.click(await screen.findByRole('button', { name: 'Actualizar en ML' }));

    expect(screen.getByText(/Las fotos se reemplazan por la lista guardada/)).toBeInTheDocument();
  });
});
