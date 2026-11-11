/**
 * sellInBonoValores — a brand bonus narrowed to one category (SISO S3, loaded from a tactical): the Bonos panel shows
 * it and keeps it on an edit, but does not offer it (L7 D3).
 */
import { describe, it, expect } from 'vitest';
import { BONO_VACIO, alcanceDeBono, bodyDeBono, valoresDeBono } from './sellInBonoValores';

const BONO = {
  alcance: 'marca',
  marca: 'TP-LINK',
  categoria: 'Routers',
  base: 'costo_venta',
  tipo: 'porcentaje',
  porcentaje: '3.0000',
  moneda: 'ARS',
  fecha_desde: '2026-11-01',
  fecha_hasta: '2026-11-30',
};

describe('a brand bonus with a category (SISO S3)', () => {
  it('reads "Marca TP-LINK · Routers"; a plain brand bonus still reads "Marca TP-LINK"', () => {
    expect(alcanceDeBono(BONO)).toBe('Marca TP-LINK · Routers');
    expect(alcanceDeBono({ ...BONO, categoria: null })).toBe('Marca TP-LINK');
  });

  it('an edit keeps its category, so the scope never widens to the whole brand', () => {
    const body = bodyDeBono(valoresDeBono(BONO));
    expect(body).toEqual(expect.objectContaining({ alcance: 'marca', marca: 'TP-LINK', categoria: 'Routers' }));
  });

  it('a category picked on a category bonus is not sent once the bonus becomes a brand one', () => {
    const body = bodyDeBono({ ...BONO_VACIO, alcance: 'marca', marca: 'HP', categoria: 'Routers' }, true);
    expect(body).not.toHaveProperty('categoria');
  });
});
