import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import styles from './ParaGanarScopeFilters.module.css';

export default function ScopeMultiSelect({
  label,
  options,
  selected,
  onChange,
  getKey,
  getLabel,
  emptyHint,
  disabled,
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const toggle = (key) => {
    if (selected.includes(key)) {
      onChange(selected.filter((item) => item !== key));
    } else {
      onChange([...selected, key]);
    }
  };

  const count = selected.length;
  const buttonLabel = count > 0 ? `${label} (${count})` : label;

  return (
    <div className={styles.selectWrap} ref={rootRef}>
      <button
        type="button"
        className={`${styles.selectBtn} ${count > 0 ? styles.selectBtnActive : ''}`}
        aria-expanded={open}
        aria-controls={listId}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        <span>{buttonLabel}</span>
        <ChevronDown size={14} aria-hidden />
      </button>
      {open && (
        <div className={styles.dropdown} id={listId} role="listbox" aria-label={label}>
          {options.length === 0 ? (
            <p className={styles.emptyHint}>{emptyHint}</p>
          ) : (
            <ul className={styles.optionList}>
              {options.map((option) => {
                const key = getKey(option);
                const checked = selected.includes(key);
                return (
                  <li key={String(key)}>
                    <label className={`${styles.option} ${checked ? styles.optionSelected : ''}`}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(key)}
                      />
                      <span>{getLabel(option)}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          {count > 0 && (
            <button
              type="button"
              className={styles.clearLocal}
              onClick={() => onChange([])}
            >
              Limpiar {label.toLowerCase()}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
