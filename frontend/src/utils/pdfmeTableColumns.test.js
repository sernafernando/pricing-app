import { describe, it, expect } from 'vitest';
import { dropLastTableColumn, withOptionalLastColumn } from './pdfmeTableColumns';

const makeTemplate = () => ({
  basePdf: { width: 210, height: 297 },
  schemas: [
    [
      { name: '__titulo__', type: 'text', content: 'REGISTRO DE HORARIOS' },
      {
        name: 'tabla_dias_1',
        type: 'table',
        head: ['Día', 'Entrada', 'Salida', 'Hs'],
        headWidthPercentages: [34, 23, 23, 20],
      },
      {
        name: 'tabla_dias_2',
        type: 'table',
        head: ['Día', 'Entrada', 'Salida', 'Hs'],
        headWidthPercentages: [34, 23, 23, 20],
      },
    ],
  ],
});

const tablas = (template) => template.schemas[0].filter((f) => f.type === 'table');

describe('dropLastTableColumn', () => {
  it('saca la última columna de TODAS las tablas', () => {
    const result = dropLastTableColumn(makeTemplate());

    for (const tabla of tablas(result)) {
      expect(tabla.head).toEqual(['Día', 'Entrada', 'Salida']);
      expect(tabla.headWidthPercentages).toHaveLength(3);
    }
  });

  it('los anchos restantes siguen sumando EXACTAMENTE 100', () => {
    const result = dropLastTableColumn(makeTemplate());

    for (const tabla of tablas(result)) {
      const suma = tabla.headWidthPercentages.reduce((acc, w) => acc + w, 0);
      expect(suma).toBe(100);
    }
  });

  it('reescala proporcionalmente (34/23/23 sobre 80 → 42.5/28.75/28.75)', () => {
    const result = dropLastTableColumn(makeTemplate());
    expect(tablas(result)[0].headWidthPercentages).toEqual([42.5, 28.75, 28.75]);
  });

  it('mantiene la suma exacta con anchos que no dividen redondo', () => {
    const template = {
      schemas: [
        [
          {
            name: 't',
            type: 'table',
            head: ['a', 'b', 'c', 'd'],
            headWidthPercentages: [33, 33, 27, 7],
          },
        ],
      ],
    };
    const result = dropLastTableColumn(template);
    const suma = result.schemas[0][0].headWidthPercentages.reduce((acc, w) => acc + w, 0);
    expect(suma).toBe(100);
  });

  it('NO muta el template original', () => {
    const original = makeTemplate();
    const snapshot = JSON.stringify(original);

    dropLastTableColumn(original);

    expect(JSON.stringify(original)).toBe(snapshot);
  });

  it('deja intactos los campos que no son tabla', () => {
    const result = dropLastTableColumn(makeTemplate());
    expect(result.schemas[0][0]).toEqual({
      name: '__titulo__',
      type: 'text',
      content: 'REGISTRO DE HORARIOS',
    });
  });

  it('no deja una tabla sin columnas', () => {
    const template = {
      schemas: [[{ name: 't', type: 'table', head: ['única'], headWidthPercentages: [100] }]],
    };
    const result = dropLastTableColumn(template);
    expect(result.schemas[0][0].head).toEqual(['única']);
    expect(result.schemas[0][0].headWidthPercentages).toEqual([100]);
  });

  it('tolera tablas sin headWidthPercentages', () => {
    const template = { schemas: [[{ name: 't', type: 'table', head: ['a', 'b'] }]] };
    const result = dropLastTableColumn(template);
    expect(result.schemas[0][0].head).toEqual(['a']);
    expect(result.schemas[0][0].headWidthPercentages).toBeUndefined();
  });
});

describe('withOptionalLastColumn', () => {
  it('con incluir=true devuelve el template sin tocar', () => {
    const template = makeTemplate();
    const result = withOptionalLastColumn(template, true);

    expect(result).toBe(template);
    expect(tablas(result)[0].head).toEqual(['Día', 'Entrada', 'Salida', 'Hs']);
  });

  it('con incluir=false saca la columna', () => {
    const result = withOptionalLastColumn(makeTemplate(), false);
    expect(tablas(result)[0].head).toEqual(['Día', 'Entrada', 'Salida']);
  });
});
