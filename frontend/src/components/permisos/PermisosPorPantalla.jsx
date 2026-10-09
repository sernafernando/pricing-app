import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowRight, Check, ChevronDown, ChevronRight, Minus, Plus, RotateCcw, X } from 'lucide-react';
import api, { marcasPmAPI } from '../../services/api';
import { usePermisos } from '../../contexts/PermisosContext';
import SearchInput from '../SearchInput';
import { FacetChips, StatusPill } from '../kit';
import { SCREENS, nombreCategoria } from '../../registry/screenCatalog';
import {
  STATUS,
  agruparPorSeccion,
  coincideBusqueda,
  construirVistaPorPantalla,
  contarFiltros,
  contarParesEfectivos,
  cumpleFiltro,
  permisoCoincideBusqueda,
  permisoCumpleFiltro,
  permisosSinPantalla,
} from '../../registry/permisosAcceso';
import styles from './PermisosPorPantalla.module.css';

const PERMISO_GESTIONAR = 'admin.gestionar_permisos';
const MOTIVO_OVERRIDE = 'Override desde panel de permisos';

const FILTRO_OPCIONES = ['sin_acceso', 'con_overrides', 'criticos', 'depende_de_datos'];
const FILTRO_LABELS = {
  sin_acceso: 'Sin acceso',
  con_overrides: 'Con overrides',
  criticos: 'Críticos',
  depende_de_datos: 'Depende de datos',
};

const STATUS_PILL = {
  [STATUS.ACCEDE]: { tone: 'success', texto: 'Accede' },
  [STATUS.SIN_ACCESO]: { tone: 'danger', texto: 'Sin acceso' },
  [STATUS.CONDICIONAL]: { tone: 'warning', texto: 'Condicional' },
  [STATUS.PUBLICA]: { tone: 'neutral', texto: 'Pública' },
};

const ORIGEN_CHIP = {
  superadmin: 'Superadmin',
  rol: 'Rol',
  override_agregado: '+ Override',
  override_quitado: '− Override',
  sin_permiso: 'Falta',
};

const ORIGEN_TEXTO = {
  superadmin: 'Superadmin: tiene todo',
  rol: 'Concedido por el rol',
  override_agregado: 'Agregado por override',
  override_quitado: 'Quitado por override',
  sin_permiso: 'Falta permiso',
};

const MAX_CHIPS = 2;

/**
 * "Por pantalla" view of one user's permissions: every app screen with its
 * access status, the permissions it needs (any-of) and where each comes from,
 * with inline Conceder / Quitar / Resetear overrides.
 *
 * `permisosUsuario` is the `GET /permisos/usuario/{id}` response. After an
 * override change it calls `onActualizado()` so the parent reloads it.
 */
