/**
 * SearchInput — Reusable search input with icon, clear button, optional debounce,
 * and optional JSON parsing for scanner/barcode inputs.
 *
 * Usage:
 *   <SearchInput value={search} onChange={setSearch} placeholder="Buscar..." />
 *   <SearchInput value={search} onChange={setSearch} debounce={400} />
 *   <SearchInput value={search} onChange={setSearch} parseJson />
 */

import { useState, useEffect, useRef, useCallback, forwardRef } from 'react';
import { Search, X } from 'lucide-react';
import styles from './SearchInput.module.css';

const ICON_SIZES = { sm: 14, md: 16, lg: 18 };

const SearchInput = forwardRef(function SearchInput(
  {
    value,
    onChange,
    placeholder = 'Buscar...',
    debounce = 0,
    onClear,
    parseJson = false,
    autoFocus = false,
    className,
    inputClassName,
    size = 'md',
    disabled = false,
    icon,
  },
  ref,
) {
  // Internal state for debounced mode
  const [displayValue, setDisplayValue] = useState(value);
  const timerRef = useRef(null);
  const inputRef = useRef(null);

  // Merge refs
  const setRefs = useCallback(
    (node) => {
      inputRef.current = node;
      if (typeof ref === 'function') ref(node);
      else if (ref) ref.current = node;
    },
    [ref],
  );

  // Sync display value when parent changes it (e.g., programmatic clear)
  useEffect(() => {
    if (debounce > 0) {
      setDisplayValue(value);
    }
  }, [value, debounce]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const processValue = useCallback(
    (val) => {
      if (debounce > 0) {
        setDisplayValue(val);
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => onChange(val), debounce);
      } else {
        onChange(val);
      }
    },
    [debounce, onChange],
  );

  const handleChange = useCallback(
    (e) => {
      const raw = e.target.value;

      // JSON parsing for scanner inputs
      if (parseJson && raw.trim().startsWith('{')) {
        try {
          const parsed = JSON.parse(raw.trim());
          const extracted = parsed.id || parsed.shipping_id || parsed.serial_number;
          if (extracted) {
            processValue(String(extracted));
            return;
          }
        } catch {
          // Incomplete JSON — let it through
        }
      }

      processValue(raw);
    },
    [parseJson, processValue],
  );

  const handleClear = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setDisplayValue('');
    onChange('');
    if (onClear) onClear();
    inputRef.current?.focus();
  }, [onChange, onClear]);

  const currentValue = debounce > 0 ? displayValue : value;
  const showClear = currentValue.length > 0 && !disabled;
  const iconSize = ICON_SIZES[size] || ICON_SIZES.md;

  const wrapperClass = [
    styles.wrapper,
    styles[size],
    disabled && styles.disabled,
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const inputClass = [styles.input, inputClassName].filter(Boolean).join(' ');

  return (
    <div className={wrapperClass}>
      <span className={styles.icon} aria-hidden="true">
        {icon || <Search size={iconSize} />}
      </span>
      <input
        ref={setRefs}
        type="text"
        role="searchbox"
        className={inputClass}
        value={currentValue}
        onChange={handleChange}
        placeholder={placeholder}
        disabled={disabled}
        autoFocus={autoFocus}
        aria-label={placeholder}
      />
      {showClear && (
        <button
          type="button"
          className={styles.clearBtn}
          onClick={handleClear}
          aria-label="Limpiar búsqueda"
          tabIndex={-1}
        >
          <X size={iconSize - 2} />
        </button>
      )}
    </div>
  );
});

export default SearchInput;
