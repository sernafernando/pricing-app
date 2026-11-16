/**
 * The Cobranza box of a tactical row (handoffs/tactical-cobranza-tarea.md S3): Fecha de cobro *, Medio (Nota de
 * crédito → Número de NC, Fondo en distribuidor → Distribuidor, Otro → Detalle), Observaciones; Guardar marks it
 * collected, Deshacer cobro undoes it (PUT / DELETE /api/tacticals/{id}/cobranza, PR #2182).
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TacticalCobranza from './TacticalCobranza';
import { tacticalsAPI } from '../../services/tacticalsAPI';
import { COBRANZA_FONDO, TACTICAL_REBATE } from './tacticalsFixtures';

vi.mock('../../services/tacticalsAPI', () => ({ tacticalsAPI: { cobrar: vi.fn(), deshacerCobro: vi.fn() } }));

const PENDIENTE = { ...TACTICAL_REBATE, cobranza: null };
const COBRADO = { ...TACTICAL_REBATE, cobranza: COBRANZA_FONDO };

const renderizar = (tactical, extra = {}) => {
  const props = { tactical, onGuardado: vi.fn(), onCerrar: vi.fn(), ...extra };
  render(<TacticalCobranza {...props} />);
  return props;
};

beforeEach(() => {
  vi.clearAllMocks();
  tacticalsAPI.cobrar.mockResolvedValue({ data: COBRADO });
  tacticalsAPI.deshacerCobro.mockResolvedValue({ data: PENDIENTE });
});

describe('TacticalCobranza', () => {
  it('shows the field of each medium only when it is chosen', async () => {
    renderizar(PENDIENTE);

    expect(screen.getByRole('group', { name: 'Medio' })).toBeInTheDocument();
    for (const campo of ['Número de NC', 'Distribuidor', 'Detalle']) expect(screen.queryByLabelText(campo)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Nota de crédito' }));
    expect(screen.getByLabelText('Número de NC')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fondo en distribuidor' }));
    expect(screen.getByLabelText('Distribuidor')).toBeInTheDocument();
    expect(screen.queryByLabelText('Número de NC')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Otro' }));
    expect(screen.getByLabelText('Detalle')).toBeInTheDocument();
  });

  it('refuses to save without the date and sends nothing', async () => {
    const props = renderizar(PENDIENTE);

    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(screen.getByRole('alert')).toHaveTextContent('La fecha de cobro es obligatoria.');
    expect(tacticalsAPI.cobrar).not.toHaveBeenCalled();
    expect(props.onGuardado).not.toHaveBeenCalled();
  });

  it('saves the date, the medium with its detail and the notes, then tells the list', async () => {
    const props = renderizar(PENDIENTE);

    await userEvent.type(screen.getByLabelText('Fecha de cobro *'), '2026-11-09');
    await userEvent.click(screen.getByRole('button', { name: 'Nota de crédito' }));
    await userEvent.type(screen.getByLabelText('Número de NC'), '0003-00012345');
    await userEvent.type(screen.getByLabelText('Observaciones'), 'NC de noviembre');
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(tacticalsAPI.cobrar).toHaveBeenCalledWith(3, {
      fecha_cobro: '2026-11-09',
      medio: 'nota_credito',
      nc_numero: '0003-00012345',
      distribuidor: null,
      otro_detalle: null,
      observaciones: 'NC de noviembre',
      tipo_cambio: null, // only a sell in in USD al cobro takes the collection rate
    });
    expect(props.onGuardado).toHaveBeenCalled();
  });

  it('opens a collected tactical with its record and can undo it; a new one has no Deshacer', async () => {
    const props = renderizar(COBRADO);

    expect(screen.getByLabelText('Fecha de cobro *')).toHaveValue('2026-11-09');
    expect(screen.getByRole('button', { name: 'Fondo en distribuidor' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Distribuidor')).toHaveValue('Grupo Núcleo');
    await userEvent.click(screen.getByRole('button', { name: 'Deshacer cobro' }));

    expect(tacticalsAPI.deshacerCobro).toHaveBeenCalledWith(3);
    expect(props.onGuardado).toHaveBeenCalled();
  });

  it("shows the server's refusal and keeps the box open", async () => {
    tacticalsAPI.cobrar.mockRejectedValue({ response: { status: 403, data: { detail: 'Falta el permiso sell_in.gestionar' } } });
    const props = renderizar(COBRADO);

    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Falta el permiso sell_in.gestionar');
    expect(props.onGuardado).not.toHaveBeenCalled();
  });

  it('Cancelar closes without saving', async () => {
    const props = renderizar(PENDIENTE, { onGuardado: vi.fn() });
    expect(screen.queryByRole('button', { name: 'Deshacer cobro' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Cancelar' }));

    expect(props.onCerrar).toHaveBeenCalled();
    expect(tacticalsAPI.cobrar).not.toHaveBeenCalled();
  });
});

// Tactical sell in USD, owner: "Ponelo donde se carga el cobro": the rate the brand paid at goes with the collection.
describe('TacticalCobranza: tipo de cambio del cobro', () => {
  const USD_AL_COBRO = { ...PENDIENTE, tipo: 'sell_in', moneda: 'USD', tc_modo: 'al_cobro', pide_tc_cobro: true };

  it('asks for it only on a tactical that takes one', () => {
    renderizar(PENDIENTE);
    expect(screen.queryByLabelText('Tipo de cambio del cobro *')).not.toBeInTheDocument();
  });

  it('requires it and sends it as a number', async () => {
    const props = renderizar(USD_AL_COBRO);
    await userEvent.type(screen.getByLabelText('Fecha de cobro *'), '2026-11-09');

    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Falta el tipo de cambio del cobro (pesos por dólar).');
    expect(tacticalsAPI.cobrar).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText('Tipo de cambio del cobro *'), '1.350,5');
    await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(tacticalsAPI.cobrar).toHaveBeenCalledWith(USD_AL_COBRO.id, expect.objectContaining({ tipo_cambio: 1350.5 }));
    expect(props.onGuardado).toHaveBeenCalled();
  });
});
