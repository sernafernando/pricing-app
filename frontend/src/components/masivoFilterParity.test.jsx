/**
 * Parity: a bulk operation must run over the SAME set the listing shows.
 *
 * The cross-DB filters (promos, wholesale tiers) used to be handed to these
 * modals in `filtrosActivos` and dropped on the floor, so "aplicar filtros"
 * quietly meant "some of them". These tests pin the ones the backend now
 * folds; a filter added to the listing and forgotten here fails as a
 * parity gap, not as a silent widening.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { buildFilterQueryString } from './exportFilterParams';
import CalcularWebModal from './CalcularWebModal';
import CalcularPVPModal from './CalcularPVPModal';
import api from '../services/api';

vi.mock('../services/api', () => ({
  default: { post: vi.fn().mockResolvedValue({ data: { procesados: 1 } }), get: vi.fn() },
}));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: () => true }),
}));

// Every cross-DB filter the listing can send, in the `filtrosActivos` shape
// Productos.jsx builds.
const FILTROS_ACTIVOS = {
  filtroPxq: 'con_pxq',
  promo_tipos: 'SMART,DEAL',
  promo_estado: 'aplicada',
  marcas: ['ACME'],
};

describe('ExportModal.buildFilterQueryString — cross-DB filters travel', () => {
  it('sends con_pxq when the wholesale filter is on', () => {
    expect(buildFilterQueryString(FILTROS_ACTIVOS)).toContain('con_pxq=true');
  });

  it('sends promo_tipos and promo_estado', () => {
    const qs = buildFilterQueryString(FILTROS_ACTIVOS);
    expect(qs).toContain('promo_tipos=SMART%2CDEAL');
    expect(qs).toContain('promo_estado=aplicada');
  });

  it('sends the legacy type-agnostic promo booleans when no type is selected', () => {
    expect(buildFilterQueryString({ con_promo_aplicada: true })).toContain('con_promo_aplicada=true');
    expect(buildFilterQueryString({ con_promo_sin_aplicar: true })).toContain('con_promo_sin_aplicar=true');
  });

  it('sends nothing when the filters are off', () => {
    const qs = buildFilterQueryString({ marcas: ['ACME'] });
    expect(qs).not.toContain('con_pxq');
    expect(qs).not.toContain('promo_');
  });
});

async function runBulk(element) {
  vi.stubGlobal('confirm', () => true);
  render(element);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: /calcular/i }));
  return api.post.mock.calls.at(-1)[1].filtros;
}

describe('Bulk price calculations narrow by the same cross-DB filters', () => {
  beforeEach(() => vi.clearAllMocks());

  it('CalcularWebModal sends con_pxq + promo params', async () => {
    const filtros = await runBulk(
      <CalcularWebModal onClose={() => {}} onSuccess={() => {}} filtrosActivos={FILTROS_ACTIVOS} showToast={() => {}} />,
    );
    expect(filtros.con_pxq).toBe(true);
    expect(filtros.promo_tipos).toBe('SMART,DEAL');
    expect(filtros.promo_estado).toBe('aplicada');
  });

  it('CalcularPVPModal sends con_pxq + promo params', async () => {
    const filtros = await runBulk(
      <CalcularPVPModal onClose={() => {}} onSuccess={() => {}} filtrosActivos={FILTROS_ACTIVOS} showToast={() => {}} />,
    );
    expect(filtros.con_pxq).toBe(true);
    expect(filtros.promo_tipos).toBe('SMART,DEAL');
    expect(filtros.promo_estado).toBe('aplicada');
  });
});
