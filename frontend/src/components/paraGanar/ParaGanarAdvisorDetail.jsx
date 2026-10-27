import { formatPrice } from './formatPrice';
import styles from '../../pages/ParaGanarAdvisor.module.css';

export default function ParaGanarAdvisorDetail({ selected }) {
  return (
    <aside className={styles.detail} aria-label="Detalle de sugerencia">
      <div className={styles.panelTitle}>Detalle</div>
      {!selected && (
        <div className={styles.emptyState}>
          <p className={styles.emptyTitle}>Seleccioná un MLA</p>
          <p className={styles.emptyBody}>
            Catálogo, referente, markup y promoción sugerida van a aparecer acá.
            Por ahora solo mostramos los datos base de la publicación.
          </p>
        </div>
      )}
      {selected && (
        <dl className={styles.detailList}>
          <div>
            <dt>MLA</dt>
            <dd>{selected.mla}</dd>
          </div>
          <div>
            <dt>Código</dt>
            <dd>{selected.codigo || '—'}</dd>
          </div>
          <div>
            <dt>Item ERP</dt>
            <dd>{selected.item_id}</dd>
          </div>
          <div>
            <dt>Título ML</dt>
            <dd>{selected.titulo || '—'}</dd>
          </div>
          <div>
            <dt>Descripción ERP</dt>
            <dd>{selected.producto_descripcion || '—'}</dd>
          </div>
          <div>
            <dt>Lista / tipo</dt>
            <dd>{selected.lista_nombre || '—'}</dd>
          </div>
          <div>
            <dt>Precio lista</dt>
            <dd>$ {formatPrice(selected.precio)}</dd>
          </div>
          <div>
            <dt>Catálogo</dt>
            <dd>
              {selected.catalog_listing
                ? `Sí (${selected.catalog_product_id || 'sin id'})`
                : 'No'}
            </dd>
          </div>
          <div>
            <dt>Par sync</dt>
            <dd>{selected.sync_partner_mla || '—'}</dd>
          </div>
          <div>
            <dt>Estado sugerencia</dt>
            <dd>{selected.suggestion_status}</dd>
          </div>
        </dl>
      )}
    </aside>
  );
}
