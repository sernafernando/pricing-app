import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Power } from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import { publicacionesMlAPI } from '../../services/api';
import ModalTesla from '../ModalTesla';
import { resolverParams } from './bulkParams';
import styles from './BulkActions.module.css';

// The most publications one write request carries; the backend refuses more (`BULK_BATCH_SIZE`).
export const BATCH_SIZE = 20;

const REGION = 'Pausar o activar publicaciones';
const ACTIONS = [
  { target: 'paused', label: 'Pausar las del filtro', verb: 'pausar', done: 'pausadas', already: 'ya estaban pausadas' },
  { target: 'active', label: 'Activar las del filtro', verb: 'activar', done: 'activadas', already: 'ya estaban activas' },
];

const plural = (n, one, many) => (n === 1 ? one : many);

/** The operator-facing reason the set could not be resolved (the server's own message for a 422 over the cap). */
function describeResolveError(error) {
  const message = error?.response?.data?.error?.message;
  if (error?.response?.status === 422 && message) return message;
  if (error?.response?.status === 503) return 'La consulta tardó demasiado: acotá los filtros o reintentá.';
  return 'No se pudieron resolver las publicaciones del filtro.';
}

function Summary({ action, results, total, stopped }) {
  const by = (status) => results.filter((result) => result.status === status);
  const done = by('submitted').length;
  const unchanged = by('unchanged').length;
  const ambiguous = by('ambiguous').length;
  const failed = results.filter((result) => !['submitted', 'unchanged', 'ambiguous'].includes(result.status));
  return (
    <div className={styles.summary}>
      {stopped && <p role="alert">{`Se cortó después de ${results.length} de ${total}. Las que faltan no se enviaron.`}</p>}
      <p>{`${done} ${action.done}.`}</p>
      {unchanged > 0 && <p>{`${unchanged} ${action.already}.`}</p>}
      {ambiguous > 0 && <p>{`${ambiguous} sin confirmar: se vuelven a consultar.`}</p>}
      {failed.length > 0 && (
        <>
          <p>{`${failed.length} con error:`}</p>
          <ul className={styles.failures}>
            {failed.map((result) => (
              <li key={result.item_id}>{`${result.item_id}: ${result.message ?? 'sin detalle'}`}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/**
 * Bulk "Pausar" / "Activar" over Publicaciones ML, behind `ml_publicaciones.pausar`: the set is every publication
 * the filters show that can take the status, resolved when the action is chosen
 * (`GET /ml-publications/view/status-item-ids`), so the confirmation says how many. Confirmed, it is written in
 * batches of `BATCH_SIZE` (each publication checked again by the server), with progress, then a summary.
 *
 * Confirmar sends the set the confirmation showed, even if the filters changed meanwhile: the operator approved
 * that set, not the new one (the server still checks each publication).
 *
 * Fail closed: no set while resolving, when the resolver refuses (over its cap) or fails, or when it is empty --
 * nothing to confirm. A failed batch stops the run; what was written is still re-read (`onDone`).
 */
export default function BulkStatusActions({ filters, canSeeMargin, onDone }) {
  const { tienePermiso } = usePermisos();
  const [open, setOpen] = useState(false);
  const [run, setRun] = useState(null);
  const containerRef = useRef(null);
  // Which choice is current: an answer for a choice the operator already closed (or replaced) never reopens it.
  const attempt = useRef(0);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', closeOutside);
    return () => document.removeEventListener('mousedown', closeOutside);
  }, [open]);

  if (!tienePermiso('ml_publicaciones.pausar')) return null;

  const choose = async (action) => {
    const mine = ++attempt.current;
    setOpen(false);
    setRun({ action, phase: 'resolving' });
    try {
      const { data } = await publicacionesMlAPI.statusItemIds({ ...resolverParams(filters, canSeeMargin), target: action.target });
      if (mine === attempt.current) setRun({ action, phase: 'confirming', itemIds: data.item_ids, noAplican: data.no_aplican });
    } catch (error) {
      if (mine === attempt.current) setRun({ action, phase: 'refused', error: describeResolveError(error) });
    }
  };

  const confirm = async () => {
    const { action, itemIds } = run;
    const results = [];
    let stopped = false;
    setRun({ ...run, phase: 'sending', results: [] }); // `results` above only accumulates; state gets copies
    for (let start = 0; start < itemIds.length; start += BATCH_SIZE) {
      try {
        const { data } = await publicacionesMlAPI.statusBulk({ status: action.target, item_ids: itemIds.slice(start, start + BATCH_SIZE) });
        results.push(...data.results);
        setRun((current) => ({ ...current, results: [...results] }));
      } catch {
        stopped = true;
        break;
      }
    }
    setRun((current) => ({ ...current, phase: 'done', results: [...results], stopped }));
    if (results.length > 0) onDone?.();
  };

  const close = () => {
    if (run?.phase === 'sending') return;
    attempt.current += 1;
    setRun(null);
  };

  const closeOnEscape = (event) => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  };

  const total = run?.itemIds?.length ?? 0;
  return (
    <div className={styles.anchor} ref={containerRef} onKeyDown={closeOnEscape}>
      <button
        type="button"
        className="btn-tesla outline-subtle-primary sm"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Pausa o activa en Mercado Libre todas las publicaciones del filtro que pueden cambiar"
        onClick={() => setOpen((was) => !was)}
      >
        <Power size={14} aria-hidden="true" />
        Pausar / activar
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className={styles.panel}>
          <div role="menu" aria-label="Pausar o activar" className={styles.menu}>
            {ACTIONS.map((action) => (
              <button key={action.target} type="button" role="menuitem" className={styles.item} onClick={() => choose(action)}>
                {action.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {run && (
        <ModalTesla isOpen onClose={close} title={run.action.label} size="sm" closeOnOverlay={false} closeOnEsc={run.phase !== 'sending'} showCloseButton={run.phase !== 'sending'}>
          <section aria-label={REGION} className={styles.statusBody}>
            {run.phase === 'resolving' && <p>Calculando las publicaciones del filtro…</p>}
            {run.phase === 'refused' && <p role="alert">{run.error}</p>}
            {run.phase === 'confirming' && total === 0 && <p>{`Ninguna publicación del filtro se puede ${run.action.verb}.`}</p>}
            {run.phase === 'confirming' && total > 0 && (
              <p>{`Se van a ${run.action.verb} ${total} ${plural(total, 'publicación', 'publicaciones')} en Mercado Libre.`}</p>
            )}
            {run.phase === 'confirming' && run.noAplican > 0 && (
              <p className={styles.note}>
                {`${run.noAplican} ${plural(run.noAplican, 'publicación del filtro no se toca', 'publicaciones del filtro no se tocan')} (otro estado).`}
              </p>
            )}
            {run.phase === 'sending' && <p role="status">{`Enviando ${run.results.length} de ${total}…`}</p>}
            {run.phase === 'done' && <Summary action={run.action} results={run.results} total={total} stopped={run.stopped} />}
            <div className={styles.statusButtons}>
              {run.phase === 'confirming' && total > 0 && (
                <button type="button" className="btn-tesla primary sm" onClick={confirm}>
                  Confirmar
                </button>
              )}
              {run.phase !== 'sending' && (
                <button type="button" className="btn-tesla ghost sm" onClick={close}>
                  {run.phase === 'done' ? 'Cerrar' : 'Cancelar'}
                </button>
              )}
            </div>
          </section>
        </ModalTesla>
      )}
    </div>
  );
}
