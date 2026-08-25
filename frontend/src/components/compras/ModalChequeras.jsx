import { useCallback, useEffect, useState } from 'react';
import { X, ChevronDown, Loader2, Plus, BookOpen, Pencil, Power, Check } from 'lucide-react';
import api from '../../services/api';
import useCheques from '../../hooks/useCheques';
import FormChequera from './_shared/FormChequera';
import EmptyState from './_shared/EmptyState';
import styles from './ModalChequeras.module.css';

/** Tope del endpoint de chequeras (`Query(50, ge=1, le=200)`). */
const PAGE_SIZE_MAX = 200;

const formatRango = (c) => {
  if (c.numero_desde == null || c.numero_hasta == null) return 'Sin rango';
  return `${String(c.numero_desde).padStart(8, '0')}–${String(c.numero_hasta).padStart(8, '0')}`;
};

/**
 * Una fila de la tabla. En modo edición muestra los campos que el backend deja
 * cambiar: descripción, numero_hasta y proximo_numero. El banco, el instrumento
 * y numero_desde no se editan — definen la identidad del talonario y los cheques
 * emitidos cuelgan de ella (ver `ChequeraUpdate` en el backend).
 */
function FilaChequera({ chequera, onGuardar, onToggleActiva, guardando }) {
  const [editando, setEditando] = useState(false);
  const [descripcion, setDescripcion] = useState(chequera.descripcion ?? '');
  const [numeroHasta, setNumeroHasta] = useState(
    chequera.numero_hasta != null ? String(chequera.numero_hasta) : '',
  );
  const [proximoNumero, setProximoNumero] = useState(
    chequera.proximo_numero != null ? String(chequera.proximo_numero) : '',
  );
  const [errorFila, setErrorFila] = useState(null);

  const cancelar = () => {
    setDescripcion(chequera.descripcion ?? '');
    setNumeroHasta(chequera.numero_hasta != null ? String(chequera.numero_hasta) : '');
    setProximoNumero(chequera.proximo_numero != null ? String(chequera.proximo_numero) : '');
    setErrorFila(null);
    setEditando(false);
  };

  const guardar = async () => {
    // El backend no acepta null en los números: vaciarlos no es "dejarlos como
    // estaban", es una edición que no se puede mandar. Avisarlo en vez de
    // descartarla en silencio y cerrar la fila como si hubiera guardado.
    if (numeroHasta === '' && chequera.numero_hasta != null) {
      setErrorFila('El número hasta no puede quedar vacío.');
      return;
    }
    if (proximoNumero === '' && chequera.proximo_numero != null) {
      setErrorFila('El próximo número no puede quedar vacío.');
      return;
    }
    setErrorFila(null);

    // PATCH parcial de verdad: sólo viaja lo que el usuario cambió. Mandar todo
    // haría que editar la descripción revalidara el rango sin necesidad.
    const payload = {};
    // Cadena vacía, NO null: Pydantic no distingue "no enviado" de "enviado en
    // null", así que un null acá caía en el validador de body vacío y el usuario
    // no podía borrar la descripción nunca. El service traduce '' → NULL.
    if ((chequera.descripcion ?? '') !== descripcion) payload.descripcion = descripcion;
    const hastaNum = numeroHasta === '' ? null : Number(numeroHasta);
    if ((chequera.numero_hasta ?? null) !== hastaNum && hastaNum !== null) {
      payload.numero_hasta = hastaNum;
    }
    const proximoNum = proximoNumero === '' ? null : Number(proximoNumero);
    if ((chequera.proximo_numero ?? null) !== proximoNum && proximoNum !== null) {
      payload.proximo_numero = proximoNum;
    }
    if (Object.keys(payload).length === 0) {
      setEditando(false);
      return;
    }
    const ok = await onGuardar(chequera.id, payload);
    if (ok) setEditando(false);
  };

  if (!editando) {
    return (
      <tr>
        <td>{chequera.descripcion || `Chequera ${chequera.id}`}</td>
        <td>{chequera.instrumento === 'echeq' ? 'e-cheq' : 'Físico'}</td>
        <td className={styles.tdMono}>{formatRango(chequera)}</td>
        <td className={`${styles.tdRight} ${styles.tdMono}`}>
          {chequera.proximo_numero != null
            ? String(chequera.proximo_numero).padStart(8, '0')
            : '—'}
        </td>
        <td>
          <span className={chequera.activa ? styles.pillActiva : styles.pillInactiva}>
            {chequera.activa ? 'Activa' : 'Inactiva'}
          </span>
        </td>
        <td className={styles.tdAcciones}>
          <button
            type="button"
            className={styles.btnFila}
            onClick={() => setEditando(true)}
            disabled={guardando}
            aria-label={`Editar chequera ${chequera.descripcion || chequera.id}`}
          >
            <Pencil size={13} />
          </button>
          <button
            type="button"
            className={styles.btnFila}
            onClick={() => onToggleActiva(chequera)}
            disabled={guardando}
            title={
              chequera.activa
                ? 'Desactivar: deja de admitir cheques nuevos'
                : 'Reactivar'
            }
            aria-label={`${chequera.activa ? 'Desactivar' : 'Reactivar'} chequera ${chequera.descripcion || chequera.id}`}
          >
            <Power size={13} />
          </button>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td>
        <input
          type="text"
          maxLength={120}
          className={styles.inputFila}
          value={descripcion}
          onChange={(e) => setDescripcion(e.target.value)}
          disabled={guardando}
          aria-label="Descripción"
        />
      </td>
      <td>{chequera.instrumento === 'echeq' ? 'e-cheq' : 'Físico'}</td>
      <td className={styles.tdMono}>
        <input
          type="number"
          min="0"
          step="1"
          className={styles.inputFila}
          value={numeroHasta}
          onChange={(e) => setNumeroHasta(e.target.value)}
          disabled={guardando}
          aria-label="Número hasta"
        />
      </td>
      <td className={styles.tdRight}>
        <input
          type="number"
          min="0"
          step="1"
          className={styles.inputFila}
          value={proximoNumero}
          onChange={(e) => setProximoNumero(e.target.value)}
          disabled={guardando}
          aria-label="Próximo número"
        />
      </td>
      <td>
        <span className={chequera.activa ? styles.pillActiva : styles.pillInactiva}>
          {chequera.activa ? 'Activa' : 'Inactiva'}
        </span>
      </td>
      <td className={styles.tdAcciones}>
        {errorFila && <span className={styles.errorFila}>{errorFila}</span>}
        <button
          type="button"
          className={styles.btnFila}
          onClick={guardar}
          disabled={guardando}
          aria-label="Guardar cambios"
        >
          {guardando ? <Loader2 size={13} className={styles.spin} /> : <Check size={13} />}
        </button>
        <button
          type="button"
          className={styles.btnFila}
          onClick={cancelar}
          disabled={guardando}
          aria-label="Cancelar edición"
        >
          <X size={13} />
        </button>
      </td>
    </tr>
  );
}

/**
 * ModalChequeras — administración de chequeras (talonarios) por banco propio.
 *
 * Listar, crear, editar y activar/desactivar talonarios de un banco propio.
 *
 * Lo que NO se edita (y no es un olvido): banco e instrumento definen la
 * identidad del talonario y los cheques emitidos cuelgan de ella; numero_desde
 * tampoco, porque moverlo deja cheques ya emitidos fuera de su propio rango.
 * Ver `ChequeraUpdate` en el backend.
 *
 * Desactivar no borra nada: los cheques emitidos siguen igual, pero la chequera
 * deja de admitir nuevos (`emitir_cheque_propio` la rechaza con 422).
 *
 * RULE: NO cierra con click en overlay (AGENTS.md: solo X o Cerrar).
 *
 * Props:
 *   onClose    () => void
 *   empresaId  (number|null) — pre-selecciona la empresa; si falta se elige acá.
 */
export default function ModalChequeras({ onClose, empresaId = null }) {
  const { listarChequeras, actualizarChequera } = useCheques();

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
  const [guardandoId, setGuardandoId] = useState(null);

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

  /** @returns {Promise<boolean>} true si el PATCH pasó — la fila cierra recién ahí. */
  const handleGuardar = async (chequeraId, payload) => {
    setGuardandoId(chequeraId);
    setError(null);
    try {
      await actualizarChequera(chequeraId, payload);
      await fetchChequeras();
      return true;
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Error al actualizar la chequera.');
      return false;
    } finally {
      setGuardandoId(null);
    }
  };

  const handleToggleActiva = (chequera) =>
    handleGuardar(chequera.id, { activa: !chequera.activa });

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
                      <th className={styles.thRight}>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {chequeras.length === 0 ? (
                      <tr>
                        <td colSpan={6} className={styles.tdEmpty}>
                          Este banco todavía no tiene chequeras.
                        </td>
                      </tr>
                    ) : (
                      chequeras.map((c) => (
                        <FilaChequera
                          key={c.id}
                          chequera={c}
                          onGuardar={handleGuardar}
                          onToggleActiva={handleToggleActiva}
                          guardando={guardandoId === c.id}
                        />
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
