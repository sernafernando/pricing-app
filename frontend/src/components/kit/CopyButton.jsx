import { useState, useRef, useEffect } from 'react';
import { Copy, Check } from 'lucide-react';
import styles from './CopyButton.module.css';

/**
 * Icon button that copies `value` to the clipboard and says so ("Copiado")
 * for a moment. A missing clipboard (insecure context, old browser) must not
 * break the panel: the click is simply a no-op.
 */
export default function CopyButton({ value, label, compact = false }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  async function handleClick(e) {
    // Inside a clickable table row the copy must not also open the panel.
    e.stopPropagation();
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
      <button
        type="button"
        className={compact ? styles.copyButtonCompact : styles.copyButton}
        onClick={handleClick}
        aria-label={label}
        title={copied ? 'Copiado' : label}
      >
        {copied ? <Check size={compact ? 12 : 14} aria-hidden="true" /> : <Copy size={compact ? 12 : 14} aria-hidden="true" />}
      </button>
      {/* `compact` (a table cell) has no room for the word: the icon
          turning into a check, plus the title, says it instead. */}
      {copied && !compact && (
        <span className={styles.copiedNote} role="status">
          Copiado
        </span>
      )}
    </>
  );
}
