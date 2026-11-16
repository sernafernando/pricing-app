import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Ban, ChevronDown } from 'lucide-react';
import { usePermisos } from '../../contexts/PermisosContext';
import { promocionesAPI, publicacionesMlAPI } from '../../services/api';
import ModalTesla from '../ModalTesla';
import { resolverParams } from './bulkParams';
import { BATCH_SIZE } from './BulkStatusActions';
import styles from './BulkActions.module.css';
import buttonStyles from './toolbarButton.module.css';

const REGION = 'Excluir o incluir en hay mejores';
const ACTIONS = [
  {
    excluido: true,
    name: 'Excluir de hay mejores',
    verb: 'excluir de hay mejores',
    done: 'excluidas de hay mejores',
    already: 'ya estaban excluidas',
  },
  {
    excluido: false,
    name: 'Incluir en hay mejores',
    verb: 'volver a incluir en hay mejores',
    done: 'incluidas en hay mejores',
    already: 'ya participaban',
  },
];

const plural = (n, one, many) => (n === 1 ? one : many);

function scopeOf(checked) {
  const itemIds = checked?.itemIds ?? [];
  const productIds = checked?.productIds ?? [];
  const rows = itemIds.length + productIds.length;
  if (rows === 0) return { checked: false, where: { one: 'del filtro', many: 'del filtro' }, suffix: 'las del filtro' };
  const suffix =
    productIds.length > 0
      ? `las de ${rows} ${plural(rows, 'fila marcada', 'filas marcadas')}`
      : plural(rows, 'la marcada', `las ${rows} marcadas`);
  return { checked: true, where: { one: 'marcada', many: 'marcadas' }, suffix, itemIds, productIds };
}

function describeResolveError(error, scope) {
  const message = error?.response?.data?.error?.message;
  if (error?.response?.status === 422 && message) return message;
  if (error?.response?.status === 503)
    return scope.checked
      ? 'La consulta tardó demasiado: marcá menos filas o reintentá.'
      : 'La consulta tardó demasiado: acotá los filtros o reintentá.';
  return scope.checked
    ? 'No se pudieron resolver las publicaciones marcadas.'
    : 'No se pudieron resolver las publicaciones del filtro.';
}

/**
 * Bulk exclude / re-include publications from the hay_mejores process (`promos.escribir`).
 * Same scope as Pausar/activar: checked rows, else the current filter.
 *
 * `variant="menuItems"`: portals menuitems into `menuSlot` and keeps the confirm modal mounted here
 * (so closing Acciones masivas does not abort the run). Default keeps a standalone toolbar button.
 */
