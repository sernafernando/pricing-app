import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import AdministracionProveedores from './AdministracionProveedores';
import api from '../services/api';

/**
 * Contrato del botón "Sync ERP" tras mover el sync full a un job de background
 * (branch fix/sync-proveedores-cadena-erp).
 *
 * El POST sin `supp_id` responde 202 y el resultado real llega después por SSE
 * en el canal `proveedores:sync`. Eso abrió dos formas de dejar la UI trabada,
 * y estos tests las fijan:
 *
 *   BUG A — la entrega por SSE es best-effort (el backend traga los errores de
 *     publicación y sin Redis ni publica). Si el evento no llega nunca,
 *     `syncEnCurso` quedaba en true para siempre: banner permanente y botón
 *     deshabilitado hasta recargar la página.
 *   BUG B — la suscripción SSE está siempre viva, así que un job rápido (p. ej.
 *     el camino de "el ERP no devolvió nada") puede publicar su resultado
 *     mientras el POST sigue en vuelo. El `setSyncEnCurso(true)` posterior
 *     pisaba el resultado ya recibido y nada volvía a limpiarlo.
 *   BUG C — `proveedores:sync` es un canal de BROADCAST GLOBAL: el evento del
 *     sync de otro usuario (o de un job viejo que llega tarde) resolvía la
 *     corrida en vuelo de esta pestaña, cancelaba su timeout y renderizaba
 *     contadores ajenos como propios. Se corrige correlacionando por el
 *     `run_id` que el backend devuelve en la 202 y repite en cada payload SSE.
 *
 * `services/api` y `PermisosContext` los mockea el setup global (`src/test/setup.js`,
 * `tienePermiso` siempre true). `useSSEChannel` se mockea acá para capturar el
 * callback y poder disparar eventos con timing controlado.
 */

let sseCallback = null;

vi.mock('../hooks/useSSEChannel', () => ({
  useSSEChannel: (channel, callback) => {
    if (channel === 'proveedores:sync') sseCallback = callback;
  },
}));

const RESPUESTA_202 = {
  status: 202,
  data: {
    success: true,
    queued: true,
    channel: 'proveedores:sync',
    message: 'Sincronización con el ERP en curso. El resultado llega al finalizar.',
  },
};

const CONTADORES = {
  success: true,
  total_erp: 120,
  insertados: 3,
  actualizados: 5,
  rma_insertados: 2,
  vinculados_rma: 1,
};

const RUN_ID = '0123456789abcdef0123456789abcdef';
const RUN_ID_AJENO = 'ffffffffffffffffffffffffffffffff';

/** 202 del backend actual: trae el `run_id` de la corrida. */
const RESPUESTA_202_CORRELACIONADA = {
  status: 202,
  data: { ...RESPUESTA_202.data, run_id: RUN_ID },
};

const RE_EN_CURSO = /Sincronización con el ERP en curso/;
const RE_SIN_CONFIRMAR = /No se pudo confirmar el resultado de la sincronización/;

/** Llamadas a la lista de proveedores (ignora detalle, marcas, etc.). */
const llamadasALaLista = () =>
  api.get.mock.calls.filter(([url]) => url.startsWith('/administracion/proveedores?')).length;

const botonSync = () => screen.getByRole('button', { name: /Sync ERP|Sincronizando/i });

/** Monta la página y espera a que termine el fetch inicial de la lista. */
const montarPagina = async () => {
  render(<AdministracionProveedores />);
  await waitFor(() => expect(llamadasALaLista()).toBe(1));
};

