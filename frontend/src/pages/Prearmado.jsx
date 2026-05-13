import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Plus, Ban, Check, X, AlertCircle, CheckCircle2 } from 'lucide-react';
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

export default function Prearmado() {
  const [prearmados, setPrearmados] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filtroEstado, setFiltroEstado] = useState('');
  const [filtroCodigo, setFiltroCodigo] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [rematching, setRematching] = useState(false);
  const [statusMsg, setStatusMsg] = useState(null); // {tipo: 'ok'|'error', texto: string}
  const [error, setError] = useState(null);
  const [anularPrearmado, setAnularPrearmado] = useState(null);
  const [motivoAnular, setMotivoAnular] = useState('');

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

  useEffect(() => {
    const t = setTimeout(cargar, filtroCodigo ? 300 : 0);
    return () => clearTimeout(t);
  }, [cargar, filtroCodigo]);

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
      await api.patch(`/prearmado/${anularPrearmado.id}`, {
        estado: 'anulado',
        notas: motivoAnular || null,
      });
      cerrarAnular();
      await cargar();
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo anular');
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
        <button
          className={styles.actionBtn}
          onClick={rematchear}
          disabled={rematching || loading}
        >
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
                    <tr key={p.id}>
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
                          <Check
                            size={14}
                            className={styles.completoIcon}
                            aria-label="Completo"
                          />
                        )}
                      </td>
                      <td>
                        {p.incluye_windows ? (
                          <span className={styles.windowsBadge}>
                            {WINDOWS_LABEL[p.incluye_windows]}
                          </span>
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
                          {p.created_at ? new Date(p.created_at).toLocaleString('es-AR') : ''}
                        </span>
                      </td>
                      <td>
                        <div className={styles.acciones}>
                          {proximos.map((next) => (
                            <button
                              key={next}
                              className={styles.iconBtn}
                              onClick={() => cambiarEstado(p, next)}
                              title={`Pasar a ${ESTADO_LABEL[next]}`}
                              disabled={terminal}
                            >
                              {ESTADO_LABEL[next]}
                            </button>
                          ))}
                          {!terminal && (
                            <button
                              className={styles.iconBtn}
                              onClick={() => onClickAnular(p)}
                              title="Anular"
                            >
                              <Ban size={14} />
                            </button>
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
        <PrearmadoForm onClose={() => setShowForm(false)} onSaved={cargar} />
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
                Vas a anular el prearmado <strong>{anularPrearmado.codigo}</strong>
                {' '}({anularPrearmado.combo_item_code}). Esta acción es terminal — no se puede revertir.
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
    </div>
  );
}
