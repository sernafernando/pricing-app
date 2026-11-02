/**
 * PaintColorMenu (S8): paints the checked rows on the layer on show, behind Productos' own rule. A checked product
 * row paints its product with Productos' batch endpoint (`POST /productos/actualizar-color-lote`, `equipo_id` in the
 * body); a checked publication paints only itself (`PUT /ml-publications/colors`, seleccion-por-publicacion S3).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PaintColorMenu from './PaintColorMenu';
import api, { publicacionesMlAPI } from '../../services/api';

vi.mock('../../services/api', () => ({ default: { post: vi.fn() }, publicacionesMlAPI: { paintColors: vi.fn() } }));

let granted = new Set();
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

const products = (...productIds) => ({ itemIds: [], productIds });
const publications = (...itemIds) => ({ itemIds, productIds: [] });

const setup = (props = {}) => {
  const onPainted = vi.fn();
  const onPaintedOwn = vi.fn();
  const onClearChecked = vi.fn();
  render(
    <PaintColorMenu
      checked={products(77, 78)}
      equipo=""
      onPainted={onPainted}
      onPaintedOwn={onPaintedOwn}
      onClearChecked={onClearChecked}
      {...props}
    />,
  );
  return { onPainted, onPaintedOwn, onClearChecked, user: userEvent.setup() };
};

beforeEach(() => {
  vi.clearAllMocks();
  granted = new Set(['productos.marcar_color', 'productos.marcar_color_lote']);
  api.post.mockResolvedValue({ data: { count: 2 } });
  publicacionesMlAPI.paintColors.mockResolvedValue({ data: { count: 1 } });
});

describe('PaintColorMenu', () => {
  it('is not there without checked products', () => {
    setup({ checked: products() });
    expect(screen.queryByRole('button', { name: /pintar/i })).not.toBeInTheDocument();
  });

  // S12d: the selection outlives a filter change, so it may hold products the list no longer shows.
  it('says how many checked rows are not on the page, in its menu', async () => {
    const { user } = setup({ offPageCount: 1 });
    await user.click(screen.getByRole('button', { name: 'Pintar 2 productos' }));
    expect(screen.getByText('1 fila marcada no está en esta página')).toBeInTheDocument();
  });

  it('on the global layer, only with productos.marcar_color_lote; on a team layer, for its members (every team listed)', () => {
    granted = new Set();
    const { unmount } = render(<PaintColorMenu checked={products(77)} equipo="" onPainted={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /pintar/i })).not.toBeInTheDocument();
    unmount();
    render(<PaintColorMenu checked={products(77)} equipo="12" onPainted={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Pintar 1 producto' })).toBeInTheDocument();
  });

  it('paints the checked products on the global layer, reports it and clears the selection', async () => {
    const { onPainted, onClearChecked, user } = setup();
    await user.click(screen.getByRole('button', { name: 'Pintar 2 productos' }));
    await user.click(screen.getByRole('menuitem', { name: 'Urgente' }));
    expect(api.post).toHaveBeenCalledWith('/productos/actualizar-color-lote', { item_ids: [77, 78], color: 'rojo' });
    expect(onPainted).toHaveBeenCalledWith({ data: { vista: 'ml', is_global: true, equipo_id: null, item_ids: [77, 78], color: 'rojo' } });
    expect(onClearChecked).toHaveBeenCalled();
  });

  it("paints on the team layer on show and can clear the color", async () => {
    const { onPainted, user } = setup({ equipo: '12' });
    await user.click(screen.getByRole('button', { name: 'Pintar 2 productos' }));
    await user.click(screen.getByRole('menuitem', { name: 'Sin color' }));
    expect(api.post).toHaveBeenCalledWith('/productos/actualizar-color-lote', { item_ids: [77, 78], color: null, equipo_id: 12 });
    expect(onPainted).toHaveBeenCalledWith({ data: { vista: 'ml', is_global: false, equipo_id: 12, item_ids: [77, 78], color: null } });
  });

  it("says why when it fails, and keeps the selection and the rows as they were", async () => {
    api.post.mockRejectedValue(Object.assign(new Error('HTTP 403'), { response: { status: 403, data: { detail: 'No tienes permiso para marcar colores en lote' } } }));
    const { onPainted, onClearChecked, user } = setup();
    await user.click(screen.getByRole('button', { name: 'Pintar 2 productos' }));
    await user.click(screen.getByRole('menuitem', { name: 'Urgente' }));
    expect(await screen.findByText('No tienes permiso para marcar colores en lote')).toBeInTheDocument();
    expect(onPainted).not.toHaveBeenCalled();
    expect(onClearChecked).not.toHaveBeenCalled();
  });

  it('works from the keyboard: focus on the first color, arrows move, Escape goes back to the button', async () => {
    const { user } = setup();
    const trigger = screen.getByRole('button', { name: 'Pintar 2 productos' });
    trigger.focus();
    await user.keyboard('{Enter}');
    const items = screen.getAllByRole('menuitem');
    expect(items[0]).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(items[1]).toHaveFocus();
    await user.keyboard('{ArrowUp}{ArrowUp}');
    expect(items.at(-1)).toHaveFocus();
    await user.keyboard('{Home}');
    expect(items[0]).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  describe('checked publications (seleccion-por-publicacion S3)', () => {
    it('paints only the checked publications, never their products, and reports them by MLA', async () => {
      const { onPainted, onPaintedOwn, onClearChecked, user } = setup({ checked: publications('MLA1', 'MLA4') });
      await user.click(screen.getByRole('button', { name: 'Pintar 2 publicaciones' }));
      await user.click(screen.getByRole('menuitem', { name: 'Urgente' }));
      expect(publicacionesMlAPI.paintColors).toHaveBeenCalledWith({ item_ids: ['MLA1', 'MLA4'], color: 'rojo' });
      expect(api.post).not.toHaveBeenCalled();
      expect(onPaintedOwn).toHaveBeenCalledWith({ data: { is_global: true, equipo_id: null, item_ids: ['MLA1', 'MLA4'], color: 'rojo' } });
      expect(onPainted).not.toHaveBeenCalled();
      expect(onClearChecked).toHaveBeenCalled();
    });

    it("on a team layer; Sin color takes the publication's own color off (it shows its product's again)", async () => {
      const { onPaintedOwn, user } = setup({ checked: publications('MLA1'), equipo: '12' });
      await user.click(screen.getByRole('button', { name: 'Pintar 1 publicación' }));
      await user.click(screen.getByRole('menuitem', { name: 'Sin color' }));
      expect(publicacionesMlAPI.paintColors).toHaveBeenCalledWith({ item_ids: ['MLA1'], color: null, equipo_id: 12 });
      expect(onPaintedOwn).toHaveBeenCalledWith({ data: { is_global: false, equipo_id: 12, item_ids: ['MLA1'], color: null } });
    });

    it('a product row and a publication checked together each paint as what they are', async () => {
      const { onPainted, onPaintedOwn, user } = setup({ checked: { itemIds: ['MLA9'], productIds: [77] } });
      await user.click(screen.getByRole('button', { name: 'Pintar 2 filas' }));
      await user.click(screen.getByRole('menuitem', { name: 'Urgente' }));
      expect(publicacionesMlAPI.paintColors).toHaveBeenCalledWith({ item_ids: ['MLA9'], color: 'rojo' });
      expect(api.post).toHaveBeenCalledWith('/productos/actualizar-color-lote', { item_ids: [77], color: 'rojo' });
      expect(onPaintedOwn).toHaveBeenCalledTimes(1);
      expect(onPainted).toHaveBeenCalledWith({ data: { vista: 'ml', is_global: true, equipo_id: null, item_ids: [77], color: 'rojo' } });
    });

    it('sends more than 500 publications in batches of 500, each one shown as it lands', async () => {
      const many = Array.from({ length: 501 }, (_, i) => `MLA${1000 + i}`);
      const { onPaintedOwn, user } = setup({ checked: publications(...many) });
      await user.click(screen.getByRole('button', { name: 'Pintar 501 publicaciones' }));
      await user.click(screen.getByRole('menuitem', { name: 'Urgente' }));
      expect(publicacionesMlAPI.paintColors.mock.calls.map(([body]) => body.item_ids.length)).toEqual([500, 1]);
      expect(onPaintedOwn).toHaveBeenCalledTimes(2);
    });

    it('stops at a failed batch: what landed stays shown, the rest and the selection stay as they were', async () => {
      publicacionesMlAPI.paintColors.mockResolvedValueOnce({ data: {} }).mockRejectedValueOnce(new Error('caído'));
      const many = Array.from({ length: 501 }, (_, i) => `MLA${1000 + i}`);
      const { onPainted, onPaintedOwn, onClearChecked, user } = setup({ checked: { itemIds: many, productIds: [77] } });
      await user.click(screen.getByRole('button', { name: 'Pintar 502 filas' }));
      await user.click(screen.getByRole('menuitem', { name: 'Urgente' }));
      expect(await screen.findByText('No se pudieron pintar las publicaciones')).toBeInTheDocument();
      expect(onPaintedOwn).toHaveBeenCalledTimes(1);
      expect(api.post).not.toHaveBeenCalled();
      expect(onPainted).not.toHaveBeenCalled();
      expect(onClearChecked).not.toHaveBeenCalled();
    });

    it('on the global layer one publication needs productos.marcar_color, several productos.marcar_color_lote', () => {
      granted = new Set(['productos.marcar_color']);
      const { unmount } = render(<PaintColorMenu checked={publications('MLA1')} equipo="" onPainted={vi.fn()} />);
      expect(screen.getByRole('button', { name: 'Pintar 1 publicación' })).toBeInTheDocument();
      unmount();
      render(<PaintColorMenu checked={publications('MLA1', 'MLA2')} equipo="" onPainted={vi.fn()} />);
      expect(screen.queryByRole('button', { name: /pintar/i })).not.toBeInTheDocument();
    });

    // The backend's rule (`puede_escribir_layer`, `_puede_escribir_layer_lote`): every write of publications needs
    // productos.marcar_color, several of them productos.marcar_color_lote too; products alone keep Productos' batch rule.
    it('with only productos.marcar_color_lote, no publication can be painted on the global layer, products can', () => {
      granted = new Set(['productos.marcar_color_lote']);
      const { unmount } = render(<PaintColorMenu checked={publications('MLA1')} equipo="" onPainted={vi.fn()} />);
      expect(screen.queryByRole('button', { name: /pintar/i })).not.toBeInTheDocument();
      unmount();
      const { unmount: unmountTwo } = render(<PaintColorMenu checked={publications('MLA1', 'MLA2')} equipo="" onPainted={vi.fn()} />);
      expect(screen.queryByRole('button', { name: /pintar/i })).not.toBeInTheDocument();
      unmountTwo();
      const { unmount: unmountMixed } = render(
        <PaintColorMenu checked={{ itemIds: ['MLA1'], productIds: [77] }} equipo="" onPainted={vi.fn()} />,
      );
      expect(screen.queryByRole('button', { name: /pintar/i })).not.toBeInTheDocument();
      unmountMixed();
      render(<PaintColorMenu checked={products(77, 78)} equipo="" onPainted={vi.fn()} />);
      expect(screen.getByRole('button', { name: 'Pintar 2 productos' })).toBeInTheDocument();
    });
  });
});
