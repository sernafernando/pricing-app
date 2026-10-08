import { useState } from 'react';
import MarkupCell from '../MarkupCell';
import { costLabel, readVariation } from '../variationRows';
import { describeVariationsError, useVariations } from '../useVariations';
import cellStyles from '../cells.module.css';
import { amount } from './format';
import { Field, Fields, Section } from './PanelParts';
import styles from './panel.module.css';

const count = (value) => (value == null ? null : String(value));

function VariationCard({ variation, canSeeMargin }) {
  return (
    <li className={styles.card} data-negative={variation.negative ? '' : undefined}>
      <div className={styles.cardHead}>
        <span className={styles.cardTitle}>Variación {variation.id}</span>
        {variation.attributes.length > 0 && <span className={styles.note}>{variation.attributes.join(' · ')}</span>}
        {variation.sku && <span className={cellStyles.code}>SKU {variation.sku}</span>}
        {variation.linked ? (
          <span className={styles.productName}>{variation.productName ?? '—'}</span>
        ) : (
          <span className={cellStyles.empty}>Sin producto vinculado</span>
        )}
        {variation.inherited && <span className={cellStyles.note}>producto de la publicación</span>}
      </div>
      <Fields>
        <Field label="Disponible">{count(variation.available)}</Field>
        <Field label="Vendidas">{count(variation.sold)}</Field>
        {canSeeMargin && <Field label={costLabel(variation.costCurrency)}>{amount(variation.cost)}</Field>}
        {canSeeMargin && (
          <Field label="Markup">
            <MarkupCell markup={variation.markup} />
          </Field>
        )}
      </Fields>
    </li>
  );
}

/**
 * Variaciones: one card per variation, from the same endpoint as the table's
 * sub-rows (P6c). Mounted only while this tab is open, so a publication's
 * variations cost a request only when somebody looks at them.
 */
export default function VariacionesTab({ itemId, canSeeMargin }) {
  const [attempt, setAttempt] = useState(0);
  const { status, variations, error } = useVariations(itemId, attempt);

  if (status === 'loading') {
    return (
      <p className={styles.note} role="status">
        Cargando variaciones…
      </p>
    );
  }
  if (status === 'error') {
    return (
      <div className={styles.error} role="alert">
        <span>{describeVariationsError(error)}</span>
        <button type="button" className="btn-tesla outline sm" onClick={() => setAttempt((n) => n + 1)}>
          Reintentar
        </button>
      </div>
    );
  }
  if (variations.length === 0) return <p className={styles.note}>Esta publicación no tiene variaciones</p>;
  return (
    <Section title="Variaciones">
      <ul className={styles.cards}>
        {variations.map((raw) => {
          const variation = readVariation(raw, { canSeeMargin });
          return <VariationCard key={variation.id} variation={variation} canSeeMargin={canSeeMargin} />;
        })}
      </ul>
    </Section>
  );
}
