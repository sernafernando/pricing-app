/**
 * SellOutAnularMasivo: the campaigns list with row selection and "Anular seleccionados" (bulk void, all or nothing,
 * `POST /sell-out/campanas/anular`). "Seleccionar todo lo filtrado" resolves every filtered id from the list endpoint
 * and is fail-closed: it refuses when the ids it got do not add up to the list total.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { sellOutAPI } from '../../services/sellOutAPI';
import { CAMPANA_MIGRADA } from './sellOutFixtures';
import SellOutAnularMasivo from './SellOutAnularMasivo';

vi.mock('../../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), anularVarias: vi.fn() },
}));

const campana = (id, estado = 'activa') => ({ ...CAMPANA_MIGRADA, id, nombre: `Campaña ${id}`, estado });
const PAGINA = [campana(1), campana(2), campana(3, 'anulada')];

function renderLista(props = {}) {
  const onAnuladas = vi.fn();
  render(
    <SellOutAnularMasivo
      campanas={PAGINA}
      total={3}
      filtros={{}}
      puedeGestionar
      selectedId={null}
      onSelect={() => {}}
      onAnuladas={onAnuladas}
      {...props}
    />,
  );
  return { onAnuladas };
}

const fila = (nombre) => screen.getByText(nombre).closest('tr');
const casilla = (nombre) => within(fila(nombre)).getByRole('checkbox');

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SellOutAnularMasivo', () => {
  it('without sell_out.gestionar the list has no selection and no bulk action', () => {
    renderLista({ puedeGestionar: false });

    expect(screen.getByText('Campaña 1')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Anular seleccionados/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Seleccionar todo lo filtrado/ })).not.toBeInTheDocument();
  });

  it('row checkboxes and the header checkbox select the visible page and the bar counts them', async () => {
    const user = userEvent.setup();
    renderLista();

    expect(screen.queryByText(/seleccionad/)).not.toBeInTheDocument();
    await user.click(casilla('Campaña 2'));
    expect(screen.getByText('1 seleccionada')).toBeInTheDocument();

    const encabezado = screen.getByRole('checkbox', { name: 'Seleccionar la página' });
    await user.click(encabezado);
    expect(screen.getByText('3 seleccionadas')).toBeInTheDocument();
    expect(casilla('Campaña 1')).toBeChecked();

    await user.click(encabezado);
    expect(screen.queryByText(/seleccionad/)).not.toBeInTheDocument();
    expect(casilla('Campaña 1')).not.toBeChecked();
  });

  it('select all filtered pages through the list with the filters and a stable order', async () => {
    const user = userEvent.setup();
    const filtradas = Array.from({ length: 250 }, (_, i) => campana(i + 1));
    sellOutAPI.listar.mockImplementation(async ({ page, page_size: size }) => ({
      data: { items: filtradas.slice((page - 1) * size, page * size), total: 250 },
    }));
    renderLista({ total: 250, filtros: { q: 'tp' } });

    await user.click(screen.getByRole('button', { name: 'Seleccionar todo lo filtrado (250)' }));

    expect(await screen.findByText('250 seleccionadas')).toBeInTheDocument();
    expect(sellOutAPI.listar).toHaveBeenNthCalledWith(1, { q: 'tp', page: 1, page_size: 200 });
    expect(sellOutAPI.listar).toHaveBeenNthCalledWith(2, { q: 'tp', page: 2, page_size: 200 });
  });

  it('select all filtered refuses when the ids do not add up to the list total', async () => {
    const user = userEvent.setup();
    sellOutAPI.listar.mockResolvedValue({ data: { items: [campana(1), campana(2)], total: 2 } });
    renderLista({ total: 3, filtros: { q: 'tp' } });

    await user.click(screen.getByRole('button', { name: 'Seleccionar todo lo filtrado (3)' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'La lista de campañas cambió mientras se seleccionaba. Actualizá la lista y volvé a intentar.',
    );
    expect(screen.queryByText(/seleccionad/)).not.toBeInTheDocument();
  });

  it('select all filtered refuses an empty answer while filters are active', async () => {
    const user = userEvent.setup();
    sellOutAPI.listar.mockResolvedValue({ data: { items: [], total: 0 } });
    renderLista({ campanas: [], total: 0, filtros: { q: 'tp' } });

    await user.click(screen.getByRole('button', { name: 'Seleccionar todo lo filtrado (0)' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'La lista de campañas cambió mientras se seleccionaba. Actualizá la lista y volvé a intentar.',
    );
  });

  it.each([
    ['an API error with its message', { response: { status: 403, data: { error: { message: 'No tienes permiso: sell_out.ver' } } } }, 'No tienes permiso: sell_out.ver'],
    ['an API error without a message', { response: { status: 500, data: {} }, message: 'Request failed with status code 500' }, 'No se pudieron seleccionar las campañas.'],
    ['a network error', { message: 'Network Error' }, 'No se pudo conectar con el servidor para seleccionar las campañas.'],
  ])('select all filtered shows %s in Spanish, never the client error', async (_caso, err, mensaje) => {
    const user = userEvent.setup();
    sellOutAPI.listar.mockRejectedValue(err);
    renderLista();

    await user.click(screen.getByRole('button', { name: 'Seleccionar todo lo filtrado (3)' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(mensaje);
    expect(screen.queryByText(/seleccionad/)).not.toBeInTheDocument();
  });

  it('the confirmation states how many are voided, what is reversed, and the result names voided and skipped', async () => {
    const user = userEvent.setup();
    sellOutAPI.anularVarias.mockResolvedValue({ data: { anuladas: [1, 2], omitidas: [3] } });
    const { onAnuladas } = renderLista();

    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la página' }));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));

    const confirmacion = screen.getByRole('region', { name: 'Confirmar anulación' });
    expect(confirmacion).toHaveTextContent('Se van a anular 2 campañas.');
    expect(confirmacion).toHaveTextContent('1 ya está anulada y se omite.');
    expect(confirmacion).toHaveTextContent(
      'El sell out que acreditaron deja de contar: se borran sus consumos y se recalculan las ventas que alcanzaban.',
    );
    await user.type(within(confirmacion).getByLabelText('Motivo (opcional)'), 'Cargadas dos veces');
    await user.click(within(confirmacion).getByRole('button', { name: 'Confirmar anulación' }));

    expect(sellOutAPI.anularVarias).toHaveBeenCalledWith([1, 2, 3], 'Cargadas dos veces');
    expect(await screen.findByRole('status')).toHaveTextContent('Se anularon 2 campañas. 1 ya estaba anulada y se omitió.');
    expect(onAnuladas).toHaveBeenCalledWith([1, 2]);
    expect(screen.queryByText(/seleccionad/)).not.toBeInTheDocument();
  });

  it('a refused bulk void voids nothing and names each refused campaign and why', async () => {
    const user = userEvent.setup();
    sellOutAPI.anularVarias.mockRejectedValue({
      response: {
        status: 422,
        data: {
          error: {
            code: 'ANULACION_RECHAZADA',
            message: 'No se anuló ninguna campaña: 1 no se puede anular.',
            rechazadas: [{ id: 2, motivo: 'La campaña 2 no existe' }],
          },
        },
      },
    });
    const { onAnuladas } = renderLista();

    await user.click(casilla('Campaña 1'));
    await user.click(casilla('Campaña 2'));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar anulación' }));

    const alerta = await screen.findByRole('alert');
    expect(alerta).toHaveTextContent('No se anuló ninguna campaña: 1 no se puede anular.');
    expect(alerta).toHaveTextContent('La campaña 2 no existe');
    expect(onAnuladas).not.toHaveBeenCalled();
    expect(screen.getByText('2 seleccionadas')).toBeInTheDocument();
  });
});
