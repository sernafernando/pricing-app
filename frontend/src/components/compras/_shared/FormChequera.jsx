import { useId, useState } from 'react';
import { ChevronDown, Loader2, Plus } from 'lucide-react';
import useCheques from '../../../hooks/useCheques';
import styles from './FormChequera.module.css';

/**
 * FormChequera — alta de una chequera (talonario) para un banco propio.
 *
 * Es el único formulario de alta: lo comparten el ABM (ModalChequeras) y el
 * atajo "+ Nueva" del modal de emisión de cheques, así la validación y el
 * payload no se duplican.
 *
 * Sobre el rango de numeración: el backend inicializa `proximo_numero` en
 * `numero_desde`, y de ahí sale el autocompletado del número al emitir. Sin
 * rango la chequera es válida igual, pero el número hay que tipearlo a mano
 * cada vez — por eso el hint, y por eso se valida que el rango sea coherente.
 *
 * Props:
 *   bancoEmpresaId    (number|string) — banco propio dueño del talonario. Requerido.
 *   instrumento       ("fisico"|"echeq") — valor inicial. Default "fisico".
 *   permitirInstrumento (bool) — muestra el selector de instrumento. Default false
 *                       (el modal de emisión ya sabe cuál está usando).
 *   onCreada          (chequera) => void — chequera recién creada.
 *   onCancel          () => void — opcional; si falta, no se renderiza Cancelar.
 *   disabled          (bool)
 */
export default function FormChequera({
  bancoEmpresaId,
  instrumento: instrumentoInicial = 'fisico',
  permitirInstrumento = false,
  onCreada,
  onCancel,
  disabled = false,
}) {
  const { crearChequera } = useCheques();
  // Componente compartido con dos callers: IDs literales se pisarían el día que
  // se rendericen dos instancias, y los labels dejarían de funcionar en silencio.
  const uid = useId();

  const [descripcion, setDescripcion] = useState('');
  const [instrumento, setInstrumento] = useState(instrumentoInicial);
  const [numeroDesde, setNumeroDesde] = useState('');
  const [numeroHasta, setNumeroHasta] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState(null);

  const validar = () => {
    if (!bancoEmpresaId) return 'Elegí primero el banco de la chequera.';
    const desde = numeroDesde === '' ? null : Number(numeroDesde);
    const hasta = numeroHasta === '' ? null : Number(numeroHasta);
    if (desde !== null && (!Number.isInteger(desde) || desde < 0))
      return 'El número desde debe ser un entero no negativo.';
    if (hasta !== null && (!Number.isInteger(hasta) || hasta < 0))
      return 'El número hasta debe ser un entero no negativo.';
    // Un rango a medias deja la chequera sin tope o sin arranque: el backend lo
    // acepta, pero es un talonario que después nadie sabe leer.
    if ((desde === null) !== (hasta === null))
      return 'Cargá los dos extremos del rango, o ninguno.';
    if (desde !== null && hasta !== null && hasta < desde)
      return 'El número hasta no puede ser menor que el número desde.';
    return null;
  };

  const handleSubmit = async () => {
    const msg = validar();
    if (msg) {
      setError(msg);
      return;
    }
    setError(null);
    setGuardando(true);
    try {
      const chequera = await crearChequera({
        banco_empresa_id: Number(bancoEmpresaId),
        descripcion: descripcion.trim() || null,
        instrumento,
        numero_desde: numeroDesde === '' ? null : Number(numeroDesde),
        numero_hasta: numeroHasta === '' ? null : Number(numeroHasta),
      });
      setDescripcion('');
      setNumeroDesde('');
      setNumeroHasta('');
      onCreada?.(chequera);
    } catch (err) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Error al crear la chequera.');
    } finally {
      setGuardando(false);
    }
  };

  const bloqueado = disabled || guardando;

  // Este bloque puede vivir DENTRO del <form> de emisión de cheques, y sus
  // inputs son controles de ese form: sin esto, Enter dispara la submisión
  // implícita del padre y el usuario termina emitiendo un cheque cuando sólo
  // quería crear el talonario. Acá Enter hace lo que el usuario espera.
  const handleKeyDown = (e) => {
    if (e.key !== 'Enter') return;
    // Sólo los inputs de texto/número: un <button> enfocado responde a Enter con
    // SU acción (si no, Enter sobre Cancelar crearía la chequera), y el <select>
    // usa Enter para confirmar la opción elegida.
    if (e.target.tagName !== 'INPUT') return;
    e.preventDefault();
    e.stopPropagation();
    if (!bloqueado && bancoEmpresaId) handleSubmit();
  };

  return (
    <div className={styles.form} onKeyDown={handleKeyDown}>
      {error && <div className={styles.errorBanner}>{error}</div>}

      <div className={styles.fieldGroup}>
        <label className={styles.fieldLabel} htmlFor={`${uid}-descripcion`}>
          Descripción
        </label>
        <input
          id={`${uid}-descripcion`}
          type="text"
          maxLength={120}
          className={styles.input}
          value={descripcion}
          onChange={(e) => setDescripcion(e.target.value)}
          placeholder="Talonario principal"
          disabled={bloqueado}
        />
      </div>

      {permitirInstrumento && (
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel} htmlFor={`${uid}-instrumento`}>
            Instrumento
          </label>
          <div className={styles.selectWrapper}>
            <select
              id={`${uid}-instrumento`}
              className={styles.select}
              value={instrumento}
              onChange={(e) => setInstrumento(e.target.value)}
              disabled={bloqueado}
            >
              <option value="fisico">Físico</option>
              <option value="echeq">e-cheq</option>
            </select>
            <ChevronDown size={14} className={styles.selectArrow} />
          </div>
        </div>
      )}

      <div className={styles.grid2}>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel} htmlFor={`${uid}-desde`}>
            Número desde
          </label>
          <input
            id={`${uid}-desde`}
            type="number"
            min="0"
            step="1"
            className={styles.inputMono}
            value={numeroDesde}
            onChange={(e) => setNumeroDesde(e.target.value)}
            placeholder="1"
            disabled={bloqueado}
          />
        </div>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel} htmlFor={`${uid}-hasta`}>
            Número hasta
          </label>
          <input
            id={`${uid}-hasta`}
            type="number"
            min="0"
            step="1"
            className={styles.inputMono}
            value={numeroHasta}
            onChange={(e) => setNumeroHasta(e.target.value)}
            placeholder="100"
            disabled={bloqueado}
          />
        </div>
      </div>
      <p className={styles.fieldHint}>
        El rango es opcional. Si lo cargás, el próximo número se autocompleta al emitir cada cheque.
      </p>

      <div className={styles.actions}>
        {onCancel && (
          <button type="button" className={styles.btnCancel} onClick={onCancel} disabled={bloqueado}>
            Cancelar
          </button>
        )}
        <button
          type="button"
          className={styles.btnSubmit}
          onClick={handleSubmit}
          disabled={bloqueado || !bancoEmpresaId}
        >
          {guardando ? <Loader2 size={14} className={styles.spin} /> : <Plus size={14} />}
          Crear chequera
        </button>
      </div>
    </div>
  );
}
