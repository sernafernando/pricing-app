/**
 * Tacticals approval S10 on the offsets screen: a new profit offset waits for approval (`POST /offsets-ganancia`
 * stores it `pendiente`), and a money edit of an approved one sends it back. The modal says so: a pending badge on its
 * row, a note on create, a warning when editing an approved one. Saving still creates and updates as before.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ModalOffset from './ModalOffset';
import api from '../services/api';

const BASE = {
  tipo_offset: 'monto_fijo',
  monto: 100,
  moneda: 'ARS',
  fecha_desde: '2026-01-01',
  aplica_ml: true,
  aplica_fuera: true,
  aplica_tienda_nube: true,
};
const APROBADO = { ...BASE, id: 7, marca: 'HP', descripcion: 'Rebate HP', estado: 'activa' };
const PENDIENTE = { ...BASE, id: 8, marca: 'TP-LINK', descripcion: 'Rebate TP-Link', estado: 'pendiente' };

const FILTROS = { marcas: ['HP', 'TP-LINK'], categorias: [], subcategorias: [] };

beforeEach(() => {
  api.get.mockImplementation((url) => {
    if (url === '/offsets-ganancia') return Promise.resolve({ data: [APROBADO, PENDIENTE] });
    if (url === '/tipo-cambio/actual') return Promise.resolve({ data: {} });
    return Promise.resolve({ data: [] });
  });
  api.post.mockResolvedValue({ data: {} });
  api.put.mockResolvedValue({ data: {} });
});

const renderModal = () =>
  render(<ModalOffset mostrar onClose={vi.fn()} onSave={vi.fn()} filtrosDisponibles={FILTROS} fechaDesde="2026-01-01" fechaHasta="2026-01-31" />);

const fila = async (texto) => (await screen.findByText(texto)).closest('tr');

describe('ModalOffset approval (tacticals approval S10)', () => {
  it('marks a pending offset with the pending badge and an approved one with none', async () => {
    renderModal();

    expect(within(await fila('Rebate TP-Link')).getByText('Pendiente de aprobación')).toBeInTheDocument();
    expect(within(await fila('Rebate HP')).queryByText('Pendiente de aprobación')).not.toBeInTheDocument();
  });

  it('a new offset says it waits for approval and applies to nothing until then', async () => {
    renderModal();
    await fila('Rebate HP');

    expect(screen.getByRole('note')).toHaveTextContent(
      'Al crearlo queda pendiente de aprobación: no aplica a la rentabilidad ni consume topes hasta que lo aprueben.',
    );
  });

  it('editing an approved offset warns that a money change sends it back; a pending one stays pending', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(within(await fila('Rebate HP')).getByTitle('Editar'));
    expect(screen.getByRole('note')).toHaveTextContent(
      'Está aprobado: si cambiás monto, porcentaje, fechas, topes, canales o alcance vuelve a quedar pendiente de aprobación',
    );

    await user.click(within(await fila('Rebate TP-Link')).getByTitle('Editar'));
    expect(screen.getByRole('note')).toHaveTextContent('Sigue pendiente de aprobación: no aplica hasta que lo aprueben.');

    await user.click(within(await fila('Rebate TP-Link')).getByTitle('Clonar'));
    expect(screen.getByRole('note')).toHaveTextContent('Al crearlo queda pendiente de aprobación');
  });

  it('still updates an edited offset and creates a cloned one, as before', async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(within(await fila('Rebate HP')).getByTitle('Editar'));
    await user.click(screen.getByRole('button', { name: 'Actualizar Offset' }));
    expect(api.put).toHaveBeenCalledWith('/offsets-ganancia/7', expect.objectContaining({ marca: 'HP', monto: 100 }));

    await user.click(within(await fila('Rebate HP')).getByTitle('Clonar'));
    await user.click(screen.getByRole('button', { name: 'Guardar Offset' }));
    expect(api.post).toHaveBeenCalledWith('/offsets-ganancia', expect.objectContaining({ marca: 'HP', monto: 100 }));
  });
});
