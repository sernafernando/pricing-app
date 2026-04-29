/**
 * LoadingBlock — Spinner azul con texto explicativo.
 *
 * @example
 * <LoadingBlock text="Cargando pedidos…" />
 * <LoadingBlock tone="inline" text="Refrescando" />
 */

import { Loader2 } from 'lucide-react';
import styles from './LoadingBlock.module.css';

/**
 * @param {Object} props
 * @param {string} [props.text='Cargando…']
 * @param {'block'|'inline'} [props.tone='block']
 */
export default function LoadingBlock({ text = 'Cargando…', tone = 'block' }) {
  const toneClass = tone === 'inline' ? styles.inline : styles.block;
  const iconSize = tone === 'inline' ? 16 : 28;

  return (
    <div className={`${styles.container} ${toneClass}`}>
      <Loader2 size={iconSize} className={styles.spin} strokeWidth={1.8} />
      {text && <span className={styles.text}>{text}</span>}
    </div>
  );
}
