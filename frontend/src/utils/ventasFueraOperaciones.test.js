/**
 * ODD `vpf-operaciones` S2/S3e: the query the PDF operations list sends (contract of GET /operaciones/listado),
 * the facets it reads and the shape a PDF line takes to open the reused ModalEditarCosto.
 */
import { describe, it, expect } from 'vitest';
import { buildListadoParams, facetas, lineaParaModalCosto, CAUSAS_SIN_PRODUCTO } from './ventasFueraOperaciones';
import { OPERACION_MIXTA } from '../components/ventasFueraOperaciones/fixtures';

const BASE = { desde: '2026-11-01', hasta: '2026-11-18' };

describe('buildListadoParams', () => {
  it('sends only the dates, cost basis, page, size and sort when no filter is on', () => {
    expect(buildListadoParams(BASE)).toEqual({
      desde: '2026-11-01',
      hasta: '2026-11-18',
      costo: 'costo_d',
      page: 1,
      page_size: 50,
      sort: 'fecha_desc',
    });
  });

  it('maps every filter to the contract names', () => {
    expect(
      buildListadoParams({
        ...BASE,
        empresa: 'Empresa Demo SA',
        vendedor: 'Vendedor Uno',
        q: '  monitor ',
        tipo: 'Nc',
        sinProducto: true,
        revisar: true,
        costo: 'costo',
        page: 3,
        pageSize: 100,
        sort: 'markup_asc',
      }),
    ).toEqual({
      desde: '2026-11-01',
      hasta: '2026-11-18',
      empresas: ['Empresa Demo SA'],
      vendedores: ['Vendedor Uno'],
      q: 'monitor',
      tipo: 'Nc',
      sin_producto: true,
      revisar: true,
      costo: 'costo',
      page: 3,
      page_size: 100,
      sort: 'markup_asc',
    });
  });
});

describe('facetas', () => {
  it('reads [{valor, cantidad}], plain names and a {name: count} map alike', () => {
    expect(facetas([{ valor: 'A', cantidad: 2 }, 'B'])).toEqual({ options: ['A', 'B'], counts: { A: 2, B: undefined } });
    expect(facetas({ A: 3 })).toEqual({ options: ['A'], counts: { A: 3 } });
    expect(facetas(undefined)).toEqual({ options: [], counts: {} });
  });
});

describe('lineaParaModalCosto', () => {
  it('gives the modal the fields it reads, from the line and its document', () => {
    const [linea] = OPERACION_MIXTA.lineas;
    expect(lineaParaModalCosto(linea, OPERACION_MIXTA)).toEqual({
      codigo_item: 'DEMO-100',
      fecha: '2026-11-12',
      descripcion: 'DEMO-100 Monitor de prueba 24"',
      cantidad: 2,
      precio_unitario_sin_iva: 30000,
      precio_final_sin_iva: 60000,
      costo_unitario: 21000,
      costo_pesos_sin_iva: 44730,
    });
  });

  it('never divides by a zero quantity', () => {
    const linea = { ...OPERACION_MIXTA.lineas[1], cantidad: 0 };
    const modal = lineaParaModalCosto(linea, OPERACION_MIXTA);
    expect(modal.precio_unitario_sin_iva).toBe(15000);
    expect(modal.costo_unitario).toBe(0);
  });
});

describe('CAUSAS_SIN_PRODUCTO', () => {
  it('names the three causes in plain Spanish', () => {
    expect(Object.keys(CAUSAS_SIN_PRODUCTO)).toEqual(['sin_codigo_manual', 'sin_codigo', 'codigo_no_encontrado']);
  });
});
