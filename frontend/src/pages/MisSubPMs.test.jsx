/**
 * Tests for MisSubPMs.jsx — user-first sub-PM bulk assignment container
 * (sub-pm-bulk-assignment Slice 4).
 *
 * Scope:
 *   - Pick the TARGET USER first from the user list; each shows a grant count,
 *     including (0), sourced from GET /marcas-pm/sub-pms/conteos.
 *   - Selecting a user pre-checks their granted pairs (GET .../usuario/{id}).
 *   - Pair source split by contract: admin -> GET /marcas-pm; titular ->
 *     GET /marcas-pm/mis-titularidades. 403-only fallback for admin.
 *   - Save disabled until the checked set differs from the baseline.
 *   - One confirm shows a +N/-N diff summary before the PUT.
 *   - Success updates the user count locally, no reload.
 *   - A 403 with a dict `detail.pares_rechazados` renders WHICH pairs were
 *     rejected and states nothing was applied.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MisSubPMs from './MisSubPMs';
import { marcasPmAPI } from '../services/api';
import { clavesDesdePayload } from './misSubPMsHelpers';
import { parKey } from '../components/parKey';

const permisosDenegados = new Set();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => !permisosDenegados.has(codigo),
    tieneAlgunPermiso: (codigos) => codigos.some((c) => !permisosDenegados.has(c)),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const PARES_TITULAR = {
  pares: [
    { id: 1, marca: 'Samsung', categoria: 'Celulares', usuario_id: 1, usuario_nombre: 'Titular' },
    { id: 2, marca: 'LG', categoria: 'Televisores', usuario_id: 1, usuario_nombre: 'Titular' },
  ],
  total: 2,
};

const TODOS_LOS_PARES = [
  { id: 1, marca: 'Samsung', categoria: 'Celulares', usuario_id: 1, usuario_nombre: 'Titular' },
  { id: 2, marca: 'LG', categoria: 'Televisores', usuario_id: 1, usuario_nombre: 'Titular' },
  { id: 99, marca: 'Huerfana', categoria: 'Sin Titular', usuario_id: null, usuario_nombre: null },
];

const USUARIOS = [
  { id: 5, nombre: 'Ana', email: 'ana@x.com', rol: 'ventas' },
  { id: 6, nombre: 'Beto', email: 'beto@x.com', rol: 'ventas' },
];

beforeEach(() => {
  marcasPmAPI.misTitularidades.mockReset().mockResolvedValue({ data: PARES_TITULAR });
  marcasPmAPI.listarTodosLosPares.mockReset().mockResolvedValue({ data: TODOS_LOS_PARES });
  marcasPmAPI.listarUsuariosPM.mockReset().mockResolvedValue({ data: USUARIOS });
  marcasPmAPI.obtenerConteosSubPMs.mockReset().mockResolvedValue({ data: { conteos: [] } });
  marcasPmAPI.obtenerGrantsUsuario.mockReset().mockResolvedValue({ data: { pares: [], total: 0 } });
  marcasPmAPI.asignarSubPMsBulk.mockReset().mockResolvedValue({ data: { otorgados: 0, revocados: 0, total: 0 } });
  permisosDenegados.clear();
  permisosDenegados.add('admin.gestionar_pms'); // default: non-admin titular
});

// The user list stays empty until the pair source resolves with at least
// one pair (security invariant: the global PM user list is only fetched once
// we know the caller has scope — see MisSubPMs.jsx). Tests wait for a user
// button before interacting.
function botonUsuario(nombre) {
  return screen.findByRole('button', { name: new RegExp(`^${nombre} \\(`) });
}

async function elegirUsuario(user, nombre) {
  await user.click(await botonUsuario(nombre));
}

// Pairs live inside a collapsed accordion per marca; open every marca so the
// per-pair checkboxes are reachable.
async function expandirTodo(user) {
  await user.click(await screen.findByRole('button', { name: /expandir todo/i }));
}

async function elegirYExpandir(user, nombre) {
  await elegirUsuario(user, nombre);
  await expandirTodo(user);
}

describe('MisSubPMs — user list', () => {
  it('shows a grant count next to each user, including (0)', async () => {
    marcasPmAPI.obtenerConteosSubPMs.mockResolvedValue({ data: { conteos: [{ usuario_id: 5, total: 12 }] } });
    render(<MisSubPMs />);
    await botonUsuario('Ana');
    await waitFor(() => expect(marcasPmAPI.obtenerConteosSubPMs).toHaveBeenCalled());
    expect(await screen.findByRole('button', { name: 'Ana (12)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Beto (0)' })).toBeInTheDocument();
  });

  it('filters the user list by name', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await botonUsuario('Ana');
    await user.type(screen.getByRole('searchbox', { name: /buscar usuario/i }), 'bet');
    expect(screen.queryByRole('button', { name: /^Ana \(/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Beto \(/ })).toBeInTheDocument();
  });

  it('keeps the selected user listed while a search hides the others', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await elegirUsuario(user, 'Ana');
    await user.type(screen.getByRole('searchbox', { name: /buscar usuario/i }), 'bet');
    expect(screen.getByRole('button', { name: /^Ana \(/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /^Beto \(/ })).toBeInTheDocument();
  });

  it('says no user matches only when a search is active', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    marcasPmAPI.listarUsuariosPM.mockRejectedValue(new Error('boom'));
    render(<MisSubPMs />);
    expect(await screen.findByText(/error al cargar los usuarios/i)).toBeInTheDocument();
    expect(screen.queryByText(/ningún usuario coincide/i)).not.toBeInTheDocument();
    consoleErrorSpy.mockRestore();
  });

  it('says no user matches when the search finds nobody', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await botonUsuario('Ana');
    await user.type(screen.getByRole('searchbox', { name: 'Buscar usuario' }), 'zzz');
    expect(screen.getByText('Ningún usuario coincide.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Ana \(/ })).not.toBeInTheDocument();
  });

  it('uses "Mis Sub-PMs" copy for titulares and "Sub-PMs" for admins', async () => {
    render(<MisSubPMs />);
    expect(await screen.findByRole('heading', { name: 'Mis Sub-PMs' })).toBeInTheDocument();

    permisosDenegados.clear();
    render(<MisSubPMs />);
    expect(await screen.findByRole('heading', { name: 'Sub-PMs' })).toBeInTheDocument();
  });
});

describe('MisSubPMs — user list fetch gated on having pairs in scope (security invariant)', () => {
  it('does NOT fetch the global user list or counts when the caller is titular of zero pairs', async () => {
    marcasPmAPI.misTitularidades.mockResolvedValue({ data: { pares: [], total: 0 } });
    render(<MisSubPMs />);

    expect(await screen.findByText(/no tenés marcas\/categorías en tu scope/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Ana \(/ })).not.toBeInTheDocument();
    expect(marcasPmAPI.listarUsuariosPM).not.toHaveBeenCalled();
    expect(marcasPmAPI.obtenerConteosSubPMs).not.toHaveBeenCalled();
  });

  it('does NOT fetch the global user list or counts when the admin has zero pairs at all', async () => {
    permisosDenegados.clear();
    marcasPmAPI.listarTodosLosPares.mockResolvedValue({ data: [] });
    render(<MisSubPMs />);

    expect(await screen.findByText(/no tenés marcas\/categorías en tu scope/i)).toBeInTheDocument();
    expect(marcasPmAPI.listarUsuariosPM).not.toHaveBeenCalled();
    expect(marcasPmAPI.obtenerConteosSubPMs).not.toHaveBeenCalled();
  });

  it('fetches the user list once pairs in scope are confirmed to exist', async () => {
    render(<MisSubPMs />);
    await botonUsuario('Ana');
    await waitFor(() => expect(marcasPmAPI.listarUsuariosPM).toHaveBeenCalled());
    await waitFor(() => expect(marcasPmAPI.obtenerConteosSubPMs).toHaveBeenCalled());
  });
});

describe('MisSubPMs — pre-check and dirty tracking', () => {
  it('pre-checks the pairs already granted to the selected user', async () => {
    const user = userEvent.setup();
    marcasPmAPI.obtenerGrantsUsuario.mockResolvedValue({
      data: { pares: [{ marca: 'Samsung', categoria: 'Celulares' }], total: 1 },
    });
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    await waitFor(() => expect(marcasPmAPI.obtenerGrantsUsuario).toHaveBeenCalledWith(5));

    const samsungCheckbox = await screen.findByLabelText('Seleccionar Samsung / Celulares');
    const lgCheckbox = screen.getByLabelText('Seleccionar LG / Televisores');
    expect(samsungCheckbox).toBeChecked();
    expect(lgCheckbox).not.toBeChecked();
  });

  it('disables save until the checked set differs from the baseline', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    await screen.findByLabelText('Seleccionar Samsung / Celulares');

    const guardar = screen.getByRole('button', { name: /guardar cambios/i });
    expect(guardar).toBeDisabled();

    await user.click(screen.getByLabelText('Seleccionar Samsung / Celulares'));
    expect(guardar).toBeEnabled();

    await user.click(screen.getByLabelText('Seleccionar Samsung / Celulares'));
    expect(guardar).toBeDisabled();
  });
});

describe('MisSubPMs — grouped by marca', () => {
  const PARES_DOS_MARCAS = {
    pares: [
      { id: 1, marca: 'LENOVO', categoria: 'Monitores', usuario_id: 1, usuario_nombre: 'Titular' },
      { id: 2, marca: 'LENOVO', categoria: 'Notebooks', usuario_id: 1, usuario_nombre: 'Titular' },
      { id: 3, marca: 'SAMSUNG', categoria: 'Monitores', usuario_id: 1, usuario_nombre: 'Titular' },
      { id: 4, marca: 'SAMSUNG', categoria: 'Celulares', usuario_id: 1, usuario_nombre: 'Titular' },
    ],
    total: 4,
  };

  beforeEach(() => {
    marcasPmAPI.misTitularidades.mockResolvedValue({ data: PARES_DOS_MARCAS });
  });

  it('asks to pick a user before showing any pair', async () => {
    render(<MisSubPMs />);
    await botonUsuario('Ana');
    expect(screen.getByText('Elegí un usuario')).toBeInTheDocument();
    expect(screen.queryByLabelText('Seleccionar toda la marca LENOVO')).not.toBeInTheDocument();
  });

  it('grants a whole marca with its checkbox and one more pair, and saves exactly those pairs', async () => {
    const user = userEvent.setup();
    marcasPmAPI.asignarSubPMsBulk.mockResolvedValue({ data: { otorgados: 3, revocados: 0, total: 3 } });
    render(<MisSubPMs />);
    await elegirUsuario(user, 'Ana');

    await user.click(await screen.findByLabelText('Seleccionar toda la marca LENOVO'));
    await user.click(screen.getByRole('button', { name: /SAMSUNG/ }));
    await user.click(screen.getByLabelText('Seleccionar SAMSUNG / Monitores'));

    expect(screen.getByText('2 sin guardar')).toBeInTheDocument();
    expect(screen.getByText('1 sin guardar')).toBeInTheDocument();
    expect(screen.getByLabelText('Seleccionar toda la marca SAMSUNG')).toHaveProperty('indeterminate', true);

    await user.click(screen.getByRole('button', { name: /guardar cambios/i }));
    await user.click(screen.getByRole('button', { name: /sí, guardar/i }));

    await waitFor(() => expect(marcasPmAPI.asignarSubPMsBulk).toHaveBeenCalledTimes(1));
    const [usuarioId, enviados] = marcasPmAPI.asignarSubPMsBulk.mock.calls[0];
    expect(usuarioId).toBe(5);
    expect(enviados).toHaveLength(3);
    expect(enviados).toEqual(
      expect.arrayContaining([
        { marca: 'LENOVO', categoria: 'Monitores' },
        { marca: 'LENOVO', categoria: 'Notebooks' },
        { marca: 'SAMSUNG', categoria: 'Monitores' },
      ]),
    );
  });

  it('unchecking a whole marca removes every pair of it', async () => {
    const user = userEvent.setup();
    marcasPmAPI.obtenerGrantsUsuario.mockResolvedValue({
      data: { pares: [{ marca: 'LENOVO', categoria: 'Monitores' }, { marca: 'LENOVO', categoria: 'Notebooks' }], total: 2 },
    });
    render(<MisSubPMs />);
    await elegirUsuario(user, 'Ana');

    await user.click(await screen.findByLabelText('Seleccionar toda la marca LENOVO'));
    await user.click(screen.getByRole('button', { name: /LENOVO/ }));

    expect(screen.getByLabelText('Seleccionar LENOVO / Monitores')).not.toBeChecked();
    expect(screen.getByLabelText('Seleccionar LENOVO / Notebooks')).not.toBeChecked();
    expect(screen.getAllByText('Se quita')).toHaveLength(2);
  });

  it('a marca checkbox only affects the rows the search leaves visible', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await elegirUsuario(user, 'Ana');

    await user.type(await screen.findByRole('searchbox', { name: /buscar marca o categoría/i }), 'monit');
    await user.click(screen.getByLabelText('Seleccionar toda la marca SAMSUNG'));

    expect(screen.getByLabelText('Seleccionar SAMSUNG / Monitores')).toBeChecked();
    expect(screen.queryByLabelText('Seleccionar SAMSUNG / Celulares')).not.toBeInTheDocument();
    expect(screen.getByText('1 sin guardar')).toBeInTheDocument();
  });

  it('marks pending rows: "Se agrega" for a new pair and "Se quita" for a removed one', async () => {
    const user = userEvent.setup();
    marcasPmAPI.obtenerGrantsUsuario.mockResolvedValue({
      data: { pares: [{ marca: 'LENOVO', categoria: 'Monitores' }], total: 1 },
    });
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');

    await user.click(screen.getByLabelText('Seleccionar LENOVO / Notebooks'));
    await user.click(screen.getByLabelText('Seleccionar LENOVO / Monitores'));

    expect(screen.getByText('Se agrega')).toBeInTheDocument();
    expect(screen.getByText('Se quita')).toBeInTheDocument();
  });

  it('"Mostrar solo lo asignado" hides pairs the user neither has nor is adding', async () => {
    const user = userEvent.setup();
    marcasPmAPI.obtenerGrantsUsuario.mockResolvedValue({
      data: { pares: [{ marca: 'LENOVO', categoria: 'Monitores' }], total: 1 },
    });
    render(<MisSubPMs />);
    await elegirUsuario(user, 'Ana');

    await user.click(await screen.findByLabelText(/mostrar solo lo asignado/i));

    expect(screen.getByLabelText('Seleccionar LENOVO / Monitores')).toBeChecked();
    expect(screen.queryByLabelText('Seleccionar LENOVO / Notebooks')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Seleccionar toda la marca SAMSUNG')).not.toBeInTheDocument();
  });
});

describe('MisSubPMs — confirm and save', () => {
  async function pickUserAndToggle(user) {
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    await user.click(await screen.findByLabelText('Seleccionar Samsung / Celulares'));
    await user.click(screen.getByRole('button', { name: /guardar cambios/i }));
  }

  it('shows a diff summary (+N granted / -N revoked) in a single confirm', async () => {
    const user = userEvent.setup();
    await pickUserAndToggle(user);
    const confirmBox = within(await screen.findByTestId('confirmarGuardarBox'));
    expect(confirmBox.getByText('+1')).toBeInTheDocument();
    expect(confirmBox.getByText('−0')).toBeInTheDocument();
    expect(marcasPmAPI.asignarSubPMsBulk).not.toHaveBeenCalled();
  });

  it('applies the bulk PUT on confirm and updates the user count without reload', async () => {
    const user = userEvent.setup();
    marcasPmAPI.asignarSubPMsBulk.mockResolvedValue({ data: { otorgados: 1, revocados: 0, total: 1 } });
    await pickUserAndToggle(user);

    await user.click(screen.getByRole('button', { name: /sí, guardar/i }));

    await waitFor(() => expect(marcasPmAPI.asignarSubPMsBulk).toHaveBeenCalledWith(5, [{ marca: 'Samsung', categoria: 'Celulares' }]));
    expect(marcasPmAPI.listarUsuariosPM).toHaveBeenCalledTimes(1); // no reload
    expect(await screen.findByRole('button', { name: 'Ana (1)' })).toBeInTheDocument();

    const guardar = screen.getByRole('button', { name: /guardar cambios/i });
    expect(guardar).toBeDisabled();
  });

  it('renders WHICH pairs were rejected on a 403 and states nothing was applied', async () => {
    const user = userEvent.setup();
    marcasPmAPI.asignarSubPMsBulk.mockRejectedValue({
      response: {
        status: 403,
        data: {
          detail: {
            mensaje: 'Uno o más pares están fuera de tu scope o no existen',
            pares_rechazados: [{ marca: 'Samsung', categoria: 'Celulares' }],
          },
        },
      },
    });
    await pickUserAndToggle(user);
    await user.click(screen.getByRole('button', { name: /sí, guardar/i }));

    expect(await screen.findByText(/samsung \/ celulares/i)).toBeInTheDocument();
    expect(screen.getByText(/no se aplicó ningún cambio/i)).toBeInTheDocument();
  });
});

describe('MisSubPMs — dirty-guard on user switch', () => {
  it('with pending changes, asks for confirmation and keeps the original user + selection on cancel', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    await user.click(await screen.findByLabelText('Seleccionar Samsung / Celulares'));

    await elegirUsuario(user, 'Beto');

    expect(await screen.findByText(/tenés cambios sin guardar/i)).toBeInTheDocument();
    expect(marcasPmAPI.obtenerGrantsUsuario).not.toHaveBeenCalledWith(6);

    await user.click(screen.getByRole('button', { name: /cancelar cambio de usuario/i }));

    expect(await botonUsuario('Ana')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Seleccionar Samsung / Celulares')).toBeChecked();
  });

  it('when confirmed, loads the new user baseline and discards the previous edits', async () => {
    const user = userEvent.setup();
    marcasPmAPI.obtenerGrantsUsuario.mockImplementation((id) =>
      Promise.resolve({ data: { pares: id === 6 ? [{ marca: 'LG', categoria: 'Televisores' }] : [], total: 0 } }),
    );
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    await user.click(await screen.findByLabelText('Seleccionar Samsung / Celulares'));

    await elegirUsuario(user, 'Beto');
    await user.click(await screen.findByRole('button', { name: /sí, cambiar/i }));

    await waitFor(() => expect(marcasPmAPI.obtenerGrantsUsuario).toHaveBeenCalledWith(6));
    expect(await botonUsuario('Beto')).toHaveAttribute('aria-pressed', 'true');
    await expandirTodo(user);
    expect(screen.getByLabelText('Seleccionar LG / Televisores')).toBeChecked();
    expect(screen.getByLabelText('Seleccionar Samsung / Celulares')).not.toBeChecked();
  });

  it('with no pending changes, switching users does not prompt', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    await screen.findByLabelText('Seleccionar Samsung / Celulares');

    await elegirUsuario(user, 'Beto');

    expect(screen.queryByText(/tenés cambios sin guardar/i)).not.toBeInTheDocument();
    await waitFor(() => expect(marcasPmAPI.obtenerGrantsUsuario).toHaveBeenCalledWith(6));
    expect(await botonUsuario('Beto')).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('MisSubPMs — selecting the current user', () => {
  it('clicking the already selected user does not prompt nor reload it', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    await user.click(await screen.findByLabelText('Seleccionar Samsung / Celulares'));

    await elegirUsuario(user, 'Ana');

    expect(screen.queryByText(/tenés cambios sin guardar/i)).not.toBeInTheDocument();
    expect(marcasPmAPI.obtenerGrantsUsuario).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('Seleccionar Samsung / Celulares')).toBeChecked();
  });
});

describe('MisSubPMs — pre-check race (gate finding #1, CRITICAL)', () => {
  it('a slow response for a superseded pick must NOT overwrite the current user\'s baseline', async () => {
    const user = userEvent.setup();
    let resolveAna;
    marcasPmAPI.obtenerGrantsUsuario.mockImplementation((id) => {
      if (id === 5) {
        // Ana: never resolves until the test tells it to — simulates a slow
        // response landing AFTER Beto's has already applied.
        return new Promise((resolve) => { resolveAna = resolve; });
      }
      // Beto: resolves immediately.
      return Promise.resolve({ data: { pares: [{ marca: 'LG', categoria: 'Televisores' }], total: 1 } });
    });
    render(<MisSubPMs />);

    await elegirUsuario(user, 'Ana'); // Ana: request in flight, no dirty edits yet — not blocked
    await elegirUsuario(user, 'Beto'); // Beto: supersedes Ana before her response lands

    await expandirTodo(user);
    await waitFor(() => expect(screen.getByLabelText('Seleccionar LG / Televisores')).toBeChecked());
    expect(await botonUsuario('Beto')).toHaveAttribute('aria-pressed', 'true');

    // Ana's slow response finally lands — it must be discarded, not applied.
    resolveAna({ data: { pares: [{ marca: 'Samsung', categoria: 'Celulares' }], total: 1 } });
    await waitFor(() => expect(marcasPmAPI.obtenerGrantsUsuario).toHaveBeenCalledWith(5));

    // Still Beto's baseline: Ana's stale grant must not have landed anywhere.
    expect(await botonUsuario('Beto')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Seleccionar LG / Televisores')).toBeChecked();
    expect(screen.getByLabelText('Seleccionar Samsung / Celulares')).not.toBeChecked();
  });

  it('does not leave the spinner stuck when a pick is superseded while its pre-check is still in flight', async () => {
    const user = userEvent.setup();
    let resolveAna;
    marcasPmAPI.obtenerGrantsUsuario.mockImplementation((id) =>
      id === 5
        ? new Promise((resolve) => { resolveAna = resolve; })
        : Promise.resolve({ data: { pares: [], total: 0 } }),
    );
    render(<MisSubPMs />);

    await elegirUsuario(user, 'Ana'); // Ana: request in flight, never resolved yet
    expect(await screen.findByText(/cargando sub-pms delegados/i)).toBeInTheDocument();

    await elegirUsuario(user, 'Beto'); // Beto supersedes Ana before her response lands

    // The pair table must render again — not stuck behind the loading state
    // Ana turned on, even though her superseded response hasn't landed yet.
    await expandirTodo(user);
    expect(screen.getByLabelText('Seleccionar Samsung / Celulares')).toBeInTheDocument();
    expect(screen.queryByText(/cargando sub-pms delegados/i)).not.toBeInTheDocument();

    // And Ana's late response landing afterwards must not resurrect it either.
    resolveAna({ data: { pares: [], total: 0 } });
    await waitFor(() => expect(marcasPmAPI.obtenerGrantsUsuario).toHaveBeenCalledWith(5));
    expect(screen.queryByText(/cargando sub-pms delegados/i)).not.toBeInTheDocument();
  });
});

describe('MisSubPMs — save/switch race (review finding #1, merge-blocking)', () => {
  it('blocks switching the target user while a save is in flight, and applies the response only to the user it was saved for', async () => {
    const user = userEvent.setup();
    let resolveGuardar;
    marcasPmAPI.asignarSubPMsBulk.mockImplementation(
      () => new Promise((resolve) => { resolveGuardar = resolve; }),
    );
    marcasPmAPI.obtenerGrantsUsuario.mockImplementation((id) =>
      Promise.resolve({ data: { pares: id === 6 ? [{ marca: 'LG', categoria: 'Televisores' }] : [], total: 0 } }),
    );
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    await user.click(await screen.findByLabelText('Seleccionar Samsung / Celulares'));
    await user.click(screen.getByRole('button', { name: /guardar cambios/i }));
    await user.click(screen.getByRole('button', { name: /sí, guardar/i }));

    // Save in flight: every user button is disabled, so no switch can start.
    // A raw DOM click (no pointer-events check, unlike user-event) must not
    // start one either. The handler's own `if (saving) return` is not
    // reachable through the DOM while the buttons are disabled.
    const beto = await botonUsuario('Beto');
    expect(beto).toBeDisabled();
    fireEvent.click(beto);
    expect(marcasPmAPI.obtenerGrantsUsuario).not.toHaveBeenCalledWith(6);

    resolveGuardar({ data: { otorgados: 1, revocados: 0, total: 1 } });
    await waitFor(() => expect(beto).not.toBeDisabled());

    // Still viewing user 5; its baseline reflects the completed save and was
    // never corrupted by an in-flight switch.
    expect(await botonUsuario('Ana')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Seleccionar Samsung / Celulares')).toBeChecked();
    expect(screen.getByRole('button', { name: /guardar cambios/i })).toBeDisabled();
  });
});

describe('MisSubPMs — stale checked pair (review finding #2, #3)', () => {
  it('drops a checked pair no longer present in the pair list, tells the user how many were omitted, and does not log it as an error', async () => {
    const user = userEvent.setup();
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    // The pre-check baseline includes a pair that is NOT among the currently
    // loaded `pares` (e.g. a titular was reassigned, narrowing the pair
    // list, while the grant record itself still exists).
    marcasPmAPI.obtenerGrantsUsuario.mockResolvedValue({
      data: { pares: [{ marca: 'Fantasma', categoria: 'Descontinuada' }], total: 1 },
    });
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    await user.click(await screen.findByLabelText('Seleccionar Samsung / Celulares'));
    await user.click(screen.getByRole('button', { name: /guardar cambios/i }));
    await user.click(screen.getByRole('button', { name: /sí, guardar/i }));

    await waitFor(() =>
      expect(marcasPmAPI.asignarSubPMsBulk).toHaveBeenCalledWith(5, [{ marca: 'Samsung', categoria: 'Celulares' }]),
    );
    // This is an expected, documented condition — not a failure — so it must
    // NOT be logged as a console error (review finding #3).
    expect(consoleErrorSpy).not.toHaveBeenCalled();
    // The user is told: it succeeded, AND that something was silently
    // dropped — never just "Cambios guardados" with no mention of it.
    expect(await screen.findByText(/1 par omitido porque ya no está disponible/i)).toBeInTheDocument();
    consoleErrorSpy.mockRestore();
  });
});

describe('MisSubPMs — counts vs users failure isolation (review finding #3)', () => {
  it('keeps the user list usable and marks counts as unknown when only the counts call fails', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    marcasPmAPI.obtenerConteosSubPMs.mockRejectedValue(new Error('boom'));
    render(<MisSubPMs />);
    expect(await screen.findByRole('button', { name: 'Ana (?)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Beto (?)' })).toBeInTheDocument();
    expect(await screen.findByText(/no se pudieron cargar los conteos/i)).toBeInTheDocument();
    consoleErrorSpy.mockRestore();
  });

  it('surfaces an error and empties the list only when the users call itself fails', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    marcasPmAPI.listarUsuariosPM.mockRejectedValue(new Error('boom'));
    render(<MisSubPMs />);
    expect(await screen.findByText(/error al cargar los usuarios/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Ana/ })).not.toBeInTheDocument();
    consoleErrorSpy.mockRestore();
  });

  it('review finding #4: the blocking users failure is never masked by the cosmetic counts failure', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    // Both fail — the counts effect resolves (rejects) LAST, which would
    // overwrite a shared alert slot if the two competed for one.
    marcasPmAPI.listarUsuariosPM.mockRejectedValue(new Error('users boom'));
    marcasPmAPI.obtenerConteosSubPMs.mockImplementation(
      () => new Promise((_resolve, reject) => setTimeout(() => reject(new Error('counts boom')), 10)),
    );
    render(<MisSubPMs />);
    expect(await screen.findByText(/error al cargar los usuarios/i)).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 20));
    // The blocking message must still be showing after the cosmetic failure
    // resolves later — it must never have been overwritten.
    expect(screen.getByText(/error al cargar los usuarios/i)).toBeInTheDocument();
    consoleErrorSpy.mockRestore();
  });
});

// The unit tests that used to live here (`respuestaDeGuardadoSigueVigente(5,
// 5)` / `(6, 5)`) tested nothing but the `===` operator — they gave false
// confidence that the identity guard in `guardar()` was covered, when in
// fact its caller passed the same closure-frozen value for both arguments,
// making the check unconditionally true regardless of runtime reality. That
// helper function is gone; `guardar()` now compares directly against
// `targetUserIdRef.current` (a ref, not a second copy of the same state).
// I tried to write a genuine integration test that starts a save, changes
// the target user underneath it, and asserts the resolving save does not
// touch the new target's state — see the note in `guardar()` on why that
// branch is currently unreachable through any exposed interaction (the
// `saving` guards added for the earlier user-switch race make it
// impossible), and why the check is kept anyway as defense-in-depth. I did
// not force a passing-either-way test into existence in its place.

describe('MisSubPMs — clavesDesdePayload (gate finding: baseline must reflect what was actually sent)', () => {
  it('builds keys from exactly the pairs sent — a checked-but-omitted ghost pair is never in the result', () => {
    // `paresDeseados` is already the POST-filter payload (see guardar()): a
    // ghost pair that had no matching entry in `pairsByKey` was dropped
    // before this function ever sees it, so there's nothing here for it to
    // accidentally reintroduce.
    const enviados = [{ marca: 'Samsung', categoria: 'Celulares' }];
    const resultado = clavesDesdePayload(enviados);
    expect(resultado).toEqual(new Set([parKey('Samsung', 'Celulares')]));
  });

  it('returns an empty set for an empty payload (a save that only revoked everything)', () => {
    expect(clavesDesdePayload([])).toEqual(new Set());
  });
});

describe('MisSubPMs — pair source split', () => {
  it('titular gets pairs from mis-titularidades, not GET /marcas-pm', async () => {
    const user = userEvent.setup();
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    expect(screen.getByLabelText('Seleccionar Samsung / Celulares')).toBeInTheDocument();
    expect(marcasPmAPI.listarTodosLosPares).not.toHaveBeenCalled();
    expect(marcasPmAPI.misTitularidades).toHaveBeenCalled();
  });

  it('admin gets every pair from GET /marcas-pm, including pairs with no titular', async () => {
    const user = userEvent.setup();
    permisosDenegados.clear();
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    expect(marcasPmAPI.listarTodosLosPares).toHaveBeenCalled();
    expect(marcasPmAPI.misTitularidades).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Seleccionar Huerfana / Sin Titular')).toBeInTheDocument();
    expect(screen.getByText('Sin titular')).toBeInTheDocument();
  });

  it('falls back to titular scope on 403 only', async () => {
    const user = userEvent.setup();
    permisosDenegados.clear();
    marcasPmAPI.listarTodosLosPares.mockRejectedValue({ response: { status: 403, data: { detail: 'No tienes permisos' } } });
    render(<MisSubPMs />);
    await elegirYExpandir(user, 'Ana');
    expect(screen.getByLabelText('Seleccionar Samsung / Celulares')).toBeInTheDocument();
    expect(marcasPmAPI.misTitularidades).toHaveBeenCalled();
  });

  it('does NOT fall back on a 500 — surfaces the error instead', async () => {
    permisosDenegados.clear();
    marcasPmAPI.listarTodosLosPares.mockRejectedValue({
      response: { status: 500, data: { detail: 'Error interno del servidor' } },
    });
    render(<MisSubPMs />);
    expect(await screen.findByText('Error interno del servidor')).toBeInTheDocument();
    expect(marcasPmAPI.misTitularidades).not.toHaveBeenCalled();
  });
});
