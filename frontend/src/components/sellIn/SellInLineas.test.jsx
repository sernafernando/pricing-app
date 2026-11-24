import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { COMPRA_AIR_TP_ARS, COMPRA_ARS, COMPRA_DISTECNA, COMPRA_USD_ANULADA } from './sellInFixtures';
import SellInLineas from './SellInLineas';

const encabezados = () => screen.getAllByRole('columnheader').map((th) => th.textContent);
const celdas = (fila) => within(fila).getAllByRole('cell').map((td) => td.textContent);
/** A line is its own row group: the product on a full-width row, its numbers on the row below. */
const filaDe = (codigo) => screen.getByText(codigo).closest('tbody');

describe('SellInLineas', () => {
  it('shows the unit sell in next to the unit costs and labels the amount as the line total (S5)', () => {
    // Distecna compra 28 / item 22: 53,713.80 is the TOTAL of 200 u, not a unit amount beside the unit cost.
    render(<SellInLineas compra={COMPRA_DISTECNA} />);
    expect(encabezados()).toEqual(['Unid.', 'Costo antes', 'Sell in unit.', 'Costo después', 'Monto asignado (total línea)']);
    expect(celdas(filaDe('6935364080433'))).toEqual([
      '200',
      '$ 26.856,90',
      '$ 268,57',
      '$ 26.588,33',
      '$ 53.713,80USD 34,00 a TC 1.580', // the total with its USD equivalent below (S3)
    ]);
  });

  it('puts each product on its own full-width row so the numbers fit the side panel (S5 layout)', () => {
    // At 1440 px with the sidebar open the panel's lines box is ~524 px: a product column beside five amounts pushed
    // the line total off-screen. The product (any description length) heads its line's row group across every column.
    render(<SellInLineas compra={COMPRA_ARS} />);
    const grupos = screen.getAllByRole('rowgroup').filter((g) => g.tagName === 'TBODY');
    expect(grupos).toHaveLength(2);
    const [producto, numeros] = within(grupos[0]).getAllByRole('row');
    const cabecera = within(producto).getByRole('rowheader');
    expect(cabecera).toHaveTextContent('Switch 8 bocas SW-8');
    expect(cabecera).toHaveAttribute('colspan', '5');
    expect(celdas(numeros)).toEqual(['10', '$ 100,00', '$ 25,00', '$ 75,00', '$ 250,00']);
  });

  it('shows each line cost before and after as the purchase reports it, in its currency (kept)', () => {
    render(<SellInLineas compra={COMPRA_ARS} />);
    const fila = filaDe('SW-8');
    expect(within(fila).getByText('$ 100,00')).toBeInTheDocument();
    expect(within(fila).getByText('$ 75,00')).toBeInTheDocument();
    expect(within(fila).getByText('$ 250,00')).toBeInTheDocument();
    expect(screen.getByText(/Reparto proporcional · el costo después entra en el costo SI del producto\./)).toBeInTheDocument();
  });

  it('shows an ARS line total with its USD equivalent below, at the purchase rate (S3)', () => {
    // Compra 25 in ARS: 162,062.25 / 1570 = USD 103.22, the amount that was stored in USD before.
    render(<SellInLineas compra={COMPRA_AIR_TP_ARS} />);
    const total = within(filaDe('1210002615013')).getByText('$ 162.062,25').closest('td');
    expect(within(total).getByText('USD 103,22 a TC 1.570')).toBeInTheDocument();
  });

  it('shows a USD line total alone, with no conversion line (kept)', () => {
    render(<SellInLineas compra={COMPRA_USD_ANULADA} />);
    const total = within(filaDe('AP-1')).getByText('USD 2,00').closest('td');
    expect(total).toHaveTextContent(/^USD 2,00$/);
  });
});