export default function PermisosPorPantalla({ usuarioId, permisosUsuario, onActualizado, onMensaje }) {
  const { tienePermiso } = usePermisos();
  const [busqueda, setBusqueda] = useState('');
  const [filtro, setFiltro] = useState('');
  const [expandidas, setExpandidas] = useState(() => new Set());
  const [paresDelegados, setParesDelegados] = useState(null);
  const [enCurso, setEnCurso] = useState(null);

  const rol = permisosUsuario?.rol;
  const esSuperadmin = rol === 'SUPERADMIN';
  const puedeEditar = tienePermiso(PERMISO_GESTIONAR) && !esSuperadmin;

  useEffect(() => {
    let cancelado = false;
    setParesDelegados(null);
    // Fail-soft: without a known count no screen is claimed CONDICIONAL.
    Promise.all([marcasPmAPI.listarTodosLosPares(), marcasPmAPI.obtenerConteosSubPMs()])
      .then(([paresRes, conteosRes]) => {
        if (!cancelado) setParesDelegados(contarParesEfectivos(paresRes?.data, conteosRes?.data, usuarioId));
      })
      .catch(() => {
        if (!cancelado) setParesDelegados(null);
      });
    return () => {
      cancelado = true;
    };
  }, [usuarioId]);

  const detallados = permisosUsuario?.permisos_detallados || {};
  const vista = construirVistaPorPantalla(detallados, { rol, paresDelegados }, SCREENS);
  const buscadas = vista.filter((item) => coincideBusqueda(item, busqueda));
  const sueltosBuscados = permisosSinPantalla(detallados, SCREENS).filter((p) =>
    permisoCoincideBusqueda(p, busqueda),
  );
  const conteos = contarFiltros(buscadas, sueltosBuscados);
  const visibles = buscadas.filter((item) => cumpleFiltro(item, filtro || 'todo'));
  const grupos = agruparPorSeccion(visibles);
  const sueltos = sueltosBuscados.filter((p) => permisoCumpleFiltro(p, filtro || 'todo'));

  const alternar = (path) => {
    setExpandidas((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const ejecutar = async (codigo, accion, textoOk, textoError) => {
    setEnCurso(codigo);
    try {
      await accion();
    } catch (error) {
      onMensaje?.({ tipo: 'error', texto: error?.response?.data?.detail || textoError });
      setEnCurso(null);
      return;
    }
    // Success is announced only once the list shows it; a failed reload gets
    // its own message instead (the change itself was saved).
    try {
      await onActualizado?.();
      onMensaje?.({ tipo: 'success', texto: textoOk });
    } catch {
      onMensaje?.({ tipo: 'error', texto: 'El cambio se guardó, pero no se pudo recargar la lista de permisos' });
    } finally {
      setEnCurso(null);
    }
  };

  const forzar = (codigo, concedido) =>
    ejecutar(
      codigo,
      () =>
        api.post('/permisos/override', {
          usuario_id: usuarioId,
          permiso_codigo: codigo,
          concedido,
          motivo: MOTIVO_OVERRIDE,
        }),
      concedido ? 'Permiso concedido' : 'Permiso quitado',
      'Error al modificar permiso',
    );

  const resetear = (codigo) =>
    ejecutar(
      codigo,
      () => api.delete(`/permisos/override/${usuarioId}/${codigo}`),
      'Vuelto al permiso base del rol',
      'Error al resetear permiso',
    );

  const acciones = { puedeEditar, enCurso, forzar, resetear };

  return (
    <div className={styles.wrapper}>
      <div className={styles.toolbar}>
        <SearchInput
          value={busqueda}
          onChange={setBusqueda}
          placeholder="Buscá una pantalla o permiso (ej: métricas, compras, editar precio)…"
          size="sm"
          className={styles.search}
        />
        <div className={styles.filtros}>
          <span className={styles.filtrosLabel}>Filtros</span>
          <FacetChips
            label="Filtrar pantallas"
            options={FILTRO_OPCIONES}
            labels={FILTRO_LABELS}
            counts={conteos}
            total={conteos.todo}
            activeValue={filtro}
            onChange={setFiltro}
          />
        </div>
      </div>

      <div className={styles.lista}>
        {grupos.length === 0 && sueltos.length === 0 && (
          <div className={styles.vacio}>No hay pantallas ni permisos que coincidan.</div>
        )}

        {grupos.map((grupo) => (
          <section key={grupo.section} className={styles.grupo} aria-label={grupo.section}>
            <header className={styles.grupoHeader}>
              <h3 className={styles.grupoTitulo}>{grupo.section}</h3>
              <span className={styles.grupoConteo}>
                {grupo.accesibles} de {grupo.total} accesibles
              </span>
            </header>
            <ul className={styles.filas}>
              {grupo.items.map((item) => (
                <FilaPantalla
                  key={item.path}
                  item={item}
                  expandida={expandidas.has(item.path)}
                  onAlternar={() => alternar(item.path)}
                  acciones={acciones}
                />
              ))}
            </ul>
          </section>
        ))}

        {sueltos.length > 0 && (
          <section className={styles.grupo} aria-label="Permisos sin pantalla">
            <header className={styles.grupoHeader}>
              <h3 className={styles.grupoTitulo}>Permisos sin pantalla</h3>
              <span className={styles.grupoConteo}>Acciones dentro de pantallas o del backend</span>
            </header>
            <ul className={styles.detalleLista}>
              {sueltos.map((permiso) => (
                <FilaPermiso key={permiso.codigo} permiso={permiso} acciones={acciones} mostrarCategoria />
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}

function FilaPantalla({ item, expandida, onAlternar, acciones }) {
  const { acceso } = item;
  const pill = STATUS_PILL[acceso.status];
  const condicional = acceso.status === STATUS.CONDICIONAL;
  const detalleId = `permisos-detalle-${item.path}`;
  const chips = acceso.filas.slice(0, MAX_CHIPS);
  const restantes = acceso.filas.length - chips.length;

  // One-click grant only when there is a single, known permission to grant.
  const unicaFalta =
    acceso.status === STATUS.SIN_ACCESO && acceso.filas.length === 1 && !acceso.filas[0].desconocido
      ? acceso.filas[0]
      : null;

  return (
    <li className={`${styles.fila} ${condicional ? styles.filaCondicional : ''}`}>
      <div className={styles.filaPrincipal}>
        <button
          type="button"
          className={styles.toggle}
          aria-expanded={expandida}
          aria-controls={detalleId}
          onClick={onAlternar}
          disabled={acceso.filas.length === 0}
        >
          {acceso.filas.length > 0 &&
            (expandida ? <ChevronDown size={14} aria-hidden="true" /> : <ChevronRight size={14} aria-hidden="true" />)}
          {condicional && <AlertTriangle size={14} className={styles.iconoAviso} aria-hidden="true" />}
          <span className={styles.label}>{item.label}</span>
          <code className={styles.path}>{item.path}</code>
        </button>

        <StatusPill tone={pill.tone}>{pill.texto}</StatusPill>

        <div className={styles.requiere}>
          {acceso.filas.length === 0 ? (
            <span className={styles.muted}>Sin permiso requerido</span>
          ) : (
            <>
              {chips.map((fila) => (
                <code key={fila.codigo} className={styles.codigoChip}>
                  {fila.codigo}
                </code>
              ))}
              {restantes > 0 && <span className={styles.muted}>+{restantes}</span>}
            </>
          )}
        </div>

        {acceso.origen && (
          <span className={`${styles.origenChip} ${styles[`origen_${acceso.origen}`] || ''}`}>
            {ORIGEN_CHIP[acceso.origen]}
          </span>
        )}

        {unicaFalta && acciones.puedeEditar && (
          <button
            type="button"
            className={styles.btnConceder}
            aria-label={`Conceder acceso a ${item.label}`}
            disabled={acciones.enCurso !== null}
            onClick={() => acciones.forzar(unicaFalta.codigo, true)}
          >
            <Plus size={12} aria-hidden="true" /> Conceder
          </button>
        )}
      </div>

      {condicional && (
        <div className={styles.aviso}>
          <span>
            Tiene el permiso, pero no tiene pares marca/categoría delegados: no va a ver datos.
          </span>
          <Link to="/mis-sub-pms" className={styles.avisoLink}>
            Ir a Mis Sub-PMs <ArrowRight size={12} aria-hidden="true" />
          </Link>
        </div>
      )}

      {expandida && acceso.filas.length > 0 && (
        <div id={detalleId} className={styles.detalle}>
          {item.nota && <p className={styles.nota}>{item.nota}</p>}
          <ul className={styles.detalleLista}>
            {acceso.filas.map((fila) => (
              <FilaPermiso key={fila.codigo} permiso={fila} acciones={acciones} />
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

function FilaPermiso({ permiso, acciones, mostrarCategoria = false }) {
  const { puedeEditar, enCurso, forzar, resetear } = acciones;
  const tieneOverride = permiso.override !== null && permiso.override !== undefined;
  const ocupado = enCurso !== null;

  let accion = null;
  if (puedeEditar && !permiso.desconocido) {
    if (tieneOverride) {
      accion = (
        <button
          type="button"
          className={styles.btnSecundario}
          aria-label={`Resetear ${permiso.codigo}`}
          disabled={ocupado}
          onClick={() => resetear(permiso.codigo)}
        >
          <RotateCcw size={12} aria-hidden="true" /> Resetear
        </button>
      );
    } else if (permiso.efectivo) {
      accion = (
        <button
          type="button"
          className={styles.btnQuitar}
          aria-label={`Quitar ${permiso.codigo}`}
          disabled={ocupado}
          onClick={() => forzar(permiso.codigo, false)}
        >
          <Minus size={12} aria-hidden="true" /> Quitar
        </button>
      );
    } else {
      accion = (
        <button
          type="button"
          className={styles.btnConceder}
          aria-label={`Conceder ${permiso.codigo}`}
          disabled={ocupado}
          onClick={() => forzar(permiso.codigo, true)}
        >
          <Plus size={12} aria-hidden="true" /> Conceder
        </button>
      );
    }
  }

  return (
    <li className={`${styles.permiso} ${permiso.efectivo ? '' : styles.permisoFalta}`}>
      <span className={permiso.efectivo ? styles.iconoOk : styles.iconoFalta} aria-hidden="true">
        {permiso.efectivo ? <Check size={14} /> : <X size={14} />}
      </span>
      <div className={styles.permisoInfo}>
        <div className={styles.permisoLinea}>
          <code className={styles.permisoCodigo}>{permiso.codigo}</code>
          {!permiso.desconocido && <span className={styles.permisoNombre}>{permiso.nombre}</span>}
          {permiso.es_critico && <StatusPill tone="danger">Crítico</StatusPill>}
          {mostrarCategoria && <span className={styles.muted}>{nombreCategoria(permiso.categoria)}</span>}
        </div>
        {permiso.descripcion && <div className={styles.permisoDescripcion}>{permiso.descripcion}</div>}
      </div>
      <span className={styles.permisoOrigen}>
        {permiso.desconocido ? 'No existe en el sistema' : ORIGEN_TEXTO[permiso.origen] || permiso.origen}
      </span>
      {accion}
    </li>
  );
}