export default function BulkHayMejoresExclusion({
  filters,
  canSeeMargin,
  onDone,
  checked,
  variant = 'button',
  onChose,
  menuSlot = null,
}) {
  const { tienePermiso } = usePermisos();
  const [open, setOpen] = useState(false);
  const [run, setRun] = useState(null);
  const containerRef = useRef(null);
  const attempt = useRef(0);
  const menuOnly = variant === 'menuItems';

  useEffect(() => {
    if (!open || menuOnly) return undefined;
    const closeOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', closeOutside);
    return () => document.removeEventListener('mousedown', closeOutside);
  }, [open, menuOnly]);

  if (!tienePermiso('promos.escribir')) return null;

  const scope = scopeOf(checked);
  const resolve = (excluido) =>
    scope.checked
      ? publicacionesMlAPI.hayMejoresExclusionItemIdsChecked({
          excluido,
          item_ids: scope.itemIds,
          producto_ids: scope.productIds,
        })
      : publicacionesMlAPI.hayMejoresExclusionItemIds({
          ...resolverParams(filters, canSeeMargin),
          excluido,
        });

  const choose = async (choice) => {
    const mine = ++attempt.current;
    const action = { ...choice, label: `${choice.name} ${scope.suffix}`, where: scope.where };
    setOpen(false);
    onChose?.();
    setRun({ action, phase: 'resolving' });
    try {
      const { data } = await resolve(action.excluido);
      if (mine === attempt.current)
        setRun({ action, phase: 'confirming', itemIds: data.item_ids, noAplican: data.no_aplican });
    } catch (error) {
      if (mine === attempt.current) setRun({ action, phase: 'refused', error: describeResolveError(error, scope) });
    }
  };

  const confirm = async () => {
    const { action, itemIds } = run;
    let done = 0;
    let stopped = false;
    setRun({ ...run, phase: 'sending', done: 0 });
    for (let start = 0; start < itemIds.length; start += BATCH_SIZE) {
      try {
        const { data } = await promocionesAPI.setHayMejoresExclusionBulk({
          excluido: action.excluido,
          item_ids: itemIds.slice(start, start + BATCH_SIZE),
        });
        done += data.count;
        setRun((current) => ({ ...current, done }));
      } catch {
        stopped = true;
        break;
      }
    }
    setRun((current) => ({ ...current, phase: 'done', done, stopped, total: itemIds.length }));
    if (done > 0) onDone?.();
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

  const total = run?.itemIds?.length ?? run?.total ?? 0;
  const menuItems = ACTIONS.map((action) => (
    <button
      key={String(action.excluido)}
      type="button"
      role="menuitem"
      className={styles.item}
      onClick={() => choose(action)}
    >
      {`${action.name} ${scope.suffix}`}
    </button>
  ));
  const modal = run && (
    <ModalTesla
      isOpen
      onClose={close}
      title={run.action.label}
      size="sm"
      closeOnOverlay={false}
      closeOnEsc={run.phase !== 'sending'}
      showCloseButton={run.phase !== 'sending'}
    >
      <section aria-label={REGION} className={styles.statusBody}>
        {run.phase === 'resolving' && <p>{`Calculando las publicaciones ${run.action.where.many}…`}</p>}
        {run.phase === 'refused' && <p role="alert">{run.error}</p>}
        {run.phase === 'confirming' && total === 0 && (
          <p>{`Ninguna publicación ${run.action.where.one} se puede ${run.action.verb}.`}</p>
        )}
        {run.phase === 'confirming' && total > 0 && (
          <p>{`Se van a ${run.action.verb} ${total} ${plural(total, 'publicación', 'publicaciones')}.`}</p>
        )}
        {run.phase === 'confirming' && run.noAplican > 0 && (
          <p className={styles.note}>
            {`${run.noAplican} ${plural(
              run.noAplican,
              `publicación ${run.action.where.one} no se toca`,
              `publicaciones ${run.action.where.many} no se tocan`,
            )} (ya están en ese estado).`}
          </p>
        )}
        {run.phase === 'sending' && <p role="status">{`Aplicando ${run.done} de ${total}…`}</p>}
        {run.phase === 'done' && (
          <div className={styles.summary}>
            {run.stopped && (
              <p role="alert">{`Se cortó después de ${run.done} de ${total}. Las que faltan no se enviaron.`}</p>
            )}
            <p>{`${run.done} ${run.action.done}.`}</p>
          </div>
        )}
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
  );

  if (menuOnly) {
    return (
      <>
        {menuSlot ? createPortal(menuItems, menuSlot) : null}
        {modal}
      </>
    );
  }

  return (
    <div className={styles.anchor} ref={containerRef} onKeyDown={closeOnEscape}>
      <button
        type="button"
        className={`btn-tesla sm ${buttonStyles.quiet}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={
          scope.checked
            ? 'Excluye o vuelve a incluir en hay mejores las publicaciones marcadas'
            : 'Excluye o vuelve a incluir en hay mejores todas las publicaciones del filtro'
        }
        onClick={() => setOpen((was) => !was)}
      >
        <Ban size={14} aria-hidden="true" />
        Hay mejores
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className={styles.panel}>
          <div role="menu" aria-label="Excluir o incluir en hay mejores" className={styles.menu}>
            {menuItems}
          </div>
        </div>
      )}
      {modal}
    </div>
  );
}
