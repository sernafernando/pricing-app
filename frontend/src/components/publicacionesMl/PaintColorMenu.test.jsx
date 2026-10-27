/**
 * PaintColorMenu (S8): paints the checked products on the layer on show with Productos' batch endpoint
 * (`POST /productos/actualizar-color-lote`, `equipo_id` in the body), behind Productos' own rule.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PaintColorMenu from './PaintColorMenu';
import api from '../../services/api';

vi.mock('../../services/api', () => ({ default: { post: vi.fn() } }));

let granted = new Set();
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

const setup = (props = {}) => {
  const onPainted = vi.fn();
  const onClearChecked = vi.fn();
  render(<PaintColorMenu checkedIds={new Set([77, 78])} equipo="" onPainted={onPainted} onClearChecked={onClearChecked} {...props} />);
  return { onPainted, onClearChecked, user: userEvent.setup() };
};

beforeEach(() => {
  vi.clearAllMocks();
  granted = new Set(['productos.marcar_color_lote']);
  api.post.mockResolvedValue({ data: { count: 2 } });
});

describe('PaintColorMenu', () => {
  it('is not there without checked products', () => {
    setup({ checkedIds: new Set() });
    expect(screen.queryByRole('button', { name: /pintar/i })).not.toBeInTheDocument();
  });

  it('on the global layer, only with productos.marcar_color_lote; on a team layer, for its members (every team listed)', () => {
    granted = new Set();
    const { unmount } = render(<PaintColorMenu checkedIds={new Set([77])} equipo="" onPainted={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /pintar/i })).not.toBeInTheDocument();
    unmount();
    render(<PaintColorMenu checkedIds={new Set([77])} equipo="12" onPainted={vi.fn()} />);
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
});
