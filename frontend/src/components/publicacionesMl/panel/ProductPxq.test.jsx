/**
 * The wholesale prices (PxQ tiers) of a product's publications (publicaciones-ml-paridad-productos S12b), as Productos'
 * publication tree shows them ("Precios mayoristas", `PxqPanel`): one entry per publication, opened on demand. Only
 * with `pxq.ver`, the permission `PxqPanel` reads with; editing tiers needs `pxq.escribir`, inside `PxqPanel`.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductPxq from './ProductPxq';

let granted = new Set(['pxq.ver']);
vi.mock('../../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

// The real PxqPanel has its own tests; here only which publication it opens and with which cache matter.
const caches = [];
vi.mock('../../promociones/PxqPanel', () => ({
  default: ({ itemId, pxqCacheRef }) => {
    caches.push(pxqCacheRef);
    return <div data-testid="pxq-panel">{`pxq of ${itemId}`}</div>;
  },
}));

const publication = (item_id, title = `Publicación ${item_id}`) => ({ item_id, title });
const PUBLICATIONS = [publication('MLA100', 'Router'), publication('MLA200', 'Router premium')];

const renderPxq = (publications = PUBLICATIONS) => render(<ProductPxq publications={publications} />);

beforeEach(() => {
  granted = new Set(['pxq.ver']);
  caches.length = 0;
});

describe('which publications', () => {
  it('lists every publication, each closed', () => {
    renderPxq();

    expect(screen.getByRole('heading', { name: 'Precios mayoristas' })).toBeInTheDocument();
    const toggles = screen.getAllByRole('button', { name: /Precios mayoristas de/ });
    expect(toggles.map((toggle) => toggle.getAttribute('aria-label'))).toEqual([
      'Precios mayoristas de MLA100',
      'Precios mayoristas de MLA200',
    ]);
    expect(toggles.every((toggle) => toggle.getAttribute('aria-expanded') === 'false')).toBe(true);
    expect(screen.queryByTestId('pxq-panel')).not.toBeInTheDocument();
  });

  it('shows nothing without publications', () => {
    const { container } = renderPxq([]);

    expect(container).toBeEmptyDOMElement();
  });
});

describe('opening a publication', () => {
  it("mounts that publication's wholesale prices, and closes again", async () => {
    const user = userEvent.setup();
    renderPxq();
    const toggle = screen.getByRole('button', { name: 'Precios mayoristas de MLA200' });

    await user.click(toggle);
    expect(screen.getByTestId('pxq-panel')).toHaveTextContent('pxq of MLA200');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    await user.click(toggle);
    expect(screen.queryByTestId('pxq-panel')).not.toBeInTheDocument();
  });

  it('keeps one cache for all its publications, so reopening one reads nothing again', async () => {
    const user = userEvent.setup();
    renderPxq();

    await user.click(screen.getByRole('button', { name: 'Precios mayoristas de MLA100' }));
    await user.click(screen.getByRole('button', { name: 'Precios mayoristas de MLA200' }));

    expect(screen.getAllByTestId('pxq-panel')).toHaveLength(2);
    expect(new Set(caches).size).toBe(1);
  });
});

describe('permission', () => {
  it('shows nothing without pxq.ver', () => {
    granted = new Set();

    const { container } = renderPxq();

    expect(container).toBeEmptyDOMElement();
  });
});
