import { useState, useRef, useEffect } from 'react';
import styles from './EditableCell.module.css';

/**
 * EditableCell - Celda editable con estilo Carbon Design (underline input)
 * 
 * Props:
 * - value: Valor actual
 * - onChange: Callback cuando cambia el valor (recibe el nuevo valor)
 * - type: 'text' | 'number' | 'select'
 * - options: Array de opciones para select (ej: [{value: 'x', label: 'X'}] o ['x', 'y'])
 * - placeholder: Placeholder cuando está vacío
 * - className: Clases adicionales
 * - disabled: Si está deshabilitado
 * - step: Step para inputs numéricos (default: 'any')
 * - min: Valor mínimo para números
 * - max: Valor máximo para números
 * - readOnly: Si es solo lectura (no editable)
 * - style: Estilos inline adicionales
 */
export default function EditableCell({
  value = '',
  onChange,
  type = 'text',
  options = [],
  placeholder = '',
  className = '',
  disabled = false,
  step = 'any',
  min,
  max,
  readOnly = false,
  style = {}
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [localValue, setLocalValue] = useState(value);
  const inputRef = useRef(null);

  // Sincronizar con value externo
  useEffect(() => {
    setLocalValue(value);
  }, [value]);

  // Focus automático al entrar en modo edición
  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      if (type === 'text' && inputRef.current.select) {
        inputRef.current.select();
      }
    }
  }, [isEditing, type]);

  const handleClick = () => {
    if (!disabled && !readOnly) {
      setIsEditing(true);
    }
  };

  const handleBlur = () => {
    setIsEditing(false);
    if (onChange && localValue !== value) {
      onChange(localValue);
    }
  };

  const handleChange = (e) => {
    const newValue = type === 'number' ? (e.target.value === '' ? '' : parseFloat(e.target.value)) : e.target.value;
    setLocalValue(newValue);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      inputRef.current?.blur();
    }
    if (e.key === 'Escape') {
      setLocalValue(value); // Revertir cambios
      setIsEditing(false);
    }
  };

  // Formatear valor para display
  const getDisplayValue = () => {
    if (type === 'select') {
      const option = options.find(opt => 
        typeof opt === 'object' ? opt.value === value : opt === value
      );
      if (option) {
        return typeof option === 'object' ? option.label : option;
      }
      return value || placeholder;
    }
    return value || placeholder;
  };

  const wrapperClasses = `${styles.editableCell} ${
    isEditing ? styles.editing : ''
  } ${disabled ? styles.disabled : ''} ${
    readOnly ? styles.readOnly : ''
  } ${className.includes('hasOverride') ? styles.hasOverride : ''} ${className}`;

  if (type === 'select') {
    return (
      <div className={wrapperClasses} style={style}>
        {isEditing && !disabled && !readOnly ? (
          <select
            ref={inputRef}
            value={localValue}
            onChange={handleChange}
            onBlur={handleBlur}
            onKeyDown={handleKeyDown}
            className={styles.input}
            disabled={disabled}
          >
            <option value="">{placeholder || 'Seleccionar...'}</option>
            {options.map((opt, idx) => {
              const optValue = typeof opt === 'object' ? opt.value : opt;
              const optLabel = typeof opt === 'object' ? opt.label : opt;
              return (
                <option key={idx} value={optValue}>
                  {optLabel}
                </option>
              );
            })}
          </select>
        ) : (
          <div className={styles.display} onClick={handleClick}>
            {getDisplayValue()}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={wrapperClasses} style={style}>
      {isEditing && !disabled && !readOnly ? (
        <input
          ref={inputRef}
          type={type}
          value={localValue}
          onChange={handleChange}
          onBlur={handleBlur}
          onKeyDown={handleKeyDown}
          className={styles.input}
          placeholder={placeholder}
          disabled={disabled}
          step={step}
          min={min}
          max={max}
        />
      ) : (
        <div className={styles.display} onClick={handleClick}>
          {getDisplayValue()}
        </div>
      )}
    </div>
  );
}
