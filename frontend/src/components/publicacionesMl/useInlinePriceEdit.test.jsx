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
  preciosAPI: {
    calcularMarkup: vi.fn(),
    setRapido: vi.fn(),
    setCuota: vi.fn(),
    setRebate: vi.fn(),
    setWebTransferencia: vi.fn(),
    setOutOfCards: vi.fn(),
  },
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
  preciosAPI.setRebate.mockResolvedValue({ data: {} });
  preciosAPI.setWebTransferencia.mockResolvedValue({ data: {} });
  preciosAPI.setOutOfCards.mockResolvedValue({ data: {} });
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

  describe('the r / w / o toggles (S9), written as the panel writes them', () => {
    it("r turns the rebate on with the product's stored percentage (3.8 when it has none), and off again", async () => {
      const { result, onWritten } = setup();
      await act(async () => {
        await result.current.toggle('rebate', { item_id: 7, participa_rebate: false, porcentaje_rebate: null });
      });
      expect(preciosAPI.setRebate).toHaveBeenCalledWith(7, { participa_rebate: true, porcentaje_rebate: 3.8 });
      expect(result.current.message).toEqual({ tone: 'ok', text: 'Rebate activado.' });
      await act(async () => {
        await result.current.toggle('rebate', { item_id: 7, participa_rebate: true, porcentaje_rebate: 4.5 });
      });
      expect(preciosAPI.setRebate).toHaveBeenLastCalledWith(7, { participa_rebate: false, porcentaje_rebate: 4.5 });
      expect(result.current.message).toEqual({ tone: 'ok', text: 'Rebate desactivado.' });
      expect(onWritten).toHaveBeenCalledTimes(2);
    });

    it('w flips the web transfer keeping its percentage and its preserve flag', async () => {
      const { result } = setup();
      await act(async () => {
        await result.current.toggle('web', { item_id: 7, participa_web_transferencia: false, porcentaje_markup_web: 5, preservar_porcentaje_web: true });
      });
      expect(preciosAPI.setWebTransferencia).toHaveBeenCalledWith(7, { participa: true, porcentaje_markup: 5, preservar_porcentaje: true });
      expect(result.current.message.text).toBe('Web transferencia activada.');
    });

    it('o flips "fuera de tarjetas"', async () => {
      const { result } = setup();
      await act(async () => {
        await result.current.toggle('tarjetas', { item_id: 7, out_of_cards: true });
      });
      expect(preciosAPI.setOutOfCards).toHaveBeenCalledWith(7, false);
      expect(result.current.message.text).toBe('Fuera de tarjetas desactivado.');
    });

    it("a failed toggle shows the backend's reason and reports nothing written", async () => {
      preciosAPI.setOutOfCards.mockRejectedValue({ response: { data: { detail: 'El producto no tiene pricing' } } });
      const { result, onWritten } = setup();
      await act(async () => {
        await result.current.toggle('tarjetas', { item_id: 7, out_of_cards: false });
      });
      expect(result.current.message).toEqual({ tone: 'error', text: 'El producto no tiene pricing' });
      expect(onWritten).not.toHaveBeenCalled();
    });
  
    it('a second press before the prices are read again flips back, from what was just written', async () => {
      const { result } = setup();
      const stale = { item_id: 7, participa_rebate: false, porcentaje_rebate: 4 };
      await act(async () => {
        await result.current.toggle('rebate', stale);
      });
      await act(async () => {
        await result.current.toggle('rebate', stale);
      });
      expect(preciosAPI.setRebate.mock.calls.map(([, body]) => body.participa_rebate)).toEqual([true, false]);
      // A fresh read of the product is the truth again.
      await act(async () => {
        await result.current.toggle('rebate', { ...stale, participa_rebate: true });
      });
      expect(preciosAPI.setRebate).toHaveBeenLastCalledWith(7, { participa_rebate: false, porcentaje_rebate: 4 });
    });

    it('a press while a write is on its way writes nothing', async () => {
      let finish;
      preciosAPI.setOutOfCards.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
      const { result } = setup();
      let first;
      act(() => {
        first = result.current.toggle('tarjetas', { item_id: 7, out_of_cards: false });
      });
      let second;
      await act(async () => {
        second = await result.current.toggle('tarjetas', { item_id: 7, out_of_cards: false });
      });
      expect(second).toBe(false);
      // Said, never dropped in silence (a price typed meanwhile would not be saved either).
      expect(result.current.message).toEqual({ tone: 'error', text: 'Esperá a que termine el cambio anterior.' });
      await act(async () => {
        finish({ data: {} });
        await first;
      });
      expect(preciosAPI.setOutOfCards).toHaveBeenCalledTimes(1);
    });

    it('a price typed while a toggle is on its way is not checked nor saved, and says why', async () => {
      let finish;
      preciosAPI.setOutOfCards.mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
      const { result } = setup();
      let first;
      act(() => {
        first = result.current.toggle('tarjetas', { item_id: 7, out_of_cards: false });
      });
      let saved;
      await act(async () => {
        saved = await result.current.save(CLASICA, PRODUCT, '500');
      });
      expect(saved).toBe(false);
      expect(preciosAPI.calcularMarkup).not.toHaveBeenCalled();
      expect(result.current.message).toEqual({ tone: 'error', text: 'Esperá a que termine el cambio anterior.' });
      await act(async () => {
        finish({ data: {} });
        await first;
      });
      expect(result.current.saving).toBe(false);
      expect(preciosAPI.setRapido).not.toHaveBeenCalled();
    });
  });
});
