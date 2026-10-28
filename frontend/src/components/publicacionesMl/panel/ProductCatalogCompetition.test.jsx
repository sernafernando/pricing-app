/**
 * The catalog competition of a product's publications (publicaciones-ml-paridad-productos S12b), as Productos'
 * publication tree shows it ("Competencia catálogo", `GET /promociones/catalogo-competencia/{mla}`): one entry per
 * catalog publication, opened on demand. Only with `promos.ver`, the permission that endpoint requires; refreshing
 * needs `promos.escribir`, as in Productos.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductCatalogCompetition from './ProductCatalogCompetition';
import { promocionesAPI } from '../../../services/api';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  promocionesAPI: { getCompetenciaCatalogo: vi.fn(), refreshCompetenciaCatalogo: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

let granted = new Set(['promos.ver']);
vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

const publication = (item_id, catalog_listing, title = `Publicación ${item_id}`) => ({ item_id, catalog_listing, title });

const PUBLICATIONS = [
  publication('MLA100', true, 'Router catálogo'),
  publication('MLA200', false, 'Router tradicional'),
  publication('MLA300', true, 'Router catálogo premium'),
];

const snapshot = {
  fetch_status: 'ok',
  fecha_consulta: '2026-10-27T15:00:00Z',
  our_price: 50000,
  competitor_count: 1,
  undercutting: [{ item_id: 'MLA999', seller_nickname: 'COMPETIDOR SA', price: 48000, markup: 12.34 }],
};

const renderCompetition = (publications = PUBLICATIONS) => render(<ProductCatalogCompetition publications={publications} />);

beforeEach(() => {
  granted = new Set(['promos.ver']);
  promocionesAPI.getCompetenciaCatalogo.mockReset();
  promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({ data: snapshot });
  promocionesAPI.refreshCompetenciaCatalogo.mockReset();
});

describe('which publications', () => {
  it('lists only the catalog publications, each closed, without reading anything yet', () => {
    renderCompetition();

    expect(screen.getByRole('heading', { name: 'Competencia de catálogo' })).toBeInTheDocument();
    const toggles = screen.getAllByRole('button', { name: /Competencia de catálogo de/ });
    expect(toggles.map((toggle) => toggle.getAttribute('aria-label'))).toEqual([
      'Competencia de catálogo de MLA100',
      'Competencia de catálogo de MLA300',
    ]);
    expect(toggles.every((toggle) => toggle.getAttribute('aria-expanded') === 'false')).toBe(true);
    expect(screen.queryByText('Router tradicional')).not.toBeInTheDocument();
    expect(promocionesAPI.getCompetenciaCatalogo).not.toHaveBeenCalled();
  });

  it('shows nothing when no publication is in a catalog', () => {
    const { container } = renderCompetition([publication('MLA200', false)]);

    expect(container).toBeEmptyDOMElement();
  });
});

describe('opening a publication', () => {
  it('reads its stored snapshot and shows the cheaper competitors with the markup if matched', async () => {
    const user = userEvent.setup();
    renderCompetition();

    await user.click(screen.getByRole('button', { name: 'Competencia de catálogo de MLA100' }));

    expect(await screen.findByText('COMPETIDOR SA')).toBeInTheDocument();
    expect(screen.getByText('Tu markup si igualás: 12.3%')).toBeInTheDocument();
    expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalledWith('MLA100');
    expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('button', { name: 'Competencia de catálogo de MLA100' })).toHaveAttribute('aria-expanded', 'true');
  });

  it('closes again, and reopening uses what it already read', async () => {
    const user = userEvent.setup();
    renderCompetition();
    const toggle = screen.getByRole('button', { name: 'Competencia de catálogo de MLA100' });

    await user.click(toggle);
    await screen.findByText('COMPETIDOR SA');
    await user.click(toggle);
    expect(screen.queryByText('COMPETIDOR SA')).not.toBeInTheDocument();
    await user.click(toggle);

    expect(await screen.findByText('COMPETIDOR SA')).toBeInTheDocument();
    expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalledTimes(1);
  });

  it('offers no refresh without promos.escribir', async () => {
    const user = userEvent.setup();
    renderCompetition();

    await user.click(screen.getByRole('button', { name: 'Competencia de catálogo de MLA100' }));
    await screen.findByText('COMPETIDOR SA');

    expect(screen.queryByRole('button', { name: 'Refrescar competencia de catálogo de MLA100' })).not.toBeInTheDocument();
  });

  it('refreshes one publication with promos.escribir and shows the new snapshot', async () => {
    granted = new Set(['promos.ver', 'promos.escribir']);
    promocionesAPI.refreshCompetenciaCatalogo.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderCompetition();

    await user.click(screen.getByRole('button', { name: 'Competencia de catálogo de MLA100' }));
    await screen.findByText('COMPETIDOR SA');
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: { ...snapshot, undercutting: [{ item_id: 'MLA998', seller_nickname: 'OTRO VENDEDOR', price: 47000, markup: 9 }] },
    });
    await user.click(screen.getByRole('button', { name: 'Refrescar competencia de catálogo de MLA100' }));

    expect(await screen.findByText('OTRO VENDEDOR')).toBeInTheDocument();
    expect(promocionesAPI.refreshCompetenciaCatalogo).toHaveBeenCalledWith('MLA100');
  });
});

describe('permission', () => {
  it('shows nothing and reads nothing without promos.ver', () => {
    granted = new Set();

    const { container } = renderCompetition();

    expect(container).toBeEmptyDOMElement();
    expect(promocionesAPI.getCompetenciaCatalogo).not.toHaveBeenCalled();
  });
});
