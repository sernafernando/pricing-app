import { useCallback, useEffect, useState } from 'react';
import { X, ChevronDown, Loader2, Plus, BookOpen } from 'lucide-react';
import api from '../../services/api';
import useCheques from '../../hooks/useCheques';
import FormChequera from './_shared/FormChequera';
import EmptyState from './_shared/EmptyState';
import styles from './ModalChequeras.module.css';

/**
 * ModalChequeras — administración de chequeras (talonarios) por banco propio.
 *
 * Hoy el backend expone GET y POST de chequeras, y nada más: no hay endpoint
 * para editar ni desactivar. Por eso esta pantalla es "listar + crear" y no
 * ofrece acciones por fila — mostrar un botón que no puede funcionar sería
 * peor que no mostrarlo.
 *
 * RULE: NO cierra con click en overlay (AGENTS.md: solo X o Cerrar).
 *
 * Props:
 *   onClose    () => void
 *   empresaId  (number|null) — pre-selecciona la empresa; si falta se elige acá.
 */
/** Tope del endpoint de chequeras (`Query(50, ge=1, le=200)`). */
const PAGE_SIZE_MAX = 200;

const formatRango = (c) => {
  if (c.numero_desde == null || c.numero_hasta == null) return 'Sin rango';
  return `${String(c.numero_desde).padStart(8, '0')}–${String(c.numero_hasta).padStart(8, '0')}`;
};

