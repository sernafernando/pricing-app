/**
 * One event as a sentence a person reads: what happened, in business words,
 * plus the detail that explains it. Every event below is a real API body
 * (`fixtures/eventsHistory_MLA1402898289_20261016.json`, production rows run
 * through the merged backend), so the payload shapes are the store's.
 */
import { describe, it, expect } from 'vitest';
import { describeEvent, describeOffers, eventIcon, foldOffers, money, originTag, stateTone } from './eventSentence';
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
      title: 'ML ofreció A- PVP LYONN (Campaña del vendedor)',
      detail: 'Precio sugerido $ 77.000 · se puede elegir entre $ 30.416 y $ 84.467,35',
      change: null,
    });
  });

  it('an offer without prices is just the sentence', () => {
    expect(describeEvent(event(57924))).toEqual({ title: 'ML ofreció Relampago compartidas (Oferta relámpago co-fondeada)', detail: null, change: null });
  });

  it('an applied promotion says at which price, and the sale price it replaced', () => {
    expect(describeEvent(event(3689))).toEqual({
      title: 'Se aplicó la promoción A PVP TODO (Campaña del vendedor) a $ 77.000',
      detail: null,
      change: { label: 'Precio de venta', before: '$ 91.193', after: '$ 77.000', delta: { text: '−15,6 %', direction: 'down' } },
    });
  });

  it('one we applied ourselves says so in first person', () => {
    const ours = { ...event(3689), origin: { kind: 'nosotros', user_name: 'Fernando S.' } };
    expect(describeEvent(ours).title).toBe('Activamos la promoción A PVP TODO (Campaña del vendedor) a $ 77.000');
  });

  it('a finished promotion reads by its state: applied and over, or no longer offered', () => {
    expect(describeEvent(event(43804)).title).toBe('Terminó la promoción A PVP TODO (Campaña del vendedor)');
    expect(describeEvent(event(6377)).title).toBe('ML dejó de ofrecer la promoción TO TP-LINK REPURCH T (Cupón del vendedor)');
  });

  it('a promotion type nobody named reads as "una promoción", never its code; its own name still shows', () => {
    expect(describeEvent({ ...event(71200), promotion_type: 'BRAND_NEW', promotion_name: null }).title).toBe('ML ofreció una promoción');
    expect(describeEvent({ ...event(71200), promotion_type: 'BRAND_NEW' }).title).toBe('ML ofreció A- PVP LYONN');
  });

  it('without its name, a promotion reads by its type as before', () => {
    const unnamed = (id) => ({ ...event(id), promotion_name: null });
    expect(describeEvent(unnamed(57925)).title).toBe('ML ofreció la promoción Campaña co-fondeada');
    expect(describeEvent(unnamed(3689)).title).toBe('Se aplicó la promoción Campaña del vendedor a $ 77.000');
    expect(describeEvent(unnamed(43804)).title).toBe('Terminó la promoción Campaña del vendedor');
    expect(describeEvent(unnamed(6377)).title).toBe('ML dejó de ofrecer la promoción Cupón del vendedor');
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

describe('the icon family', () => {
  it('price, promotion, play/pause, catalog star and stock, each with its tone', () => {
    expect(eventIcon(event(43805))).toEqual({ family: 'price', tone: 'warning' });
    expect(eventIcon(event(71200))).toEqual({ family: 'promotion', tone: 'neutral' });
    expect(eventIcon(event(3689))).toEqual({ family: 'promotion', tone: 'info' });
    expect(eventIcon(event(43638))).toEqual({ family: 'play', tone: 'success' });
    expect(eventIcon(event(42330))).toEqual({ family: 'pause', tone: 'warning' });
    expect(eventIcon(event(3687))).toEqual({ family: 'star', tone: 'success' });
    expect(eventIcon(event(43333))).toEqual({ family: 'star', tone: 'danger' });
    expect(eventIcon(event(3195))).toEqual({ family: 'stock', tone: 'info' });
    expect(eventIcon({ ...event(42330), event_type: 'title_changed' })).toEqual({ family: 'other', tone: 'neutral' });
  });
});

describe('folding the offers ML made in the same minute', () => {
  const ids = (lines) => lines.map((line) => line.events.map((found) => found.id));

  it('folds consecutive informative ML offers of the same minute, and nothing else', () => {
    const lines = foldOffers(capture.events.events);
    expect(lines).toHaveLength(18);
    expect(ids(lines).slice(0, 3)).toEqual([[71200, 71199, 71198], [57925, 57924], [43805]]);
    expect(ids(lines).find((group) => group.includes(6379))).toEqual([6379, 6378]);
    // the offers that went away right after are not offers: they stay alone
    expect(ids(lines).find((group) => group.includes(6377))).toEqual([6377]);
  });

  it('never folds an offer we made, an applied one, or offers of different minutes', () => {
    const [a, b] = [event(71200), event(71199)];
    expect(foldOffers([a, { ...b, origin: { kind: 'nosotros', user_name: 'Fernando S.' } }])).toHaveLength(2);
    expect(foldOffers([a, { ...b, informational: false }])).toHaveLength(2);
    expect(foldOffers([a, { ...b, observed_at: '2026-10-16T03:12:01.000000Z' }])).toHaveLength(2);
    expect(foldOffers([a, b])).toHaveLength(1);
  });

  const unnamed = (id) => ({ ...event(id), promotion_name: null });

  it('a fold of one type counts them, and its detail names each offer', () => {
    expect(describeOffers([event(71200), event(71199), event(71198)])).toEqual({
      title: 'ML ofreció 3 campañas del vendedor',
      detail: 'A- PVP LYONN, PVP LYONN y A - PVP TP',
      change: null,
    });
  });

  it('offers without a name are counted after the named ones', () => {
    expect(describeOffers([event(71200), unnamed(71199), event(71198)]).detail).toBe('A- PVP LYONN, A - PVP TP y 1 más');
    expect(describeOffers([unnamed(71200), unnamed(71199), event(71198)]).detail).toBe('A - PVP TP y 2 más');
  });

  it('a fold with no names keeps the detail its offers share', () => {
    expect(describeOffers([unnamed(71200), unnamed(71199), unnamed(71198)])).toEqual({
      title: 'ML ofreció 3 campañas del vendedor',
      detail: 'Precio sugerido $ 77.000 · se puede elegir entre $ 30.416 y $ 84.467,35',
      change: null,
    });
  });

  it('a fold of several types names each one', () => {
    expect(describeOffers([event(57925), event(57924)])).toEqual({
      title: 'ML ofreció Campaña co-fondeada y Oferta relámpago co-fondeada',
      detail: 'Tec Week y Relampago compartidas',
      change: null,
    });
    expect(describeOffers([event(71200), event(71199), event(57925)]).title).toBe('ML ofreció 2 campañas del vendedor y Campaña co-fondeada');
  });
});
