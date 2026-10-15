import { useId, useState } from 'react';
import { publicacionesMlAPI } from '../../../services/api';
import styles from './linkActions.module.css';

const SEARCH_MIN = 2; // `GET /buscar-productos-erp` refuses shorter queries
const MANUAL_SOURCES = new Set(['manual', 'manual_none']);

/** What to tell the operator when a link write is refused. */
function describeWriteError(error) {
  const status = error?.response?.status;
  if (status === 409) return 'La vinculación de productos está desactivada.';
  if (status === 403) return 'No tenés permiso para vincular productos.';
  const detail = error?.response?.data?.detail;
  if (status === 422 && typeof detail === 'string') return detail;
  return 'No se pudo guardar el vínculo.';
}

const productLine = (product) => [product.codigo, product.descripcion].filter(Boolean).join(' · ') || `Producto ${product.item_id}`;

function ProductOptions({ title, products, selectedId, onSelect }) {
  const titleId = useId();
  return (
    <div>
      <p id={titleId} className={styles.listTitle}>
        {title}
      </p>
      <ul className={styles.options} aria-labelledby={titleId}>
        {products.map((product) => (
          <li key={product.item_id}>
            <button type="button" className={styles.option} aria-pressed={product.item_id === selectedId} onClick={() => onSelect(product.item_id)}>
              <span>{productLine(product)}</span>
              {product.marca && <span className={styles.optionMeta}>{product.marca}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function NoteField({ value, onChange }) {
  const id = useId();
  return (
    <div className={styles.field}>
      <label htmlFor={id}>Nota (opcional)</label>
      <input id={id} className={styles.input} value={value} maxLength={500} onChange={(event) => onChange(event.target.value)} />
    </div>
  );
}

/** Search an ERP product (or pick a conflict candidate) to link the unit to. */
function LinkForm({ candidates, busy, onSave, onCancel }) {
  const searchId = useId();
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState({ status: 'idle', results: [] });
  const [selected, setSelected] = useState(null);
  const [note, setNote] = useState('');
  const canSearch = query.trim().length >= SEARCH_MIN && search.status !== 'loading';

  const runSearch = async (event) => {
    event?.preventDefault();
    if (!canSearch) return;
    // The results are being replaced: a pick among the old ones leaves the view,
    // so it must not be what "Guardar" saves. A conflict candidate stays in view.
    setSelected((current) => (candidates.some((candidate) => candidate.item_id === current) ? current : null));
    setSearch({ status: 'loading', results: [] });
    try {
      const response = await publicacionesMlAPI.searchProducts(query.trim());
      setSearch({ status: 'ready', results: Array.isArray(response?.data) ? response.data : [] });
    } catch {
      setSearch({ status: 'error', results: [] });
    }
  };

  return (
    <div className={styles.editor}>
      {candidates.length > 0 && <ProductOptions title="Candidatos" products={candidates} selectedId={selected} onSelect={setSelected} />}
      <div className={styles.field}>
        <label htmlFor={searchId}>Buscar producto</label>
        <div className={styles.searchRow}>
          <input
            id={searchId}
            className={styles.input}
            value={query}
            placeholder="Código o descripción"
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && runSearch(event)}
          />
          <button type="button" className="btn-tesla outline sm" onClick={runSearch} disabled={!canSearch}>
            Buscar
          </button>
        </div>
      </div>
      {search.status === 'loading' && <p className={styles.hint}>Buscando…</p>}
      {search.status === 'error' && <p className={styles.error}>No se pudo buscar productos.</p>}
      {search.status === 'ready' && search.results.length === 0 && <p className={styles.hint}>No se encontraron productos.</p>}
      {search.results.length > 0 && <ProductOptions title="Resultados" products={search.results} selectedId={selected} onSelect={setSelected} />}
      <NoteField value={note} onChange={setNote} />
      <div className={styles.actions}>
        <button type="button" className="btn-tesla sm" disabled={selected == null || busy} onClick={() => onSave(selected, note)}>
          Guardar
        </button>
        <button type="button" className="btn-tesla outline sm" onClick={onCancel} disabled={busy}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

function NoneForm({ busy, onConfirm, onCancel }) {
  const [note, setNote] = useState('');
  return (
    <div className={styles.editor}>
      <p className={styles.hint}>La unidad queda marcada sin producto hasta que se vincule o vuelva a automático.</p>
      <NoteField value={note} onChange={setNote} />
      <div className={styles.actions}>
        <button type="button" className="btn-tesla danger sm" disabled={busy} onClick={() => onConfirm(note)}>
          Confirmar
        </button>
        <button type="button" className="btn-tesla outline sm" onClick={onCancel} disabled={busy}>
          Cancelar
        </button>
      </div>
    </div>
  );
}

const noteOrNull = (note) => (note.trim() === '' ? null : note.trim());

/**
 * The manual backup of one unit's link (`ml_publicaciones.vincular`): link it
 * to a product by hand, mark it as having no product, or hand it back to the
 * automatic rule (only when the link is manual). A refused write says why and
 * leaves everything as it was; a done one calls `onWritten`.
 *
 * @param {object} props
 * @param {string} props.itemId
 * @param {number} props.variationId 0 is the item-level unit.
 * @param {string|null} props.source The link's source (`sku_auto`, `manual`, `manual_none`), null without a link row.
 * @param {Array} props.candidates The conflict candidates (`{ item_id, codigo, descripcion }`), offered first.
 * @param {() => void} props.onWritten
 */
export default function LinkActions({ itemId, variationId, source, candidates = [], onWritten }) {
  const [mode, setMode] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const run = async (write) => {
    setBusy(true);
    setError(null);
    try {
      await write();
      setMode(null);
      onWritten();
    } catch (failure) {
      setError(describeWriteError(failure));
    } finally {
      setBusy(false);
    }
  };

  const open = (next) => {
    setError(null);
    setMode(next);
  };

  return (
    <>
      {mode == null && (
        <div className={styles.actions}>
          <button type="button" className="btn-tesla outline sm" onClick={() => open('link')}>
            Vincular producto
          </button>
          <button type="button" className="btn-tesla outline sm" onClick={() => open('none')}>
            Marcar sin producto
          </button>
          {MANUAL_SOURCES.has(source) && (
            <button
              type="button"
              className="btn-tesla outline sm"
              disabled={busy}
              onClick={() => run(() => publicacionesMlAPI.revertProductLinkAuto(itemId, variationId))}
            >
              Volver a automático
            </button>
          )}
        </div>
      )}
      {mode === 'link' && (
        <LinkForm
          candidates={candidates}
          busy={busy}
          onCancel={() => open(null)}
          onSave={(productId, note) => run(() => publicacionesMlAPI.setProductLink(itemId, variationId, { producto_item_id: productId, note: noteOrNull(note) }))}
        />
      )}
      {mode === 'none' && (
        <NoneForm
          busy={busy}
          onCancel={() => open(null)}
          onConfirm={(note) => run(() => publicacionesMlAPI.setProductLinkNone(itemId, variationId, { note: noteOrNull(note) }))}
        />
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </>
  );
}
