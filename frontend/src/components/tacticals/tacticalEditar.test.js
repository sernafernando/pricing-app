/**
 * tacticalEditar: the Editar dialog's values and the body of `PATCH /tacticals/{id}` (tacticals F1): only the name,
 * the note, the end date and each line's caps, and only what changed.
 */
import { describe, it, expect } from 'vitest';
import { TACTICAL_BPS, TACTICAL_REBATE } from './tacticalsFixtures';
import { cuerpoDeEdicion, problemaDeEdicion, valoresDeEdicion } from './tacticalEditar';

describe('valoresDeEdicion', () => {
  it("one row per line with its caps and the most any of its children already used", () => {
    const valores = valoresDeEdicion({ ...TACTICAL_BPS, nota: 'Por mail' });

    expect({ ...valores, lineas: undefined }).toEqual({ nombre: 'Tacticals BPS Noviembre Q1FY27', nota: 'Por mail', fechaHasta: '2026-11-30' });
    expect(valores.lineas).toEqual([
      { linea: 1, titulo: '2 productos, cada uno con su tope', topeUnidades: '90', topeMonto: '', usadas: 62, usado: 12760, moneda: 'USD', admiteTopes: true },
      { linea: 2, titulo: '2 productos con un tope compartido', topeUnidades: '300', topeMonto: '3000', usadas: 132, usado: 1584, moneda: 'USD', admiteTopes: true },
    ]);
  });

  it('a product line that comes without its products still opens', () => {
    const tactical = { ...TACTICAL_REBATE, lineas: [{ ...TACTICAL_REBATE.lineas[0], alcance: 'productos', productos: null }] };

    expect(valoresDeEdicion(tactical).lineas[0].titulo).toBe('0 productos');
  });

  it('a monto total line takes no caps', () => {
    const tactical = { ...TACTICAL_REBATE, lineas: [{ ...TACTICAL_REBATE.lineas[0], modo_monto: 'monto_total' }] };

    expect(valoresDeEdicion(tactical).lineas[0]).toMatchObject({ titulo: 'Marca HP', admiteTopes: false });
  });
});

describe('cuerpoDeEdicion', () => {
  it('sends only what changed; an emptied cap goes as null, which removes it', () => {
    const valores = valoresDeEdicion(TACTICAL_BPS);
    valores.nombre = 'Tacticals BPS Diciembre';
    valores.fechaHasta = '2026-12-31';
    valores.lineas[0].topeUnidades = '120';
    valores.lineas[1].topeMonto = '';

    expect(cuerpoDeEdicion(TACTICAL_BPS, valores)).toEqual({
      nombre: 'Tacticals BPS Diciembre',
      fecha_hasta: '2026-12-31',
      lineas: [
        { linea: 1, tope_unidades: 120 },
        { linea: 2, tope_monto: null },
      ],
    });
    expect(cuerpoDeEdicion(TACTICAL_BPS, valoresDeEdicion(TACTICAL_BPS))).toEqual({});
  });

  it('reads amounts as the screen types them (es-AR)', () => {
    const valores = valoresDeEdicion(TACTICAL_BPS);
    valores.lineas[1].topeMonto = '3.500,50';
    valores.nota = '  ';

    expect(cuerpoDeEdicion({ ...TACTICAL_BPS, nota: 'Vieja' }, valores)).toEqual({
      nota: null,
      lineas: [{ linea: 2, tope_monto: 3500.5 }],
    });
  });
});

describe('problemaDeEdicion', () => {
  it('stops an empty name, a missing end date and a cap that is not a whole number', () => {
    const ok = valoresDeEdicion(TACTICAL_BPS);
    expect(problemaDeEdicion(ok)).toBeNull();
    expect(problemaDeEdicion({ ...ok, nombre: ' ' })).toBe('El nombre no puede quedar vacío.');
    expect(problemaDeEdicion({ ...ok, fechaHasta: '' })).toBe('Elegí la fecha hasta.');
    const mal = { ...ok, lineas: [{ ...ok.lineas[0], topeUnidades: '1,5' }, ok.lineas[1]] };
    expect(problemaDeEdicion(mal)).toBe('La línea 1 tiene un tope de unidades que no es un número entero.');
    const ilegible = { ...ok, lineas: [ok.lineas[0], { ...ok.lineas[1], topeMonto: 'abc' }] };
    expect(problemaDeEdicion(ilegible)).toBe('La línea 2 tiene un tope de monto que no es un número.');
  });
});
