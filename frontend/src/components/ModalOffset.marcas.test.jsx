/**
 * marcas-sin-stock S3: editing an offset whose brand is now hidden from the brand options keeps showing that brand.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ModalOffset from './ModalOffset';
import api from '../services/api';

const OFFSET_OCULTA = {
  id: 7,
  marca: 'OCULTA',
  tipo_offset: 'monto_fijo',
  monto: 100,
  moneda: 'ARS',
  fecha_desde: '2026-01-01',
  aplica_ml: true,
  aplica_fuera: true,
  aplica_tienda_nube: true,
};

const FILTROS = { marcas: ['HP', 'TP-LINK'], categorias: [], subcategorias: [] };

beforeEach(() => {
  api.get.mockImplementation((url) => {
    if (url === '/offsets-ganancia') return Promise.resolve({ data: [OFFSET_OCULTA] });
    if (url === '/tipo-cambio/actual') return Promise.resolve({ data: {} });
    return Promise.resolve({ data: [] });
  });
});

const renderModal = () =>
  render(<ModalOffset mostrar onClose={vi.fn()} onSave={vi.fn()} filtrosDisponibles={FILTROS} fechaDesde="2026-01-01" fechaHasta="2026-01-31" />);

describe('ModalOffset brand picker', () => {
  it('shows the edited offset brand even when it is not in the brand options', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(await screen.findByTitle('Editar'));

    const select = screen.getByDisplayValue('OCULTA');
    expect(select.tagName).toBe('SELECT');
    expect(select.value).toBe('OCULTA');
  });

  it('offers only the server brands when no hidden brand is selected', async () => {
    renderModal();
    await screen.findByTitle('Editar');

    const select = screen.getByDisplayValue('Seleccionar marca...');
    const values = [...select.options].map((option) => option.value).filter(Boolean);
    expect(values).toEqual(['HP', 'TP-LINK']);
  });
});
