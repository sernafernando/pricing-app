import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, X } from 'lucide-react';
import styles from './ParaGanarScopeFilters.module.css';

function sameKey(a, b) {
  return String(a) === String(b);
}

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
    if (selected.some((item) => sameKey(item, key))) {
      onChange(selected.filter((item) => !sameKey(item, key)));
    } else {
      onChange([...selected, key]);
    }
  };

  const clear = () => {
    onChange([]);
    setOpen(false);
  };

  const count = selected.length;
  const buttonLabel = count > 0 ? `${label} (${count})` : label;

  return (
    <div className={styles.selectWrap} ref={rootRef}>
      <div className={`${styles.selectGroup} ${count > 0 ? styles.selectGroupActive : ''}`}>
        <button
          type="button"
          className={styles.selectBtn}
          aria-expanded={open}
          aria-controls={listId}
          disabled={disabled}
          onClick={() => setOpen((value) => !value)}
        >
          <span>{buttonLabel}</span>
          <ChevronDown size={14} aria-hidden />
        </button>
        {count > 0 && (
          <button
            type="button"
            className={styles.clearChip}
            aria-label={`Limpiar ${label.toLowerCase()}`}
            disabled={disabled}
            onClick={clear}
          >
            <X size={12} aria-hidden />
          </button>
        )}
      </div>
      {open && (
        <div className={styles.dropdown} id={listId} aria-label={label}>
          <div className={styles.dropdownBody} role="listbox">
            {options.length === 0 ? (
              <p className={styles.emptyHint}>{emptyHint}</p>
            ) : (
              <ul className={styles.optionList}>
                {options.map((option) => {
                  const key = getKey(option);
                  const checked = selected.some((item) => sameKey(item, key));
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
          </div>
          {count > 0 && (
            <button type="button" className={styles.clearLocal} onClick={clear}>
              Limpiar {label.toLowerCase()}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
