/**
 * useColumnLayout (pubml-columnas-presets S1, S2): each view's visible columns and their order, kept per user on
 * the server (`GET` / `PUT /ml-publications/layouts/{vista}`), so they survive a reload and another PC.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import useColumnLayout, { SAVE_DELAY_MS } from './useColumnLayout';
import { mlPublicationsPresetsAPI } from '../services/mlPublicationsPresets';

vi.mock('../services/mlPublicationsPresets', () => ({
  mlPublicationsPresetsAPI: { getLayout: vi.fn(), saveLayout: vi.fn() },
}));

const COLUMNS = [
  { key: 'titulo', header: 'Publicación' },
  { key: 'tipo', header: 'Tipo' },
  { key: 'unidades_7d', group: 'Ventas', header: '7D', label: 'Ventas 7D' },
  { key: 'unidades_30d', group: 'Ventas', header: '30D', label: 'Ventas 30D' },
  { key: 'codigo', header: 'Código' },
];
const DEFAULTS = { codigo: false };
const keys = (columns) => columns.map((column) => column.key);

const setup = (vista = 'publicacion') =>
  renderHook((props) => useColumnLayout({ columns: COLUMNS, defaults: DEFAULTS, ...props }), { initialProps: { vista } });

beforeEach(() => {
  mlPublicationsPresetsAPI.getLayout.mockReset();
  mlPublicationsPresetsAPI.saveLayout.mockReset();
  mlPublicationsPresetsAPI.getLayout.mockResolvedValue({ columns: null, preset_activo_id: null });
  mlPublicationsPresetsAPI.saveLayout.mockImplementation((vista, body) => Promise.resolve(body));
  localStorage.clear();
});

afterEach(() => vi.useRealTimers());

describe('loading', () => {
  it('asks the view its saved layout and shows the defaults until (and when) nothing is saved', async () => {
    const { result } = setup();
    expect(keys(result.current.arrange(COLUMNS))).toEqual(['titulo', 'tipo', 'unidades_7d', 'unidades_30d']);
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(mlPublicationsPresetsAPI.getLayout).toHaveBeenCalledWith('publicacion');
    expect(keys(result.current.arrange(COLUMNS))).toEqual(['titulo', 'tipo', 'unidades_7d', 'unidades_30d']);
    expect(result.current.presetId).toBeNull();
  });

  it('applies the saved visibility and order, ignoring unknown keys; a column the save lacks keeps its default place', async () => {
    mlPublicationsPresetsAPI.getLayout.mockResolvedValue({
      columns: { visibility: { codigo: true, tipo: false, ya_no_existe: true }, order: ['titulo', 'codigo', 'ya_no_existe', 'unidades_30d'] },
      preset_activo_id: 7,
    });
    const { result } = setup();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    // unidades_7d is not in the save: it moves with its group, at its default place inside it (first).
    expect(keys(result.current.arrange(COLUMNS))).toEqual(['titulo', 'codigo', 'unidades_7d', 'unidades_30d']);
    expect(result.current.presetId).toBe(7);
  });

  it('a failed load is no crash: the defaults', async () => {
    mlPublicationsPresetsAPI.getLayout.mockRejectedValue(new Error('500'));
    const { result } = setup();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(keys(result.current.arrange(COLUMNS))).toEqual(['titulo', 'tipo', 'unidades_7d', 'unidades_30d']);
  });
});

describe('saving', () => {
  it('a picker toggle saves the whole layout of the view, once, after a pause', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    vi.useFakeTimers();
    const tienda = () => result.current.pickerTable.getAllLeafColumns().find((column) => column.id === 'codigo');
    act(() => tienda().getToggleVisibilityHandler()());
    act(() => result.current.pickerTable.getAllLeafColumns().find((column) => column.id === 'tipo').getToggleVisibilityHandler()());
    expect(mlPublicationsPresetsAPI.saveLayout).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTime(SAVE_DELAY_MS));
    expect(mlPublicationsPresetsAPI.saveLayout).toHaveBeenCalledTimes(1);
    expect(mlPublicationsPresetsAPI.saveLayout).toHaveBeenCalledWith('publicacion', {
      columns: {
        visibility: { titulo: true, tipo: false, unidades_7d: true, unidades_30d: true, codigo: true },
        order: ['titulo', 'tipo', 'unidades_7d', 'unidades_30d', 'codigo'],
      },
      preset_activo_id: null,
    });
    expect(keys(result.current.arrange(COLUMNS))).toEqual(['titulo', 'unidades_7d', 'unidades_30d', 'codigo']);
  });

  it('reorder keeps the first column first and saves the new order', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    vi.useFakeTimers();
    act(() => result.current.reorder(['unidades_7d', 'unidades_30d', 'tipo', 'codigo']));
    expect(keys(result.current.arrange(COLUMNS))).toEqual(['titulo', 'unidades_7d', 'unidades_30d', 'tipo']);
    await act(async () => vi.advanceTimersByTime(SAVE_DELAY_MS));
    expect(mlPublicationsPresetsAPI.saveLayout.mock.calls.at(-1)[1].columns.order).toEqual([
      'titulo',
      'unidades_7d',
      'unidades_30d',
      'tipo',
      'codigo',
    ]);
  });

  it('Restablecer saves nulls right away and goes back to the defaults', async () => {
    mlPublicationsPresetsAPI.getLayout.mockResolvedValue({ columns: { visibility: { tipo: false }, order: ['codigo'] }, preset_activo_id: 3 });
    const { result } = setup();
    await waitFor(() => expect(result.current.presetId).toBe(3));
    act(() => result.current.reset());
    expect(mlPublicationsPresetsAPI.saveLayout).toHaveBeenCalledWith('publicacion', { columns: null, preset_activo_id: null });
    expect(keys(result.current.arrange(COLUMNS))).toEqual(['titulo', 'tipo', 'unidades_7d', 'unidades_30d']);
    expect(result.current.presetId).toBeNull();
  });

  it('a change still waiting is saved to its own view when the view changes, and the new view loads its own', async () => {
    const { result, rerender } = setup();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    act(() => result.current.reorder(['codigo', 'tipo', 'unidades_7d', 'unidades_30d']));
    rerender({ vista: 'producto' });
    expect(mlPublicationsPresetsAPI.saveLayout).toHaveBeenCalledWith('publicacion', expect.objectContaining({ preset_activo_id: null }));
    await waitFor(() => expect(mlPublicationsPresetsAPI.getLayout).toHaveBeenCalledWith('producto'));
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(keys(result.current.arrange(COLUMNS))).toEqual(['titulo', 'tipo', 'unidades_7d', 'unidades_30d']);
  });
});

describe('Auditoría', () => {
  it('with nothing on the server, starts from the columns this browser hid before (the old localStorage key)', async () => {
    localStorage.setItem('publicaciones-ml.auditoria.columnas-ocultas', JSON.stringify(['tipo']));
    const { result } = setup('auditoria');
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(keys(result.current.arrange(COLUMNS))).toEqual(['titulo', 'unidades_7d', 'unidades_30d']);
  });
});
