import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  RefreshCw,
  Plus,
  Ban,
  Check,
  X,
  AlertCircle,
  CheckCircle2,
  Eye,
  Play,
  Wrench,
  RotateCcw,
  AlertTriangle,
  Pencil,
  Trash2,
  Save,
} from 'lucide-react';
import api from '../services/api';
import SearchInput from '../components/SearchInput';
import PrearmadoForm from '../components/PrearmadoForm';
import sharedStyles from './PedidosPreparacion.module.css';
import styles from './Prearmado.module.css';

const ESTADOS = ['pendiente', 'en_proceso', 'armado', 'consumido', 'anulado'];
const ESTADO_LABEL = {
  pendiente: 'Pendiente',
  en_proceso: 'En proceso',
  armado: 'Armado',
  consumido: 'Consumido',
  anulado: 'Anulado',
};
const ESTADO_CLASS = {
  pendiente: styles.estadoPendiente,
  en_proceso: styles.estadoEnProceso,
  armado: styles.estadoArmado,
  consumido: styles.estadoConsumido,
  anulado: styles.estadoAnulado,
};
const WINDOWS_LABEL = { home: 'Win 11 Home', pro: 'Win 11 Pro' };

const formatFechaArg = (iso) =>
  iso ? new Date(iso).toLocaleString('es-AR', { hour12: false }) : '';

// Iconos para cada transición de estado (avance vs retroceso)
const TRANSITION_ICON = {
  pendiente: RotateCcw, // volver atrás
  en_proceso: Play, // avanzar a en proceso
  armado: Wrench, // marcar armado
};

