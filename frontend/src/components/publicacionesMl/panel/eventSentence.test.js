/**
 * One event as a sentence a person reads: what happened, in business words,
 * plus the detail that explains it. Every event below is a real API body
 * (`fixtures/eventsHistory_MLA1402898289_20261016.json`, production rows run
 * through the merged backend), so the payload shapes are the store's.
 */
import { describe, it, expect } from 'vitest';
import { describeEvent, money, originTag, stateTone } from './eventSentence';
import capture from './fixtures/eventsHistory_MLA1402898289_20261016.json';

const event = (id) => capture.events.events.find((found) => found.id === id);

describe('money', () => {
  it('reads as pesos with thousands separators, and cents only when there are any', () => {
    expect(money('77000.0')).toBe('$ 77.000');
    expect(money('84467.35')).toBe('$ 84.467,35');
    expect(money(null)).toBeNull();
    expect(money('not a number')).toBeNull();
  });
});

describe('promotions', () => {
  it('an offer says ML offered it, with the suggested price and the range it allows', () => {
    expect(describeEvent(event(71200))).toEqual({
      title: 'ML ofreció la promoción Campaña del vendedor',
      detail: 'Precio sugerido $ 77.000 · se puede elegir entre $ 30.416 y $ 84.467,35',
      change: null,
    });
  });

  it('an offer without prices is just the sentence', () => {
    expect(describeEvent(event(57924))).toEqual({ title: 'ML ofreció la promoción Oferta relámpago co-fondeada', detail: null, change: null });
  });

  it('an applied promotion says at which price, and the sale price it replaced', () => {
    expect(describeEvent(event(3689))).toEqual({
      title: 'Se aplicó la promoción Campaña del vendedor a $ 77.000',
      detail: null,
      change: { label: 'Precio de venta', before: '$ 91.193', after: '$ 77.000', delta: { text: '−15,6 %', direction: 'down' } },
    });
  });

  it('one we applied ourselves says so in first person', () => {
    const ours = { ...event(3689), origin: { kind: 'nosotros', user_name: 'Fernando S.' } };
    expect(describeEvent(ours).title).toBe('Activamos la promoción Campaña del vendedor a $ 77.000');
  });

  it('a finished promotion reads by its state: applied and over, or no longer offered', () => {
    expect(describeEvent(event(43804)).title).toBe('Terminó la promoción Campaña del vendedor');
    expect(describeEvent(event(6377)).title).toBe('ML dejó de ofrecer la promoción Cupón del vendedor');
  });

  it('a promotion type nobody named reads as "una promoción", never its code', () => {
    expect(describeEvent({ ...event(71200), promotion_type: 'BRAND_NEW' }).title).toBe('ML ofreció una promoción');
  });
});

describe('prices', () => {
  it('a sale price change shows both prices and how much it moved', () => {
    expect(describeEvent(event(43805))).toEqual({
      title: 'Cambió el precio de venta',
      detail: null,
      change: { label: null, before: '$ 77.000', after: '$ 88.913', delta: { text: '+15,5 %', direction: 'up' } },
    });
  });

  it('a list price change says it is the list price', () => {
    expect(describeEvent(event(43802))).toMatchObject({
      title: 'Cambió el precio de lista',
      change: { before: '$ 91.193', after: '$ 88.913', delta: { text: '−2,5 %', direction: 'down' } },
    });
  });

  it('a promotion price that appears or goes away says so, without a percentage', () => {
    expect(describeEvent(event(3688))).toMatchObject({ title: 'Nuevo precio de promoción', change: { before: null, after: '$ 77.000', delta: null } });
    expect(describeEvent(event(43803))).toMatchObject({ title: 'Se quitó el precio de promoción', change: { before: '$ 77.000', after: null, delta: null } });
  });
});

describe('status, catalog and stock', () => {
  it('tells a reactivation from a first activation, and a pause', () => {
    expect(describeEvent(event(43638)).title).toBe('Publicación reactivada');
    expect(describeEvent(event(3194)).title).toBe('Publicación activada');
    expect(describeEvent(event(42330))).toEqual({ title: 'Publicación pausada', detail: null, change: null });
  });

  it('the catalog: won at a price, or out of the competition after winning', () => {
    expect(describeEvent(event(3687)).title).toBe('Ganó el catálogo con $ 77.000');
    expect(describeEvent(event(43333))).toEqual({ title: 'Dejó de competir en el catálogo', detail: 'Antes estaba ganando.', change: null });
  });

  it('stock that came back shows the quantities', () => {
    expect(describeEvent(event(3195))).toEqual({
      title: 'Volvió a tener stock',
      detail: null,
      change: { label: 'Stock', before: '0', after: '5', delta: null },
    });
  });
});

describe('any other type', () => {
  it('reads as its Spanish label with the plain values', () => {
    const title = { ...event(42330), event_type: 'title_changed', old_value: 'Router viejo', new_value: 'Router nuevo', payload: null };
    expect(describeEvent(title)).toEqual({
      title: 'Título modificado',
      detail: null,
      change: { label: null, before: 'Router viejo', after: 'Router nuevo', delta: null },
    });
  });

  it('never shows an object as JSON', () => {
    const odd = { ...event(42330), event_type: 'brand_new_type', old_value: { a: 1 }, new_value: { a: 2 }, payload: null };
    expect(describeEvent(odd)).toEqual({ title: 'Evento', detail: null, change: null });
  });
});

describe('the origin tag', () => {
  it('names who caused it: us with the user, an automatic process, ML, or unknown', () => {
    expect(originTag({ kind: 'nosotros', user_name: 'Fernando S.' }, false)).toEqual({ text: 'Hecho por nosotros · Fernando S.', tone: 'ours' });
    expect(originTag({ kind: 'nosotros', user_name: null }, false)).toEqual({ text: 'Hecho por nosotros', tone: 'ours' });
    expect(originTag({ kind: 'automatico', user_name: null }, false)).toEqual({ text: 'Automático', tone: 'auto' });
    expect(originTag({ kind: 'ml', user_name: null }, false)).toEqual({ text: 'Cambio de ML', tone: 'neutral' });
    expect(originTag({ kind: 'ml', user_name: null }, true)).toEqual({ text: 'Informativo de ML', tone: 'neutral' });
    expect(originTag({ kind: 'sin_registrar', user_name: null }, false)).toEqual({ text: 'Origen sin registrar', tone: 'neutral' });
  });

  it('is absent when the backend sent no origin', () => {
    expect(originTag(undefined, false)).toBeNull();
  });
});

describe('the state tone', () => {
  it('offered is amber, applied green, gone neutral', () => {
    expect(stateTone('Disponible para activar')).toBe('warning');
    expect(stateTone('Aplicada')).toBe('success');
    expect(stateTone('Pendiente')).toBe('info');
    expect(stateTone('Finalizada')).toBe('neutral');
    expect(stateTone('Ya no se ofrece')).toBe('neutral');
  });
});
