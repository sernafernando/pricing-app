/**
 * Corrimiento de zona horaria en las fechas de los documentos.
 *
 * Un `YYYY-MM-DD` pelado —que es como el backend serializa toda columna
 * `Date`— lo parsea el motor como medianoche UTC. En Argentina (UTC-3) eso
 * cae el día anterior, así que el documento impreso mostraba una fecha
 * corrida un día.
 *
 * Afectaba a documentos que la gente FIRMA: la ficha de empleado (nacimiento,
 * ingreso, egreso), la sanción (ingreso y período de suspensión), la
 * notificación de vacaciones (desde, hasta, reincorporación), el RMA (fecha
 * del caso) y el remito de envíos (fecha de envío).
 *
 * IMPORTANTE: el bug SOLO se manifiesta en zonas con offset negativo. En UTC
 * o en Asia no aparece, así que estos tests fijan la zona; sin eso, un CI en
 * UTC los dejaría pasar sin probar nada. El primer test es el guardián de esa
 * premisa.
 */

import { describe, it, expect, beforeAll, afterAll, vi } from 'vitest';

import { mapEntityToInputs } from './contextDataMappers';

beforeAll(() => {
  vi.stubEnv('TZ', 'America/Buenos_Aires');
});

afterAll(() => {
  vi.unstubAllEnvs();
});

describe('premisa del entorno de test', () => {
  it('corre en una zona que efectivamente corre la fecha hacia atrás', () => {
    // Si esto falla, la zona no está aplicada y TODO el resto del archivo
    // pasaría sin ejercitar el bug. Es un guardián, no una aserción del fix.
    expect(new Date('2026-08-03').toLocaleDateString('es-AR')).toBe('2/8/2026');
  });
});

describe('ficha de empleado', () => {
  it('no corre nacimiento, ingreso ni egreso', () => {
    const out = mapEntityToInputs('rrhh', {
      fecha_nacimiento: '1990-01-01',
      fecha_ingreso: '2020-08-03',
      fecha_egreso: '2026-03-01',
    });

    expect(out.fecha_nacimiento).toBe('1/1/1990');
    expect(out.fecha_ingreso).toBe('3/8/2020');
    expect(out.fecha_egreso).toBe('1/3/2026');
  });
});

describe('sanción', () => {
  it('no corre el ingreso ni el período de suspensión', () => {
    const out = mapEntityToInputs('sanciones', {
      fecha_ingreso: '2020-08-03',
      fecha_desde: '2026-08-10',
      fecha_hasta: '2026-08-12',
    });

    expect(out.empleado_fecha_ingreso).toBe('3/8/2020');
    expect(out.fecha_suspension_desde).toBe('10/8/2026');
    expect(out.fecha_suspension_hasta).toBe('12/8/2026');
  });
});

describe('vacaciones', () => {
  it('no corre desde, hasta ni reincorporación', () => {
    const out = mapEntityToInputs('vacaciones', {
      fecha_desde: '2026-08-03',
      fecha_hasta: '2026-08-17',
      fecha_reincorporacion: '2026-08-18',
    });

    expect(out.fecha_desde).toBe('3/8/2026');
    expect(out.fecha_hasta).toBe('17/8/2026');
    expect(out.fecha_reincorporacion).toBe('18/8/2026');
  });
});

describe('RMA y remito de envíos', () => {
  it('no corre la fecha del caso', () => {
    expect(mapEntityToInputs('rma', { fecha_caso: '2026-08-03' }).fecha_caso).toBe('3/8/2026');
  });

  it('no corre la fecha de envío', () => {
    expect(mapEntityToInputs('envios', { fecha_envio: '2026-08-03' }).fecha_envio).toBe('3/8/2026');
  });
});

describe('valores que no son fecha sin hora', () => {
  it('un ISO con hora se sigue interpretando en zona local, sin anclar', () => {
    // 2026-08-03T23:30 local sigue siendo el día 3; no se toca el parseo.
    const out = mapEntityToInputs('rma', { fecha_caso: '2026-08-03T23:30:00' });
    expect(out.fecha_caso).toBe('3/8/2026');
  });

  it('un timestamp UTC con Z se convierte a local como antes', () => {
    // 2026-08-04T01:00Z es el 3 a las 22:00 en AR: la conversión debe seguir ocurriendo.
    const out = mapEntityToInputs('rma', { fecha_caso: '2026-08-04T01:00:00Z' });
    expect(out.fecha_caso).toBe('3/8/2026');
  });

  it('un valor no parseable devuelve el original y NO el texto "Invalid Date"', () => {
    const out = mapEntityToInputs('rma', { fecha_caso: 'no soy una fecha' });
    expect(out.fecha_caso).toBe('no soy una fecha');
  });

  it('null y string vacío dan string vacío', () => {
    expect(mapEntityToInputs('rma', { fecha_caso: null }).fecha_caso).toBe('');
    expect(mapEntityToInputs('rma', { fecha_caso: '' }).fecha_caso).toBe('');
  });
});