describe('AdministracionProveedores — contrato del sync ERP en background', () => {
  beforeEach(() => {
    sseCallback = null;
    api.get.mockImplementation((url) =>
      url.startsWith('/administracion/proveedores?')
        ? Promise.resolve({ data: { proveedores: [], total: 0 } })
        : Promise.resolve({ data: {} }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('un 202 muestra el banner "en curso" y deshabilita el botón', async () => {
    api.post.mockResolvedValue(RESPUESTA_202);
    await montarPagina();

    fireEvent.click(botonSync());

    await waitFor(() => expect(screen.getByText(RE_EN_CURSO)).toBeInTheDocument());
    expect(botonSync()).toBeDisabled();
  });

  it('el evento SSE de éxito limpia el banner, muestra los contadores y refresca la tabla', async () => {
    api.post.mockResolvedValue(RESPUESTA_202);
    await montarPagina();

    fireEvent.click(botonSync());
    await waitFor(() => expect(screen.getByText(RE_EN_CURSO)).toBeInTheDocument());

    await act(async () => {
      sseCallback({ channel: 'proveedores:sync', data: CONTADORES });
    });

    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(screen.getByText(/Sync completado: 120 proveedores/)).toBeInTheDocument();
    expect(screen.getByText(/3 nuevos, 5 actualizados/)).toBeInTheDocument();
    expect(botonSync()).not.toBeDisabled();
    // La tabla se refetchea con los datos ya sincronizados.
    await waitFor(() => expect(llamadasALaLista()).toBe(2));
  });

  // BUG B
  it('un evento SSE que llega ANTES de que resuelva el POST no deja la UI trabada en "en curso"', async () => {
    let resolverPost;
    api.post.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolverPost = resolve;
        }),
    );
    await montarPagina();

    fireEvent.click(botonSync());
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));

    // El job rápido publica su resultado con el POST todavía en vuelo.
    await act(async () => {
      sseCallback({
        channel: 'proveedores:sync',
        data: { success: false, error: 'El ERP no devolvió proveedores' },
      });
    });

    // Recién ahora responde el 202: su `setSyncEnCurso(true)` es un dato viejo.
    await act(async () => {
      resolverPost(RESPUESTA_202);
    });

    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(screen.getByText('El ERP no devolvió proveedores')).toBeInTheDocument();
    expect(botonSync()).not.toBeDisabled();
  });

  // BUG A
  it('si el evento SSE nunca llega, al vencer la ventana el banner se limpia y el botón vuelve a servir', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.post.mockResolvedValue(RESPUESTA_202);
    await montarPagina();

    fireEvent.click(botonSync());
    await waitFor(() => expect(screen.getByText(RE_EN_CURSO)).toBeInTheDocument());

    // Justo antes del vencimiento la UI sigue esperando de forma legítima.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(89_000);
    });
    expect(screen.getByText(RE_EN_CURSO)).toBeInTheDocument();
    expect(botonSync()).toBeDisabled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });

    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(botonSync()).not.toBeDisabled();
    // Aviso honesto: no se declara un fallo que no ocurrió.
    expect(screen.getByText(RE_SIN_CONFIRMAR)).toBeInTheDocument();
  });

  it('el camino sincrónico (200 con contadores) los muestra al instante sin tocar el estado "en curso"', async () => {
    api.post.mockResolvedValue({ status: 200, data: CONTADORES });
    await montarPagina();

    fireEvent.click(botonSync());

    await waitFor(() =>
      expect(screen.getByText(/Sync completado: 120 proveedores/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(screen.queryByText(RE_SIN_CONFIRMAR)).not.toBeInTheDocument();
    expect(botonSync()).not.toBeDisabled();
    await waitFor(() => expect(llamadasALaLista()).toBe(2));
  });

  // BUG C
  it('un evento SSE de OTRA corrida no resuelve la propia: el banner sigue, el timeout no se cancela y syncResult queda intacto', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.post.mockResolvedValue(RESPUESTA_202_CORRELACIONADA);
    await montarPagina();

    fireEvent.click(botonSync());
    await waitFor(() => expect(screen.getByText(RE_EN_CURSO)).toBeInTheDocument());

    // El sync de otro usuario termina y publica en el canal global.
    await act(async () => {
      sseCallback({
        channel: 'proveedores:sync',
        data: { ...CONTADORES, run_id: RUN_ID_AJENO, total_erp: 999 },
      });
    });

    // Nada de eso es nuestro: la corrida propia sigue esperando su resultado.
    expect(screen.getByText(RE_EN_CURSO)).toBeInTheDocument();
    expect(botonSync()).toBeDisabled();
    expect(screen.queryByText(/Sync completado/)).not.toBeInTheDocument();
    expect(screen.queryByText(/999 proveedores/)).not.toBeInTheDocument();
    // El sync ajeno terminó bien y dejó datos nuevos: la tabla SÍ se refresca,
    // pero en silencio (sin banner, sin resultado, sin tocar la corrida propia).
    await waitFor(() => expect(llamadasALaLista()).toBe(2));

    // Y el timeout propio NO fue cancelado: sigue vigente y vence a los 90 s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(91_000);
    });
    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(screen.getByText(RE_SIN_CONFIRMAR)).toBeInTheDocument();
  });

  it('un evento SSE con el run_id propio resuelve la corrida normalmente', async () => {
    api.post.mockResolvedValue(RESPUESTA_202_CORRELACIONADA);
    await montarPagina();

    fireEvent.click(botonSync());
    await waitFor(() => expect(screen.getByText(RE_EN_CURSO)).toBeInTheDocument());

    await act(async () => {
      sseCallback({ channel: 'proveedores:sync', data: { ...CONTADORES, run_id: RUN_ID } });
    });

    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(screen.getByText(/Sync completado: 120 proveedores/)).toBeInTheDocument();
    expect(botonSync()).not.toBeDisabled();
    await waitFor(() => expect(llamadasALaLista()).toBe(2));
  });

  // BUG B + BUG C: el evento temprano no se puede correlacionar todavía, porque
  // el `run_id` recién se conoce cuando resuelve la 202. Se retiene y se
  // reconcilia ahí — ni se aplica a ciegas ni se descarta a ciegas.
  it('un evento propio que llega ANTES de la 202 se reconcilia al conocer el run_id', async () => {
    let resolverPost;
    api.post.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolverPost = resolve;
        }),
    );
    await montarPagina();

    fireEvent.click(botonSync());
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));

    await act(async () => {
      sseCallback({ channel: 'proveedores:sync', data: { ...CONTADORES, run_id: RUN_ID } });
    });

    await act(async () => {
      resolverPost(RESPUESTA_202_CORRELACIONADA);
    });

    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(screen.getByText(/Sync completado: 120 proveedores/)).toBeInTheDocument();
    expect(botonSync()).not.toBeDisabled();
  });

  it('un evento AJENO que llega antes de la 202 se descarta y la corrida propia sigue en curso', async () => {
    let resolverPost;
    api.post.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolverPost = resolve;
        }),
    );
    await montarPagina();

    fireEvent.click(botonSync());
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));

    await act(async () => {
      sseCallback({
        channel: 'proveedores:sync',
        data: { success: false, error: 'Sync de otro usuario', run_id: RUN_ID_AJENO },
      });
    });

    await act(async () => {
      resolverPost(RESPUESTA_202_CORRELACIONADA);
    });

    // Al reconciliar contra el run_id propio se ve que el evento no era nuestro.
    expect(screen.queryByText('Sync de otro usuario')).not.toBeInTheDocument();
    expect(screen.getByText(RE_EN_CURSO)).toBeInTheDocument();
    expect(botonSync()).toBeDisabled();
  });

  // El buffer de eventos en vuelo no es de un solo slot: un evento ajeno que
  // llega DESPUÉS del propio (ambos con el POST en vuelo) no lo pisa.
  it('dos eventos en vuelo (propio y después ajeno): el propio se reconcilia igual', async () => {
    let resolverPost;
    api.post.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolverPost = resolve;
        }),
    );
    await montarPagina();

    fireEvent.click(botonSync());
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));

    await act(async () => {
      sseCallback({ channel: 'proveedores:sync', data: { ...CONTADORES, run_id: RUN_ID } });
    });
    await act(async () => {
      sseCallback({
        channel: 'proveedores:sync',
        data: { success: false, error: 'Sync de otro usuario', run_id: RUN_ID_AJENO },
      });
    });

    await act(async () => {
      resolverPost(RESPUESTA_202_CORRELACIONADA);
    });

    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(screen.getByText(/Sync completado: 120 proveedores/)).toBeInTheDocument();
    expect(screen.queryByText('Sync de otro usuario')).not.toBeInTheDocument();
    expect(botonSync()).not.toBeDisabled();
  });

  it('dos eventos en vuelo (ajeno y después propio): también gana el propio', async () => {
    let resolverPost;
    api.post.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolverPost = resolve;
        }),
    );
    await montarPagina();

    fireEvent.click(botonSync());
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));

    await act(async () => {
      sseCallback({
        channel: 'proveedores:sync',
        data: { success: false, error: 'Sync de otro usuario', run_id: RUN_ID_AJENO },
      });
    });
    await act(async () => {
      sseCallback({ channel: 'proveedores:sync', data: { ...CONTADORES, run_id: RUN_ID } });
    });

    await act(async () => {
      resolverPost(RESPUESTA_202_CORRELACIONADA);
    });

    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(screen.getByText(/Sync completado: 120 proveedores/)).toBeInTheDocument();
    expect(screen.queryByText('Sync de otro usuario')).not.toBeInTheDocument();
    expect(botonSync()).not.toBeDisabled();
  });

  it('un evento ajeno exitoso sin corrida propia refresca la lista en silencio', async () => {
    await montarPagina();

    await act(async () => {
      sseCallback({ channel: 'proveedores:sync', data: { ...CONTADORES, run_id: RUN_ID_AJENO } });
    });

    await waitFor(() => expect(llamadasALaLista()).toBe(2));
    expect(screen.queryByText(RE_EN_CURSO)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sync completado/)).not.toBeInTheDocument();
    expect(botonSync()).not.toBeDisabled();
  });

  it('un evento ajeno FALLIDO no refresca la lista: no hay datos nuevos que buscar', async () => {
    await montarPagina();

    await act(async () => {
      sseCallback({
        channel: 'proveedores:sync',
        data: { success: false, error: 'El ERP no devolvió proveedores', run_id: RUN_ID_AJENO },
      });
    });

    expect(llamadasALaLista()).toBe(1);
    expect(screen.queryByText('El ERP no devolvió proveedores')).not.toBeInTheDocument();
  });

  it('no deja timers colgados: desmontar con un sync en curso no dispara setState después', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api.post.mockResolvedValue(RESPUESTA_202);

    const { unmount } = render(<AdministracionProveedores />);
    await waitFor(() => expect(llamadasALaLista()).toBe(1));

    fireEvent.click(botonSync());
    await waitFor(() => expect(screen.getByText(RE_EN_CURSO)).toBeInTheDocument());

    const errores = [];
    const consoleErrorOriginal = console.error;
    console.error = (...args) => errores.push(args);

    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });

    console.error = consoleErrorOriginal;
    expect(errores).toEqual([]);
  });
});
