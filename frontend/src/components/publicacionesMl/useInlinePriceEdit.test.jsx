/**
 * useInlinePriceEdit (S11c): a price typed in a Publicaciones ML table cell is saved with the very flow of the
 * product panel and Productos: parse, confirm a 0 (it clears the price) or a negative markup, write, report.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import useInlinePriceEdit from './useInlinePriceEdit';
import { LISTS } from '../pricing/priceWrites';
import { preciosAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  preciosAPI: { calcularMarkup: vi.fn(), setRapido: vi.fn(), setCuota: vi.fn() },
}));

const ROWS = LISTS.flatMap((list) => list.rows);
const CLASICA = ROWS.find((row) => row.id === 'ml-clasica');
const CUOTA6 = ROWS.find((row) => row.id === 'ml-6');
const PRODUCT = { item_id: 7, recalcular_cuotas_auto: false };

const setup = () => {
  const onWritten = vi.fn();
  const hook = renderHook(() => useInlinePriceEdit({ onWritten }));
  return { ...hook, onWritten };
};

beforeEach(() => {
  vi.clearAllMocks();
  preciosAPI.calcularMarkup.mockResolvedValue({ data: { markup: 12 } });
  preciosAPI.setRapido.mockResolvedValue({ data: {} });
  preciosAPI.setCuota.mockResolvedValue({ data: {} });
});

describe('useInlinePriceEdit', () => {
  it('saves a valid price as Productos does and reports it', async () => {
    const { result, onWritten } = setup();
    let saved;
    await act(async () => {
      saved = await result.current.save(CLASICA, PRODUCT, '1.200,50');
    });
    expect(saved).toBe(true);
    expect(preciosAPI.calcularMarkup).toHaveBeenCalledWith({ item_id: 7, precio: 1200.5, pricelist_id: CLASICA.pricelist });
    expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 7, precio: 1200.5, recalcular_cuotas: false });
    expect(result.current.message).toEqual({ tone: 'ok', text: 'Precio guardado.' });
    expect(onWritten).toHaveBeenCalledTimes(1);
  });

  it('writes a cuota through its own endpoint', async () => {
    const { result } = setup();
    await act(async () => {
      await result.current.save(CUOTA6, PRODUCT, '900');
    });
    expect(preciosAPI.setCuota).toHaveBeenCalledWith({ item_id: 7, tipo_cuota: CUOTA6.cuota, precio: 900, lista_tipo: CUOTA6.listaTipo });
  });

  it('an invalid value is an error and writes nothing', async () => {
    const { result, onWritten } = setup();
    let saved;
    await act(async () => {
      saved = await result.current.save(CLASICA, PRODUCT, 'abc');
    });
    expect(saved).toBe(false);
    expect(result.current.message.tone).toBe('error');
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
    expect(onWritten).not.toHaveBeenCalled();
  });

  it('a 0 clears the price: it asks first, and writes only once confirmed', async () => {
    const { result, onWritten } = setup();
    await act(async () => {
      await result.current.save(CLASICA, PRODUCT, '0');
    });
    expect(result.current.pending).toMatchObject({ kind: 'zero', row: CLASICA });
    expect(result.current.warning).toBe('Esto borra el precio de la lista ML y todas sus cuotas.');
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
    await act(async () => {
      await result.current.confirm();
    });
    expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 7, precio: 0, recalcular_cuotas: false });
    expect(result.current.pending).toBeNull();
    expect(onWritten).toHaveBeenCalledTimes(1);
  });

  it('a negative markup asks first; cancelling writes nothing', async () => {
    preciosAPI.calcularMarkup.mockResolvedValue({ data: { markup: -4.5 } });
    const { result } = setup();
    await act(async () => {
      await result.current.save(CLASICA, PRODUCT, '500');
    });
    expect(result.current.pending).toMatchObject({ kind: 'negative', markup: -4.5 });
    expect(result.current.warning).toContain('Markup negativo en');
    act(() => result.current.cancel());
    expect(result.current.pending).toBeNull();
    expect(preciosAPI.setRapido).not.toHaveBeenCalled();
  });

  it('a confirmed negative markup is saved without asking again', async () => {
    preciosAPI.calcularMarkup.mockResolvedValue({ data: { markup: -4.5 } });
    const { result } = setup();
    await act(async () => {
      await result.current.save(CLASICA, PRODUCT, '500');
    });
    await act(async () => {
      await result.current.confirm();
    });
    expect(preciosAPI.calcularMarkup).toHaveBeenCalledTimes(1);
    expect(preciosAPI.setRapido).toHaveBeenCalledWith({ item_id: 7, precio: 500, recalcular_cuotas: false });
  });

  it('a failed markup check does not block the save', async () => {
    preciosAPI.calcularMarkup.mockRejectedValue(new Error('down'));
    const { result } = setup();
    await act(async () => {
      await result.current.save(CLASICA, PRODUCT, '500');
    });
    expect(preciosAPI.setRapido).toHaveBeenCalled();
  });

  it("a failed write shows the backend's reason and reports nothing written", async () => {
    preciosAPI.setRapido.mockRejectedValue({ response: { data: { detail: 'Sin permiso' } } });
    const { result, onWritten } = setup();
    let saved;
    await act(async () => {
      saved = await result.current.save(CLASICA, PRODUCT, '500');
    });
    expect(saved).toBe(false);
    expect(result.current.message).toEqual({ tone: 'error', text: 'Sin permiso' });
    expect(result.current.saving).toBe(false);
    expect(onWritten).not.toHaveBeenCalled();
  });
});