export default function Prearmado() {
  const [prearmados, setPrearmados] = useState([]);
  const [prearmadosActivos, setPrearmadosActivos] = useState([]); // para stats arriba (sin filtros)
  const [loading, setLoading] = useState(true);
  const [filtroEstado, setFiltroEstado] = useState('');
  const [filtroCodigo, setFiltroCodigo] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [rematching, setRematching] = useState(false);
  const [statusMsg, setStatusMsg] = useState(null);
  const [error, setError] = useState(null);
  const [anularPrearmado, setAnularPrearmado] = useState(null);
  const [motivoAnular, setMotivoAnular] = useState('');
  const [verPrearmado, setVerPrearmado] = useState(null);
  const [loadingDetalle, setLoadingDetalle] = useState(false);
  const [editandoSerialId, setEditandoSerialId] = useState(null);
  const [editValor, setEditValor] = useState('');
  const [editValidacion, setEditValidacion] = useState(null);
  const [editForce, setEditForce] = useState(false);
  const [savingSerial, setSavingSerial] = useState(false);
  const [confirmDeleteSerial, setConfirmDeleteSerial] = useState(null);
  const [notasEdit, setNotasEdit] = useState('');
  const [guardandoNotas, setGuardandoNotas] = useState(false);

  const cargar = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {};
      if (filtroEstado) params.estado = filtroEstado;
      if (filtroCodigo) params.codigo = filtroCodigo;
      const resp = await api.get('/prearmado', { params });
      setPrearmados(resp.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Error cargando prearmados');
    } finally {
      setLoading(false);
    }
  }, [filtroEstado, filtroCodigo]);

  // Fetch separado para las stats: sin filtros, solo activos (pendiente/en_proceso/armado).
  // Cuando un prearmado pasa a consumido o anulado, deja de contar.
  // NOTE: el endpoint topa en limit=1000. Si hay más, conviene endpoint de stats agregadas.
  const cargarStats = useCallback(async () => {
    try {
      const resp = await api.get('/prearmado', { params: { limit: 1000 } });
      const activos = (resp.data || []).filter(
        (p) => p.estado === 'pendiente' || p.estado === 'en_proceso' || p.estado === 'armado',
      );
      setPrearmadosActivos(activos);
    } catch (err) {
      console.error('Error cargando stats de prearmados', err);
      setPrearmadosActivos([]);
    }
  }, []);

  // Stats agrupadas por combo (solo activos, ignora filtros — siempre muestran lo que HAY)
  const statsActivas = useMemo(() => {
    const map = new Map();
    for (const p of prearmadosActivos) {
      const key = p.combo_item_id;
      if (!map.has(key)) {
        map.set(key, {
          combo_item_id: p.combo_item_id,
          combo_item_code: p.combo_item_code,
          combo_item_desc: p.combo_item_desc,
          incluye_windows: p.incluye_windows,
          total: 0,
          pendiente: 0,
          en_proceso: 0,
          armado: 0,
        });
      }
      const stat = map.get(key);
      stat.total += 1;
      if (p.estado in stat) stat[p.estado] += 1;
    }
    return Array.from(map.values()).sort((a, b) => b.total - a.total);
  }, [prearmadosActivos]);

  const totalActivos = prearmadosActivos.length;

  useEffect(() => {
    const t = setTimeout(cargar, filtroCodigo ? 300 : 0);
    return () => clearTimeout(t);
  }, [cargar, filtroCodigo]);

  // Stats al mount + cuando se recarga manualmente
  useEffect(() => {
    cargarStats();
  }, [cargarStats]);

  const rematchear = async () => {
    setRematching(true);
    setStatusMsg(null);
    try {
      const resp = await api.post('/prearmado/rematch');
      const { matched, total_checked, errors } = resp.data;
      setStatusMsg({
        tipo: 'ok',
        texto: `Matcher: ${matched}/${total_checked} consumidos${errors.length ? ` (${errors.length} errores)` : ''}`,
      });
      await cargar();
      await cargarStats();
    } catch (err) {
      setStatusMsg({
        tipo: 'error',
        texto: err.response?.data?.detail || err.message || 'Error al rematchear',
      });
    } finally {
      setRematching(false);
      setTimeout(() => setStatusMsg(null), 6000);
    }
  };

  const cambiarEstado = async (p, nuevoEstado) => {
    setError(null);
    try {
      await api.patch(`/prearmado/${p.id}`, { estado: nuevoEstado });
      await cargar();
      await cargarStats();
      if (verPrearmado && verPrearmado.id === p.id) {
        await recargarDetalle(p.id);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo cambiar el estado');
    }
  };

  const onClickAnular = (p) => {
    setAnularPrearmado(p);
    setMotivoAnular('');
  };

  const cerrarAnular = () => {
    setAnularPrearmado(null);
    setMotivoAnular('');
  };

  const confirmarAnular = async () => {
    if (!anularPrearmado) return;
    setError(null);
    try {
      const anuladoId = anularPrearmado.id;
      await api.patch(`/prearmado/${anuladoId}`, {
        estado: 'anulado',
        notas: motivoAnular || null,
      });
      cerrarAnular();
      await cargar();
      await cargarStats();
      // Si estaba abierto el detalle del que anulamos, cerrarlo (es terminal).
      if (verPrearmado && verPrearmado.id === anuladoId) {
        cerrarDetalle();
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo anular');
    }
  };

  const abrirDetalle = async (p) => {
    setError(null);
    setLoadingDetalle(true);
    setVerPrearmado({ id: p.id, codigo: p.codigo, seriales: [], _loading: true });
    try {
      const resp = await api.get(`/prearmado/${p.id}`);
      setVerPrearmado(resp.data);
      setNotasEdit(resp.data.notas || '');
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo cargar el detalle');
      setVerPrearmado(null);
    } finally {
      setLoadingDetalle(false);
    }
  };

  const cerrarDetalle = () => {
    setVerPrearmado(null);
    setEditandoSerialId(null);
    setEditValor('');
    setEditValidacion(null);
    setEditForce(false);
    setNotasEdit('');
  };

  const guardarNotas = async () => {
    if (!verPrearmado) return;
    setGuardandoNotas(true);
    setError(null);
    try {
      const valor = notasEdit.trim();
      const resp = await api.patch(`/prearmado/${verPrearmado.id}`, {
        notas: valor === '' ? null : valor,
      });
      setVerPrearmado(resp.data);
      setNotasEdit(resp.data.notas || '');
      await cargar();
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo guardar la nota');
    } finally {
      setGuardandoNotas(false);
    }
  };

  const recargarDetalle = async (prearmadoId) => {
    try {
      const resp = await api.get(`/prearmado/${prearmadoId}`);
      setVerPrearmado(resp.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo refrescar el detalle');
    }
  };

  const iniciarEdicion = (s) => {
    setEditandoSerialId(s.id);
    setEditValor(s.serial || '');
    setEditValidacion(null);
    setEditForce(false);
  };

  const cancelarEdicion = () => {
    setEditandoSerialId(null);
    setEditValor('');
    setEditValidacion(null);
    setEditForce(false);
  };

  const validarEdicion = async (item_id_esperado) => {
    if (!editValor || !editValor.trim()) {
      setEditValidacion(null);
      return;
    }
    try {
      const resp = await api.post('/prearmado/validar-serial', {
        serial: editValor.trim(),
        item_id_esperado,
      });
      setEditValidacion(resp.data);
    } catch {
      setEditValidacion({ valid: false, motivo: 'NetworkError' });
    }
  };

  const guardarEdicion = async (s) => {
    if (!verPrearmado || !editValor.trim()) return;
    setSavingSerial(true);
    setError(null);
    try {
      await api.patch(`/prearmado/${verPrearmado.id}/seriales/${s.id}`, {
        serial: editValor.trim(),
        force: editForce,
      });
      await recargarDetalle(verPrearmado.id);
      await cargar();
      await cargarStats();
      cancelarEdicion();
    } catch (err) {
      const detail = err.response?.data?.detail;
      const msg =
        typeof detail === 'object'
          ? `Serial inválido (${detail.motivo}). Marcá "forzar" para guardar igual.`
          : detail || 'No se pudo guardar el serial';
      setError(msg);
    } finally {
      setSavingSerial(false);
    }
  };

  const onClickBorrarSerial = (s) => setConfirmDeleteSerial(s);
  const cerrarConfirmDelete = () => setConfirmDeleteSerial(null);

  const confirmarBorrarSerial = async () => {
    if (!confirmDeleteSerial || !verPrearmado) return;
    setError(null);
    try {
      await api.delete(`/prearmado/${verPrearmado.id}/seriales/${confirmDeleteSerial.id}`);
      setConfirmDeleteSerial(null);
      await recargarDetalle(verPrearmado.id);
      await cargar();
      await cargarStats();
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo borrar el serial');
    }
  };

  const proximosEstados = (estado) => {
    switch (estado) {
      case 'pendiente':
        return ['en_proceso'];
      case 'en_proceso':
        return ['armado', 'pendiente'];
      case 'armado':
        return ['en_proceso'];
      default:
        return [];
    }
  };

  return (
    <div className={sharedStyles.container}>
      <div className={sharedStyles.header}>
        <h1 className={sharedStyles.title}>Prearmado de Combos</h1>
      </div>

      {totalActivos > 0 && (
        <section className={styles.statsResumen}>
          <header className={styles.statsResumenHeader}>
            <span className={styles.statsResumenEyebrow}>En curso</span>
            <span className={styles.statsResumenSubtitulo}>
              {statsActivas.length} combo{statsActivas.length === 1 ? '' : 's'} ·{' '}
              <strong>{totalActivos}</strong> prearmado{totalActivos === 1 ? '' : 's'}
            </span>
          </header>
          <div className={styles.statsResumenGrid}>
            {statsActivas.map((s) => (
              <article key={s.combo_item_id} className={styles.statsMiniCard}>
                <div className={styles.statsMiniCardHead}>
                  <span className={styles.statsMiniCardCode} title={s.combo_item_desc || ''}>
                    {s.combo_item_code}
                  </span>
                  {s.incluye_windows && (
                    <span className={styles.windowsBadge}>
                      {WINDOWS_LABEL[s.incluye_windows]}
                    </span>
                  )}
                </div>
                <div className={styles.statsMiniCardBody}>
                  <div className={styles.statsMiniCardTotalBox}>
                    <span className={styles.statsMiniCardTotalValue}>{s.total}</span>
                    <span className={styles.statsMiniCardTotalLabel}>Total</span>
                  </div>
                  <div className={styles.statsMiniBreakdown}>
                    {s.pendiente > 0 && (
                      <div className={styles.statsDotRow}>
                        <span className={`${styles.statsDot} ${styles.statsDotPendiente}`} />
                        <span className={styles.statsDotCount}>{s.pendiente}</span>
                        <span className={styles.statsDotLabel}>Pendiente</span>
                      </div>
                    )}
                    {s.en_proceso > 0 && (
                      <div className={styles.statsDotRow}>
                        <span className={`${styles.statsDot} ${styles.statsDotEnProceso}`} />
                        <span className={styles.statsDotCount}>{s.en_proceso}</span>
                        <span className={styles.statsDotLabel}>En proceso</span>
                      </div>
                    )}
                    {s.armado > 0 && (
                      <div className={styles.statsDotRow}>
                        <span className={`${styles.statsDot} ${styles.statsDotArmado}`} />
                        <span className={styles.statsDotCount}>{s.armado}</span>
                        <span className={styles.statsDotLabel}>Armado</span>
                      </div>
                    )}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {statusMsg && (
        <div
          className={
            statusMsg.tipo === 'error'
              ? styles.statusBannerError
              : `${styles.statusBanner} ${styles.statusBannerOk}`
          }
          role="status"
        >
          {statusMsg.tipo === 'error' ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
          <span>{statusMsg.texto}</span>
        </div>
      )}

      <div className={sharedStyles.tabControls}>
        <button
          className={`${styles.actionBtn} ${styles.actionBtnAccent}`}
          onClick={() => setShowForm(true)}
          disabled={loading}
        >
          <Plus size={16} /> Nuevo prearmado
        </button>
        <button className={styles.actionBtn} onClick={rematchear} disabled={rematching || loading}>
          <RefreshCw size={16} /> {rematching ? 'Matcheando...' : 'Re-matchear'}
        </button>
        <button className={styles.actionBtn} onClick={cargar} disabled={loading}>
          Actualizar
        </button>
      </div>

      <div className={sharedStyles.filtrosContainer}>
        <div className={sharedStyles.filtrosRow}>
          <select
            value={filtroEstado}
            onChange={(e) => setFiltroEstado(e.target.value)}
            className={sharedStyles.select}
          >
            <option value="">Todos los estados</option>
            {ESTADOS.map((e) => (
              <option key={e} value={e}>
                {ESTADO_LABEL[e]}
              </option>
            ))}
          </select>

          <SearchInput
            value={filtroCodigo}
            onChange={setFiltroCodigo}
            placeholder="Buscar por código..."
            className={sharedStyles.searchInput}
            size="sm"
          />
        </div>
      </div>

      {error && (
        <div className={styles.errorBanner} role="alert">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <div className={sharedStyles.loading}>Cargando prearmados...</div>
      ) : (
        <div className={sharedStyles.tableContainer}>
          <table className={sharedStyles.table}>
            <thead>
              <tr>
                <th>Código</th>
                <th>Combo</th>
                <th>Estado</th>
                <th>Seriales</th>
                <th>Windows</th>
                <th>Consumido en</th>
                <th>Creado</th>
                <th aria-label="Acciones" />
              </tr>
            </thead>
            <tbody>
              {prearmados.length === 0 ? (
                <tr>
                  <td colSpan={8} className={sharedStyles.empty}>
                    No hay prearmados
                  </td>
                </tr>
              ) : (
                prearmados.map((p) => {
                  const proximos = proximosEstados(p.estado);
                  const terminal = p.estado === 'consumido' || p.estado === 'anulado';
                  return (
                    <tr
                      key={p.id}
                      className={styles.rowClickable}
                      onClick={() => abrirDetalle(p)}
                      title="Ver detalle y cambiar estado"
                    >
                      <td className={styles.codigoCell}>{p.codigo}</td>
                      <td>
                        <div className={sharedStyles.producto}>
                          <strong>{p.combo_item_code}</strong>
                          <span className={sharedStyles.descripcion}>{p.combo_item_desc}</span>
                        </div>
                      </td>
                      <td>
                        <span className={ESTADO_CLASS[p.estado]}>{ESTADO_LABEL[p.estado]}</span>
                      </td>
                      <td className={sharedStyles.cantidad}>
                        {p.seriales_validados}/{p.seriales_total}
                        {p.seriales_completos && (
                          <Check size={14} className={styles.completoIcon} aria-label="Completo" />
                        )}
                      </td>
                      <td>
                        {p.incluye_windows ? (
                          <span className={styles.windowsBadge}>{WINDOWS_LABEL[p.incluye_windows]}</span>
                        ) : (
                          <span className={styles.muted}>—</span>
                        )}
                      </td>
                      <td>
                        {p.consumido_por_soh_id ? (
                          <span>SOH {p.consumido_por_soh_id}</span>
                        ) : (
                          <span className={styles.muted}>—</span>
                        )}
                      </td>
                      <td>
                        <span className={styles.smallMuted}>
                          {formatFechaArg(p.created_at)}
                        </span>
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <div className={styles.acciones}>
                          <button
                            type="button"
                            className={styles.iconBtn}
                            onClick={() => abrirDetalle(p)}
                            title="Ver detalle y seriales"
                            aria-label="Ver detalle"
                          >
                            <Eye size={14} />
                          </button>
                          {proximos.length > 0 && <span className={styles.accionSeparator} />}
                          {proximos.map((next) => {
                            const Icon = TRANSITION_ICON[next] || Play;
                            return (
                              <button
                                key={next}
                                type="button"
                                className={styles.iconBtn}
                                onClick={() => cambiarEstado(p, next)}
                                title={`Pasar a ${ESTADO_LABEL[next]}`}
                                aria-label={`Pasar a ${ESTADO_LABEL[next]}`}
                                disabled={terminal}
                              >
                                <Icon size={14} />
                              </button>
                            );
                          })}
                          {!terminal && (
                            <>
                              <span className={styles.accionSeparator} />
                              <button
                                type="button"
                                className={`${styles.iconBtn} ${styles.iconBtnDanger}`}
                                onClick={() => onClickAnular(p)}
                                title="Anular"
                                aria-label="Anular"
                              >
                                <Ban size={14} />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className={sharedStyles.footer}>
        <span>Mostrando {prearmados.length} prearmados</span>
      </div>

      {showForm && (
        <PrearmadoForm
          onClose={() => setShowForm(false)}
          onSaved={async () => {
            await cargar();
            await cargarStats();
          }}
        />
      )}

      {anularPrearmado && (
        <div className={styles.modalBackdrop} onClick={cerrarAnular}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2 className={styles.modalTitle}>Anular prearmado</h2>
              <button
                type="button"
                className={styles.modalCloseBtn}
                onClick={cerrarAnular}
                aria-label="Cerrar"
              >
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p className={styles.confirmText}>
                Vas a anular el prearmado <strong>{anularPrearmado.codigo}</strong> (
                {anularPrearmado.combo_item_code}). Esta acción es terminal — no se puede revertir.
              </p>
              <label className={styles.comboSelectorLabel}>Motivo (opcional)</label>
              <input
                type="text"
                value={motivoAnular}
                onChange={(e) => setMotivoAnular(e.target.value)}
                placeholder="Ej: componente roto, error de carga..."
                className={styles.confirmInput}
                autoFocus
              />
            </div>
            <div className={styles.modalFooter}>
              <button type="button" className={styles.actionBtn} onClick={cerrarAnular}>
                Cancelar
              </button>
              <button
                type="button"
                className={`${styles.actionBtn} ${styles.actionBtnAccent}`}
                onClick={confirmarAnular}
              >
                Confirmar anulación
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDeleteSerial && (
        <div className={styles.modalBackdrop} onClick={cerrarConfirmDelete}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2 className={styles.modalTitle}>Borrar serial</h2>
              <button
                type="button"
                className={styles.modalCloseBtn}
                onClick={cerrarConfirmDelete}
                aria-label="Cerrar"
              >
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <p className={styles.confirmText}>
                Vas a borrar el serial{' '}
                <code className={styles.codigoCell}>
                  {confirmDeleteSerial.serial || '(sin serie)'}
                </code>{' '}
                del componente <strong>{confirmDeleteSerial.componente_item_code}</strong>.
              </p>
              <p className={styles.smallMuted}>
                Después podés volver a cargarlo si te equivocás.
              </p>
            </div>
            <div className={styles.modalFooter}>
              <button type="button" className={styles.actionBtn} onClick={cerrarConfirmDelete}>
                Cancelar
              </button>
              <button
                type="button"
                className={`${styles.actionBtn} ${styles.actionBtnAccent}`}
                onClick={confirmarBorrarSerial}
              >
                Borrar
              </button>
            </div>
          </div>
        </div>
      )}

      {verPrearmado && (
        <div className={styles.modalBackdrop} onClick={cerrarDetalle}>
          <div className={`${styles.modal} ${styles.modalLarge}`} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2 className={styles.modalTitle}>
                Prearmado <span className={styles.codigoCell}>{verPrearmado.codigo}</span>
              </h2>
              <button
                type="button"
                className={styles.modalCloseBtn}
                onClick={cerrarDetalle}
                aria-label="Cerrar"
              >
                <X size={18} />
              </button>
            </div>
            <div className={styles.modalBody}>
              {loadingDetalle || verPrearmado._loading ? (
                <div className={sharedStyles.loading}>Cargando detalle...</div>
              ) : (
                <>
                  <div className={styles.detalleGrid}>
                    <div className={styles.detalleField}>
                      <span className={styles.detalleLabel}>Combo</span>
                      <span className={styles.detalleValue}>
                        <strong>{verPrearmado.combo_item_code}</strong>
                      </span>
                      <span className={styles.smallMuted}>{verPrearmado.combo_item_desc}</span>
                    </div>
                    <div className={styles.detalleField}>
                      <span className={styles.detalleLabel}>Estado</span>
                      <span className={ESTADO_CLASS[verPrearmado.estado]}>
                        {ESTADO_LABEL[verPrearmado.estado]}
                      </span>
                      {(() => {
                        const proximos = proximosEstados(verPrearmado.estado);
                        const terminal =
                          verPrearmado.estado === 'consumido' ||
                          verPrearmado.estado === 'anulado';
                        if (terminal) return null;
                        return (
                          <div className={styles.detalleAcciones}>
                            {proximos.map((next) => {
                              const Icon = TRANSITION_ICON[next] || Play;
                              return (
                                <button
                                  key={next}
                                  type="button"
                                  className={styles.actionBtn}
                                  onClick={() => cambiarEstado(verPrearmado, next)}
                                >
                                  <Icon size={14} /> {ESTADO_LABEL[next]}
                                </button>
                              );
                            })}
                            <button
                              type="button"
                              className={`${styles.actionBtn} ${styles.actionBtnDanger}`}
                              onClick={() => onClickAnular(verPrearmado)}
                            >
                              <Ban size={14} /> Anular
                            </button>
                          </div>
                        );
                      })()}
                    </div>
                    {verPrearmado.incluye_windows && (
                      <div className={styles.detalleField}>
                        <span className={styles.detalleLabel}>Windows</span>
                        <span className={styles.windowsBadge}>
                          {WINDOWS_LABEL[verPrearmado.incluye_windows]}
                        </span>
                      </div>
                    )}
                    <div className={styles.detalleField}>
                      <span className={styles.detalleLabel}>Creado</span>
                      <span className={styles.smallMuted}>
                        {formatFechaArg(verPrearmado.created_at)}
                      </span>
                    </div>
                    {verPrearmado.consumido_por_soh_id && (
                      <div className={styles.detalleField}>
                        <span className={styles.detalleLabel}>Consumido en</span>
                        <span>SOH {verPrearmado.consumido_por_soh_id}</span>
                        {verPrearmado.consumido_at && (
                          <span className={styles.smallMuted}>
                            {formatFechaArg(verPrearmado.consumido_at)}
                          </span>
                        )}
                      </div>
                    )}
                    <div className={`${styles.detalleField} ${styles.detalleFieldFull}`}>
                      <span className={styles.detalleLabel}>Notas</span>
                      <textarea
                        value={notasEdit}
                        onChange={(e) => setNotasEdit(e.target.value)}
                        rows={2}
                        className={styles.notasTextarea}
                        placeholder="Notas, pendientes, observaciones..."
                        disabled={guardandoNotas}
                      />
                      {notasEdit !== (verPrearmado.notas || '') && (
                        <div className={styles.notasActions}>
                          <button
                            type="button"
                            className={`${styles.actionBtn} ${styles.actionBtnAccent}`}
                            onClick={guardarNotas}
                            disabled={guardandoNotas}
                          >
                            {guardandoNotas ? 'Guardando...' : 'Guardar nota'}
                          </button>
                          <button
                            type="button"
                            className={styles.actionBtn}
                            onClick={() => setNotasEdit(verPrearmado.notas || '')}
                            disabled={guardandoNotas}
                          >
                            Descartar
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  <h3 className={styles.detalleSectionTitle}>
                    Seriales cargados ({verPrearmado.seriales_validados}/{verPrearmado.seriales_total})
                  </h3>
                  {verPrearmado.seriales.length === 0 ? (
                    <div className={styles.muted}>No hay seriales cargados todavía.</div>
                  ) : (
                    <div className={styles.serialesTableWrap}>
                      <table className={styles.serialesTable}>
                        <thead>
                          <tr>
                            <th>Componente</th>
                            <th>Serial</th>
                            <th>Estado</th>
                            <th aria-label="Acciones" />
                          </tr>
                        </thead>
                        <tbody>
                          {verPrearmado.seriales.map((s) => {
                            const detalleTerminal =
                              verPrearmado.estado === 'consumido' ||
                              verPrearmado.estado === 'anulado';
                            const enEdicion = editandoSerialId === s.id;
                            return (
                              <tr key={s.id}>
                                <td>
                                  <div className={sharedStyles.producto}>
                                    <strong>{s.componente_item_code}</strong>
                                    <span className={sharedStyles.descripcion}>
                                      {s.componente_item_desc}
                                    </span>
                                  </div>
                                </td>
                                <td className={styles.serialCell}>
                                  {enEdicion ? (
                                    <div className={styles.serialEditRow}>
                                      <input
                                        type="text"
                                        className={styles.serialEditInput}
                                        value={editValor}
                                        onChange={(e) => setEditValor(e.target.value)}
                                        onBlur={() => validarEdicion(s.componente_item_id)}
                                        autoFocus
                                      />
                                      {editValidacion?.valid && (
                                        <Check size={14} className={styles.validacionOk} />
                                      )}
                                      {editValidacion && !editValidacion.valid && (
                                        <AlertTriangle
                                          size={14}
                                          className={styles.validacionWarn}
                                        />
                                      )}
                                    </div>
                                  ) : s.serial ? (
                                    <code className={styles.codigoCell}>{s.serial}</code>
                                  ) : (
                                    <span className={styles.muted}>(no requiere)</span>
                                  )}
                                  {enEdicion && editValidacion && !editValidacion.valid && (
                                    <label className={styles.forceInline}>
                                      <input
                                        type="checkbox"
                                        checked={editForce}
                                        onChange={(e) => setEditForce(e.target.checked)}
                                      />
                                      Forzar (
                                      {editValidacion.motivo === 'SerialNotFound'
                                        ? 'no existe en ERP'
                                        : editValidacion.motivo === 'ItemMismatch'
                                          ? `otro item: ${editValidacion.item_code_real || editValidacion.item_id_real}`
                                          : editValidacion.motivo === 'AlreadyInSaleOrder'
                                            ? `ya en pedido SOH ${editValidacion.usado_en_soh_id}`
                                            : editValidacion.motivo === 'AlreadyInvoiced'
                                              ? `ya facturado en SOH ${editValidacion.usado_en_factura_soh_id}`
                                              : 'inválido'}
                                      )
                                    </label>
                                  )}
                                </td>
                                <td>
                                  {!s.requiere_serie ? (
                                    <span className={styles.noRequiereSerie}>No-serializable</span>
                                  ) : s.validado ? (
                                    <span className={styles.serialOk}>
                                      <Check size={14} /> Validado
                                    </span>
                                  ) : (
                                    <span className={styles.serialWarn}>
                                      <AlertTriangle size={14} /> Sin validar
                                    </span>
                                  )}
                                </td>
                                <td>
                                  <div className={styles.acciones}>
                                    {enEdicion ? (
                                      <>
                                        <button
                                          type="button"
                                          className={styles.iconBtn}
                                          onClick={() => guardarEdicion(s)}
                                          disabled={savingSerial || !editValor.trim()}
                                          title="Guardar"
                                          aria-label="Guardar"
                                        >
                                          <Save size={14} />
                                        </button>
                                        <button
                                          type="button"
                                          className={styles.iconBtn}
                                          onClick={cancelarEdicion}
                                          disabled={savingSerial}
                                          title="Cancelar"
                                          aria-label="Cancelar"
                                        >
                                          <X size={14} />
                                        </button>
                                      </>
                                    ) : (
                                      !detalleTerminal && (
                                        <>
                                          {s.requiere_serie && (
                                            <button
                                              type="button"
                                              className={styles.iconBtn}
                                              onClick={() => iniciarEdicion(s)}
                                              title="Editar serial"
                                              aria-label="Editar serial"
                                            >
                                              <Pencil size={14} />
                                            </button>
                                          )}
                                          <button
                                            type="button"
                                            className={`${styles.iconBtn} ${styles.iconBtnDanger}`}
                                            onClick={() => onClickBorrarSerial(s)}
                                            title="Borrar"
                                            aria-label="Borrar"
                                          >
                                            <Trash2 size={14} />
                                          </button>
                                        </>
                                      )
                                    )}
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </div>
            <div className={styles.modalFooter}>
              <button type="button" className={styles.actionBtn} onClick={cerrarDetalle}>
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
