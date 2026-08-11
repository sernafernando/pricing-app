/**
 * useDocumentGenerator — contrato de `generatePdf`.
 *
 * Lo que protege este archivo es la COMPATIBILIDAD HACIA ATRÁS: seis pantallas
 * llaman `generatePdf(templateId, unaEntidad)` y tienen que seguir produciendo
 * EXACTAMENTE un registro en `inputs`. El soporte multi-registro es aditivo.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const { obtenerMock, generateMock } = vi.hoisted(() => ({
  obtenerMock: vi.fn(),
  generateMock: vi.fn(),
}));

vi.mock('../services/api', () => ({
  documentTemplatesAPI: {
    listar: vi.fn().mockResolvedValue({ data: [] }),
    obtener: obtenerMock,
  },
}));

vi.mock('@pdfme/generator', () => ({ generate: generateMock }));
vi.mock('../utils/pdfmePlugins', () => ({ plugins: { text: {} } }));
vi.mock('../utils/pdfmeFonts', () => ({ getFont: () => Promise.resolve({}) }));

const { useDocumentGenerator } = await import('./useDocumentGenerator');

const TEMPLATE_JSON = {
  basePdf: { width: 210, height: 297 },
  schemas: [
    [
      { name: '__titulo__', type: 'text', content: 'REGISTRO' },
      { name: 'legajo', type: 'text', content: '' },
      {
        name: 'tabla_dias_1',
        type: 'table',
        content: '',
        head: ['Día', 'Entrada', 'Salida', 'Hs'],
        headWidthPercentages: [34, 23, 23, 20],
        headStyles: { padding: 3, borderWidth: 0 },
        bodyStyles: {},
      },
    ],
  ],
};

beforeEach(() => {
  obtenerMock.mockResolvedValue({ data: { template_json: TEMPLATE_JSON } });
  generateMock.mockResolvedValue(new Uint8Array([1, 2, 3]));
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:fake');
  globalThis.URL.revokeObjectURL = vi.fn();
  vi.spyOn(window, 'open').mockImplementation(() => null);
});

describe('useDocumentGenerator.generatePdf', () => {
  it('una sola entidad produce EXACTAMENTE un registro de inputs', async () => {
    const { result } = renderHook(() => useDocumentGenerator('rrhh'));

    await act(async () => {
      await result.current.generatePdf(7, { legajo: '0042', nombre: 'Juan' });
    });

    expect(generateMock).toHaveBeenCalledTimes(1);
    const { inputs } = generateMock.mock.calls[0][0];
    expect(Array.isArray(inputs)).toBe(true);
    expect(inputs).toHaveLength(1);
    expect(inputs[0].legajo).toBe('0042');
    // Los defaults estáticos del template siguen mergeados en el registro.
    expect(inputs[0].__titulo__).toBe('REGISTRO');
    expect(result.current.error).toBeNull();
  });

  it('un array de N entidades produce N registros de inputs', async () => {
    const { result } = renderHook(() => useDocumentGenerator('rrhh'));

    await act(async () => {
      await result.current.generatePdf(7, [{ legajo: '1' }, { legajo: '2' }, { legajo: '3' }]);
    });

    const { inputs } = generateMock.mock.calls[0][0];
    expect(inputs).toHaveLength(3);
    expect(inputs.map((i) => i.legajo)).toEqual(['1', '2', '3']);
    // Los defaults se mergean en CADA registro, no solo en el primero.
    expect(inputs.every((i) => i.__titulo__ === 'REGISTRO')).toBe(true);
  });

  it('no muta el template_json que devolvió la API', async () => {
    const { result } = renderHook(() => useDocumentGenerator('rrhh'));
    const tabla = TEMPLATE_JSON.schemas[0][2];

    await act(async () => {
      await result.current.generatePdf(7, { legajo: '0042' });
    });

    expect(tabla.columnStyles).toBeUndefined();
    expect(tabla.headStyles.padding).toBe(3);
    // ...pero el template que recibe pdfme sí quedó normalizado.
    const { template } = generateMock.mock.calls[0][0];
    expect(template.schemas[0][2].columnStyles).toEqual({});
    expect(template.schemas[0][2].headStyles.padding).toEqual({ top: 3, right: 3, bottom: 3, left: 3 });
  });

  it('aplica transformTemplate antes de generar', async () => {
    const { result } = renderHook(() => useDocumentGenerator('rrhh'));
    const transformTemplate = vi.fn((t) => ({
      ...t,
      schemas: [t.schemas[0].filter((f) => f.type !== 'table')],
    }));

    await act(async () => {
      await result.current.generatePdf(7, { legajo: '0042' }, { transformTemplate });
    });

    expect(transformTemplate).toHaveBeenCalledWith(TEMPLATE_JSON);
    const { template } = generateMock.mock.calls[0][0];
    expect(template.schemas[0].some((f) => f.type === 'table')).toBe(false);
  });

  it('con un array vacío no llama a pdfme y reporta el error', async () => {
    const { result } = renderHook(() => useDocumentGenerator('rrhh'));

    await act(async () => {
      await result.current.generatePdf(7, []);
    });

    expect(generateMock).not.toHaveBeenCalled();
    expect(result.current.error).toBe('No hay datos para generar el documento');
    expect(result.current.generating).toBe(false);
  });

  it('propaga el error de pdfme sin dejar `generating` colgado', async () => {
    generateMock.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useDocumentGenerator('rrhh'));

    await act(async () => {
      await result.current.generatePdf(7, { legajo: '0042' });
    });

    expect(result.current.error).toBe('boom');
    expect(result.current.generating).toBe(false);
  });
});
