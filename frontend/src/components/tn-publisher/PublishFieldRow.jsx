/**
 * PublishFieldRow — one labelled control (label + input + hint/error).
 * The D2 primitive: `ProductFieldsSection` / `VariantFieldsSection` render
 * a loop of these once PR-7 wires the field catalog. In this PR (pure
 * refactor) it backs the Título control with byte-identical markup to the
 * pre-decomposition inline JSX.
 */
import styles from './TnPublishModal.module.css';

export default function PublishFieldRow({
  id,
  label,
  value,
  onChange,
  hint,
  error,
  type = 'text',
  maxLength,
  placeholder,
}) {
  return (
    <div className={styles.section}>
      <label className={styles.sectionTitle} htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        type={type}
        className={styles.titleInput}
        value={value}
        maxLength={maxLength}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <p className={styles.fieldHint}>{hint}</p>}
      {error && <p className={styles.fieldError}>{error}</p>}
    </div>
  );
}
