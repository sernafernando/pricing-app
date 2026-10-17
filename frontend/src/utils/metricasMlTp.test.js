import { describe, it, expect } from 'vitest';
import { TP_MARKUP_HINT, tpCellState, tpErrorMessage, tpRequestParams, tpSoloSortKey } from './metricasMlTp';

describe('tpRequestParams', () => {
  it('asks for costos_tp only while the toggle is on', () => {
    expect(tpRequestParams(true)).toEqual({ costos_tp: true });
    expect(tpRequestParams(false)).toEqual({});
  });
});

describe('tpErrorMessage', () => {
  it('explains a 403 and a 503 in words, and ignores anything else', () => {
    expect(tpErrorMessage(403)).toBe('No tenés permiso para ver los costos TP. Se desactivó "Costos TP".');
    expect(tpErrorMessage(503)).toBe(
      'Los costos TP no están disponibles: no hay una tienda TP-Link configurada. Se desactivó "Costos TP".',
    );
    expect(tpErrorMessage(500)).toBeNull();
    expect(tpErrorMessage(undefined)).toBeNull();
  });
});

describe('tpCellState', () => {
  it('a known Total TP is complete when no TP line lacks its cost', () => {
    expect(tpCellState(100, 0)).toEqual({ known: true, incompletos: 0, kind: 'complete' });
  });

  it('a known Total TP with lines lacking a TP cost is partial', () => {
    expect(tpCellState(100, 2)).toEqual({ known: true, incompletos: 2, kind: 'partial' });
  });

  it('an unknown Total TP with lines lacking a TP cost is incomplete, never 0', () => {
    expect(tpCellState(null, 1)).toEqual({ known: false, incompletos: 1, kind: 'incomplete' });
  });

  it('no TP figure and nothing missing means the row sold nothing in the TP store', () => {
    expect(tpCellState(null, 0)).toEqual({ known: false, incompletos: 0, kind: 'none' });
    expect(tpCellState(undefined, undefined)).toEqual({ known: false, incompletos: 0, kind: 'none' });
  });
});

it('the markup hint names the TP cost', () => {
  expect(TP_MARKUP_HINT).toBe('Usa el costo TP en las operaciones de la tienda TP-Link');
});

describe('tpSoloSortKey', () => {
  it('never sorts a tplink.solo board by Total Gauss: Total TP takes its place', () => {
    expect(tpSoloSortKey('total_gauss', true)).toBe('total_tp');
    expect(tpSoloSortKey('gross', true)).toBe('gross');
  });

  it('leaves everyone else alone', () => {
    expect(tpSoloSortKey('total_gauss', false)).toBe('total_gauss');
  });
});
