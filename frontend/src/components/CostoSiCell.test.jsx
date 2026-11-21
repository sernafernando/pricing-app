import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import CostoSiCell from './CostoSiCell';

// The Publicaciones ML format; Productos passes its own (`USD $17.04`).
const format = (monto, moneda) => `${moneda} ${monto.toFixed(2).replace('.', ',')}`;

// interfaz §6: the `costo_si` payload of a product row.
const USD_SI = {
  costo: 16.4266,
  moneda: 'USD',
  fuente: 'costo_si',
  desde: '2026-11-02',
  tipo_cambio: 1570,
  tipo_cambio_fecha: '2026-11-20',
  costo_ars: 25789.76,
};
const ARS_LISTA = { costo: 20000, moneda: 'ARS', fuente: 'lista', desde: null, tipo_cambio: null, tipo_cambio_fecha: null, costo_ars: 20000 };

const cell = (container) => container.firstChild;

describe('CostoSiCell', () => {
  it('shows the costo SI in its own currency, on one line, never converted', () => {
    const { container } = render(<CostoSiCell costoSi={USD_SI} format={format} />);
    expect(cell(container)).toHaveTextContent(/^USD 16,43$/);
  });

  it('dates the step and gives the pesos with their rate and its date in the tooltip', () => {
    const { container } = render(<CostoSiCell costoSi={USD_SI} format={format} />);
    expect(cell(container).getAttribute('title')).toBe(
      'Costo SI desde 02/11/26\nEn pesos: ARS 25789,76 (TC 1570 del 20/11/26)',
    );
  });

  it('marks a list cost that stands in for a missing costo SI (Q1)', () => {
    const { container } = render(<CostoSiCell costoSi={ARS_LISTA} format={format} />);
    expect(cell(container)).toHaveTextContent('ARS 20000,00 lista');
    expect(cell(container).getAttribute('title')).toBe('Sin costo SI: es el costo de lista');
  });

  it('a USD cost without a rate keeps its dollars and says its pesos are unknown, never 0 (interfaz §7)', () => {
    const sinTc = { ...USD_SI, tipo_cambio: null, tipo_cambio_fecha: null, costo_ars: null };
    const { container } = render(<CostoSiCell costoSi={sinTc} format={format} />);
    expect(cell(container)).toHaveTextContent(/^USD 16,43$/);
    expect(cell(container).getAttribute('title')).toContain('Sin tipo de cambio: no se sabe en pesos');
    expect(cell(container).getAttribute('title')).not.toMatch(/ARS 0/);
  });

  it('a rate without a date (the caller passed it) still shows, undated', () => {
    const { container } = render(<CostoSiCell costoSi={{ ...USD_SI, tipo_cambio_fecha: null }} format={format} />);
    expect(cell(container).getAttribute('title')).toContain('En pesos: ARS 25789,76 (TC 1570)');
  });

  it('an unknown cost reads "—", never 0', () => {
    for (const costoSi of [null, undefined]) {
      const { container, unmount } = render(<CostoSiCell costoSi={costoSi} format={format} />);
      expect(cell(container)).toHaveTextContent(/^—$/);
      unmount();
    }
  });
});
