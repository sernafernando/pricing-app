/**
 * PublishFieldRow — one labelled control (label + input/textarea + hint/
 * error). The D2 primitive: `ProductFieldsSection` / `VariantFieldsSection`
 * render a loop of these for the PR-7 field catalog. `testId` tags the
 * wrapper for the D2 field-to-control audit (task 7.1).
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
  as = 'input',
  maxLength,
  placeholder,
  readOnly = false,
  testId,
  inputRef,
}) {
  const Control = as === 'textarea' ? 'textarea' : 'input';
  return (
    <div className={styles.section} data-testid={testId}>
      <label className={styles.sectionTitle} htmlFor={id}>
        {label}
      </label>
      <Control
        id={id}
        ref={inputRef}
        {...(as === 'textarea' ? {} : { type })}
        className={styles.titleInput}
        value={value}
        maxLength={maxLength}
        placeholder={placeholder}
        readOnly={readOnly}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <p className={styles.fieldHint}>{hint}</p>}
      {error && <p className={styles.fieldError}>{error}</p>}
    </div>
  );
}
