/**
 * Panel footer (publicaciones-ml-vista P13a.T4): how fresh the data is, and the
 * "Resincronizar" button for whoever may manage the store. A failure never
 * clears what the panel shows (S60.3).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelFooter from './PanelFooter';
import { readDetail } from './detailModel';
import { publicacionesMlAPI } from '../../../services/api';
import { DETAIL_RESPONSE, FRESHNESS, makeDetail } from '../../../test/visual/publicacionesMlFixtures';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { enqueue: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status } });
const ENQUEUED = {
  enqueued: 1,
  lane: 0,
  resources: ['bundle', 'replenishment'],
  refresh_enabled: true,
  note: null,
  missing_from_bundle_resources: [],
};

const renderFooter = ({ canManage = true, raw = makeDetail({ can_resync: true }), itemId = 'MLA1100000001' } = {}) =>
  render(<PanelFooter key={itemId} detail={readDetail(raw)} itemId={itemId} canManage={canManage} />);
const resync = () => screen.getByRole('button', { name: 'Resincronizar' });

beforeEach(() => {
  // "hace 15 min" for the fixtures' 09:45 check, whatever day the suite runs.
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-10-08T10:00:00Z'));
  publicacionesMlAPI.enqueue.mockReset();
  publicacionesMlAPI.enqueue.mockResolvedValue({ data: ENQUEUED });
});
afterEach(() => vi.useRealTimers());

describe('freshness', () => {
  it('says how long ago each resource was updated', () => {
    renderFooter();
    const freshness = screen.getByRole('list', { name: 'Actualización de los datos' });
    expect(freshness).toHaveTextContent('Publicación');
    expect(freshness).toHaveTextContent('hace 30 min');
    expect(freshness).toHaveTextContent('Reposición');
    expect(freshness).toHaveTextContent('hace 2 h');
  });

  it('a resource never fetched says so instead of a made-up time', () => {
    renderFooter({ raw: makeDetail({ freshness: [{ resource: 'stock', fetched_at: null, last_checked_at: null, state: 'never_fetched' }] }) });
    expect(screen.getByRole('list', { name: 'Actualización de los datos' })).toHaveTextContent('Stock');
    expect(screen.getByRole('list', { name: 'Actualización de los datos' })).toHaveTextContent('sin datos');
  });

  it.each([
    ['error', 'error'],
    ['not_found', 'no existe'],
    ['gone', 'eliminada'],
  ])('a resource in the state %s says so', (state, text) => {
    renderFooter({ raw: makeDetail({ freshness: [{ ...FRESHNESS[1], state }] }) });
    expect(screen.getByRole('list', { name: 'Actualización de los datos' })).toHaveTextContent(text);
  });

  it('names every resource the backend reports in Spanish', () => {
    const resources = ['items', 'description', 'prices', 'sale_price', 'promotions', 'competition', 'moderation', 'performance', 'visits', 'user_product', 'stock', 'family', 'replenishment'];
    renderFooter({ raw: makeDetail({ freshness: resources.map((resource) => ({ ...FRESHNESS[1], resource })) }) });
    const text = screen.getByRole('list', { name: 'Actualización de los datos' }).textContent;
    for (const resource of resources) expect(text).not.toContain(resource);
  });

  it('the tooltip writes the last check as a date, not as raw ISO', () => {
    renderFooter();
    const title = screen.getByText('Publicación').closest('li').getAttribute('title');
    expect(title).toMatch(/Última verificación: \d{2}\/\d{2}\/\d{4}/);
    expect(title).not.toContain('T09:45');
  });

  it('has no list when the backend sent no freshness', () => {
    renderFooter({ raw: makeDetail({ freshness: [] }) });
    expect(screen.queryByRole('list', { name: 'Actualización de los datos' })).not.toBeInTheDocument();
  });
});

describe('who sees "Resincronizar"', () => {
  it('whoever has ml_ops.gestionar and a detail that allows it', () => {
    renderFooter();
    expect(resync()).toBeInTheDocument();
  });

  it('nobody without the permission (S60.2)', () => {
    renderFooter({ canManage: false });
    expect(screen.queryByRole('button', { name: 'Resincronizar' })).not.toBeInTheDocument();
  });

  it('nobody when the backend says the caller cannot resync', () => {
    renderFooter({ raw: DETAIL_RESPONSE });
    expect(screen.queryByRole('button', { name: 'Resincronizar' })).not.toBeInTheDocument();
  });
});

describe('resyncing', () => {
  it('enqueues the bundle and the replenishment of this publication, once (S60.1)', async () => {
    renderFooter();
    await userEvent.click(resync());
    expect(publicacionesMlAPI.enqueue).toHaveBeenCalledTimes(1);
    expect(publicacionesMlAPI.enqueue).toHaveBeenCalledWith({
      item_ids: ['MLA1100000001'],
      resources: ['bundle', 'replenishment'],
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Resincronización pedida');
  });

  it('cannot be sent twice while the request is in flight', async () => {
    publicacionesMlAPI.enqueue.mockReturnValue(new Promise(() => {}));
    renderFooter();
    await userEvent.click(resync());
    expect(resync()).toBeDisabled();
    await userEvent.click(resync());
    expect(publicacionesMlAPI.enqueue).toHaveBeenCalledTimes(1);
  });

  it('names what the store does not collect (missing_from_bundle_resources)', async () => {
    publicacionesMlAPI.enqueue.mockResolvedValue({ data: { ...ENQUEUED, missing_from_bundle_resources: ['replenishment'] } });
    renderFooter();
    await userEvent.click(resync());
    expect(await screen.findByRole('status')).toHaveTextContent('No habilitado en la sincronización: reposición de Full');
  });

  it('a resource it has no name for keeps its own', async () => {
    publicacionesMlAPI.enqueue.mockResolvedValue({ data: { ...ENQUEUED, missing_from_bundle_resources: ['user_product'] } });
    renderFooter();
    await userEvent.click(resync());
    expect(await screen.findByRole('status')).toHaveTextContent('No habilitado en la sincronización: user_product');
  });

  it('an empty answer is still a success, with nothing more to say', async () => {
    publicacionesMlAPI.enqueue.mockResolvedValue({ data: null });
    renderFooter();
    await userEvent.click(resync());
    expect(await screen.findByRole('status')).toHaveTextContent('Resincronización pedida');
  });

  it('passes on the backend\'s note when the refresh is off', async () => {
    publicacionesMlAPI.enqueue.mockResolvedValue({
      data: { ...ENQUEUED, refresh_enabled: false, note: 'refresh.enabled está apagado: las entradas quedan en cola hasta que se encienda' },
    });
    renderFooter();
    await userEvent.click(resync());
    expect(await screen.findByRole('status')).toHaveTextContent('refresh.enabled está apagado');
  });

  it.each([
    [403, 'No tenés permiso para resincronizar'],
    [422, 'El pedido de resincronización no es válido'],
    [500, 'No se pudo pedir la resincronización'],
  ])('a %i says so, keeps the freshness it had and lets you try again (S60.3)', async (status, message) => {
    publicacionesMlAPI.enqueue.mockRejectedValueOnce(httpError(status));
    renderFooter();
    await userEvent.click(resync());
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
    expect(screen.queryByText(/Resincronización pedida/)).not.toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Actualización de los datos' })).toHaveTextContent('hace 30 min');
    expect(resync()).toBeEnabled();

    await userEvent.click(resync());
    expect(await screen.findByRole('status')).toHaveTextContent('Resincronización pedida');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('the feedback of one publication is not shown under the next', async () => {
    const { rerender } = renderFooter();
    await userEvent.click(resync());
    await screen.findByRole('status');
    rerender(<PanelFooter key="MLA1100000002" detail={readDetail(makeDetail({ can_resync: true }))} itemId="MLA1100000002" canManage />);
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });
});
