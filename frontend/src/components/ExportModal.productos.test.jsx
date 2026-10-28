import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ExportModal from './ExportModal';
import api from '../services/api';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true }),
}));

vi.mock('../services/api', () => ({
  default: {
    get: vi.fn(async (url) => (url.startsWith('/tipo-cambio') ? { data: { venta: 1000 } } : { data: 'xlsx' })),
    post: vi.fn(async () => ({ data: 'xlsx' })),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  window.URL.createObjectURL = vi.fn(() => 'blob:x');
  window.URL.revokeObjectURL = vi.fn();
  seedTiendasOficiales([]);
});

afterAll(resetTiendasOficiales);

// Publicaciones ML hands the modal the products its own filters select: every kind exports exactly those.
const renderConConjunto = (resolverProductos, showToast = vi.fn()) =>
  render(
    <ExportModal
      onClose={() => {}}
      filtrosActivos={{}}
      showToast={showToast}
      resolverProductos={resolverProductos}
      descripcionConjunto="Los productos de las publicaciones filtradas."
    />,
  );

const exportar = async (tab, boton) => {
  await userEvent.click(await screen.findByRole('button', { name: tab }));
  await userEvent.click(screen.getByRole('button', { name: boton }));
};

describe('ExportModal with an explicit product set', () => {
  it.each([
    ['Vista Actual', 'Exportar Vista Actual', '/exportar-vista-actual?'],
    ['Web Transferencia', 'Exportar Excel', '/exportar-web-transferencia?'],
    ['Clásica', 'Exportar Excel', '/exportar-clasica?'],
    ['PVP', 'Exportar PVP', '/exportar-clasica?'],
  ])('%s posts the resolved products, without the Productos filters', async (tab, boton, path) => {
    renderConConjunto(async () => [5, 7]);

    await exportar(tab, boton);

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    const [url, body, config] = api.post.mock.calls[0];
    expect(url.startsWith(path)).toBe(true);
    expect(body).toEqual({ item_ids: [5, 7] });
    expect(config).toEqual({ responseType: 'blob' });
    expect(api.get).not.toHaveBeenCalledWith(expect.stringMatching(/^\/exportar/), expect.anything());
  });

  it('Rebate sends the resolved products instead of filtros', async () => {
    renderConConjunto(async () => [5, 7]);

    await exportar('Rebate ML', 'Exportar Rebate');

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    const [url, body] = api.post.mock.calls[0];
    expect(url).toBe('/productos/exportar-rebate');
    expect(body.item_ids).toEqual([5, 7]);
    expect(body).not.toHaveProperty('filtros');
  });

  it('shows what it exports instead of the Productos filter checkbox', async () => {
    renderConConjunto(async () => [5]);

    expect(await screen.findByText('Los productos de las publicaciones filtradas.')).toBeInTheDocument();
    expect(screen.queryByText('Exportar solo productos filtrados')).not.toBeInTheDocument();
  });

  it("shows the resolver's own error and exports nothing", async () => {
    const showToast = vi.fn();
    renderConConjunto(async () => {
      throw new Error('El filtro selecciona 12000 productos; una exportación admite hasta 10000.');
    }, showToast);

    await exportar('Vista Actual', 'Exportar Vista Actual');

    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith('El filtro selecciona 12000 productos; una exportación admite hasta 10000.', 'error'),
    );
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe('ExportModal without a product set (Productos)', () => {
  it('still asks the export by GET with the filters', async () => {
    render(<ExportModal onClose={() => {}} filtrosActivos={{ search: 'abc' }} showToast={() => {}} />);

    await exportar('Vista Actual', 'Exportar Vista Actual');

    await waitFor(() =>
      expect(api.get).toHaveBeenCalledWith('/exportar-vista-actual?page=1&page_size=10000&search=abc', { responseType: 'blob' }),
    );
    expect(api.post).not.toHaveBeenCalled();
  });
});
