import { useState, useRef, useEffect } from 'react';
import { Copy, Check } from 'lucide-react';
import styles from './SaleDetailPanel.module.css';

/**
 * Icon button that copies `value` to the clipboard and says so ("Copiado")
 * for a moment. A missing clipboard (insecure context, old browser) must not
 * break the panel: the click is simply a no-op.
 */
export default function CopyButton({ value, label }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  async function handleClick() {
    try {
      await navigator.clipboard.writeText(String(value));
    } catch {
      return;
    }
    setCopied(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 1500);
  }

  return (
    <>
      <button type="button" className={styles.copyButton} onClick={handleClick} aria-label={label}>
        {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
      </button>
      {copied && (
        <span className={styles.copiedNote} role="status">
          Copiado
        </span>
      )}
    </>
  );
}