export default function ModalChequeras({ onClose, empresaId = null }) {
  const { listarChequeras } = useCheques();

  const [empresas, setEmpresas] = useState([]);
  const [empresaSel, setEmpresaSel] = useState(empresaId ? String(empresaId) : '');
  const [bancos, setBancos] = useState([]);
  const [loadingBancos, setLoadingBancos] = useState(false);
  const [bancoSel, setBancoSel] = useState('');

  const [chequeras, setChequeras] = useState([]);
  // La tabla no pagina: si el banco tiene más chequeras que el page_size hay que
  // decirlo, no esconderlas.
  const [totalChequeras, setTotalChequeras] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [mostrarForm, setMostrarForm] = useState(false);

  // Empresas (solo cuando no vino fijada por el caller).
  useEffect(() => {
    if (empresaId) return;
    api
      .get('/admin/empresas')
      .then(({ data }) => setEmpresas(Array.isArray(data) ? data : data?.empresas ?? []))
      .catch(() => setEmpresas([]));
  }, [empresaId]);

  // Bancos de la empresa elegida.
  useEffect(() => {
    setBancoSel('');
    setBancos([]);
    if (!empresaSel) return;
    setLoadingBancos(true);
    api
      .get(`/administracion/bancos?solo_activos=true&empresa_id=${empresaSel}`)
      .then(({ data }) =>
        setBancos(Array.isArray(data?.bancos) ? data.bancos : Array.isArray(data) ? data : []),
      )
      .catch(() => setBancos([]))
      .finally(() => setLoadingBancos(false));
  }, [empresaSel]);

  const fetchChequeras = useCallback(async () => {
    if (!bancoSel) {
      setChequeras([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // 200 es el tope exacto del endpoint (`page_size: Query(50, ge=1, le=200)`);
      // pedir más devuelve 422.
      const result = await listarChequeras({
        banco_empresa_id: Number(bancoSel),
        page_size: PAGE_SIZE_MAX,
      });
      const items = result?.items ?? (Array.isArray(result) ? result : []);
      setChequeras(items);
      setTotalChequeras(Number(result?.total ?? items.length));
    } catch (err) {
      // FastAPI devuelve `detail` como array de objetos en un 422: pasarlo crudo
      // a JSX revienta el modal con "Objects are not valid as a React child".
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Error al cargar las chequeras.');
      setChequeras([]);
      setTotalChequeras(0);
    } finally {
      setLoading(false);
    }
  }, [bancoSel, listarChequeras]);

  // Separados a propósito: el fetch sigue a su propia función memoizada, y el
  // cierre del formulario sigue al banco. Mezclarlos hacía que un cambio de
  // identidad de `listarChequeras` pisara estado de UI.
  useEffect(() => {
    setMostrarForm(false);
  }, [bancoSel]);

  useEffect(() => {
    fetchChequeras();
  }, [fetchChequeras]);

  const handleCreada = () => {
    setMostrarForm(false);
    fetchChequeras();
  };

  return (
    <div className={styles.overlay}>
      <div
        className={styles.container}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-chequeras-title"
      >
        <div className={styles.header}>
          <h2 id="modal-chequeras-title" className={styles.title}>
            Chequeras
          </h2>
          <button type="button" className={styles.closeBtn} onClick={onClose} aria-label="Cerrar">
            <X size={18} />
          </button>
        </div>

        <div className={styles.body}>
          {error && <div className={styles.errorBanner}>{error}</div>}

          <div className={styles.filtros}>
            {!empresaId && (
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel} htmlFor="chequeras-empresa">
                  Empresa
                </label>
                <div className={styles.selectWrapper}>
                  <select
                    id="chequeras-empresa"
                    className={styles.select}
                    value={empresaSel}
                    onChange={(e) => setEmpresaSel(e.target.value)}
                  >
                    <option value="">Seleccioná...</option>
                    {empresas.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.nombre}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={14} className={styles.selectArrow} />
                </div>
              </div>
            )}

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="chequeras-banco">
                Banco
              </label>
              {loadingBancos ? (
                <div className={styles.loadingRow}>
                  <Loader2 size={14} className={styles.spin} />
                </div>
              ) : (
                <div className={styles.selectWrapper}>
                  <select
                    id="chequeras-banco"
                    className={styles.select}
                    value={bancoSel}
                    onChange={(e) => setBancoSel(e.target.value)}
                    disabled={!empresaSel}
                  >
                    <option value="">Seleccioná...</option>
                    {bancos.map((b) => (
                      <option key={b.id} value={b.id}>
                        {b.banco}
                        {b.numero_cuenta ? ` · ${b.numero_cuenta}` : ''}
                      </option>
                    ))}
                  </select>
                  <ChevronDown size={14} className={styles.selectArrow} />
                </div>
              )}
            </div>
          </div>

          {!bancoSel ? (
            <EmptyState
              icon={<BookOpen size={28} strokeWidth={1.5} />}
              title="Elegí un banco para ver sus chequeras."
              tone="default"
            />
          ) : loading ? (
            <div className={styles.loadingRow}>
              <Loader2 size={16} className={styles.spin} /> Cargando chequeras...
            </div>
          ) : (
            <>
              <div className={styles.tableWrapper}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Descripción</th>
                      <th>Instrumento</th>
                      <th>Rango</th>
                      <th className={styles.thRight}>Próximo</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chequeras.length === 0 ? (
                      <tr>
                        <td colSpan={5} className={styles.tdEmpty}>
                          Este banco todavía no tiene chequeras.
                        </td>
                      </tr>
                    ) : (
                      chequeras.map((c) => (
                        <tr key={c.id}>
                          <td>{c.descripcion || `Chequera ${c.id}`}</td>
                          <td>{c.instrumento === 'echeq' ? 'e-cheq' : 'Físico'}</td>
                          <td className={styles.tdMono}>{formatRango(c)}</td>
                          <td className={`${styles.tdRight} ${styles.tdMono}`}>
                            {c.proximo_numero != null
                              ? String(c.proximo_numero).padStart(8, '0')
                              : '—'}
                          </td>
                          <td>
                            <span className={c.activa ? styles.pillActiva : styles.pillInactiva}>
                              {c.activa ? 'Activa' : 'Inactiva'}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {totalChequeras > chequeras.length && (
                <p className={styles.avisoTruncado}>
                  Mostrando {chequeras.length} de {totalChequeras} chequeras de este banco.
                </p>
              )}

              {mostrarForm ? (
                <FormChequera
                  bancoEmpresaId={bancoSel}
                  permitirInstrumento
                  onCreada={handleCreada}
                  onCancel={() => setMostrarForm(false)}
                />
              ) : (
                <button
                  type="button"
                  className={styles.btnNueva}
                  onClick={() => setMostrarForm(true)}
                >
                  <Plus size={14} /> Nueva chequera
                </button>
              )}
            </>
          )}
        </div>

        <div className={styles.footer}>
          <button type="button" className={styles.btnCancel} onClick={onClose}>
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}
