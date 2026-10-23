import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { BONO } from './sellInFixtures';
import SellInBonosTable from './SellInBonosTable';

const CATEGORIA_PCT = { ...BONO, id: 5, alcance: 'categoria', marca: null, categoria: 'Switches', tipo: 'porcentaje', monto_unit: null, porcentaje: '2.5000' };
const MODELOS = { ...BONO, id: 6, alcance: 'modelos', marca: null, modelos: [{ item_id: 1 }, { item_id: 2 }] };
const FACTURA = { ...BONO, id: 7, alcance: 'factura', marca: null, pedido_id: 20, pedido_numero: 'P-00020' };

const fila = (texto) => screen.getByText(texto).closest('tr');

describe('SellInBonosTable', () => {
  it('shows what each bonus reaches and how it pays', () => {
    render(<SellInBonosTable bonos={[BONO, CATEGORIA_PCT, MODELOS, FACTURA]} selectedId={null} onSelect={vi.fn()} />);

    expect(screen.getByRole('columnheader', { name: 'Alcance' })).toBeInTheDocument();
    expect(within(fila('Marca TP-LINK')).getByText('USD 3,00 / u')).toBeInTheDocument();
    expect(within(fila('Categoría Switches')).getByText('2,5 % de lo facturado')).toBeInTheDocument();
    expect(fila('2 modelos')).toBeInTheDocument();
    expect(fila('Factura N° P-00020')).toBeInTheDocument();
  });
});
