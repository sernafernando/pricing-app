/**
 * OperadorPinLock — Pantalla de bloqueo con PIN para tabs que requieren
 * identificación de operador.
 *
 * Uso:
 *   <OperadorPinLock
 *     tabKey="envios-flex"
 *     pagePath="/pedidos-preparacion"
 *     operador={useOperador()}
 *   >
 *     <TabEnviosFlex />
 *   </OperadorPinLock>
 *
 * Si el tab NO requiere PIN (no configurado en backend), muestra children directamente.
 * Si el tab requiere PIN y no hay operador autenticado, muestra la pantalla de PIN.
 * Cuando el operador se autentica, muestra children + barra inferior con el nombre.
 */

import { useState, useEffect, useRef } from 'react';
import { Lock, LogOut, User, CheckCircle } from 'lucide-react';
import styles from './OperadorPinLock.module.css';

export default function OperadorPinLock({
  tabKey,
  pagePath,
  operador,
  children,
}) {
  const {
    operadorActivo,
    configLoading,
    necesitaPin,
    validarPin,
    cerrarSesionOperador,
    iniciarTimer,
  } = operador;

  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [validando, setValidando] = useState(false);
  const [showSuccess, setShowSuccess] = useState(false);
  const inputRef = useRef(null);

  // Si no necesita PIN, mostrar children directo
  const requierePin = necesitaPin(tabKey, pagePath);

  // Focus en el input de PIN al montar
  useEffect(() => {
    if (requierePin && !operadorActivo && inputRef.current) {
      inputRef.current.focus();
    }
  }, [requierePin, operadorActivo]);

  // Iniciar timer de inactividad cuando el operador se autentica
  useEffect(() => {
    if (operadorActivo && requierePin) {
      iniciarTimer(tabKey, pagePath);
    }
  }, [operadorActivo, requierePin, iniciarTimer, tabKey, pagePath]);

  // Auto-submit cuando se ingresan 4 dígitos
  useEffect(() => {
    if (pin.length === 4) {
      handleSubmit();
    }
  }, [pin]);

  const handleSubmit = async () => {
    if (pin.length !== 4 || validando) return;

    setValidando(true);
    setError('');

    const result = await validarPin(pin);

    if (result.ok) {
      setShowSuccess(true);
      setPin('');

      // Flash de éxito por 1 segundo
      setTimeout(() => {
        setShowSuccess(false);
      }, 1000);
    } else {
      setError(result.error || 'PIN inválido');
      setPin('');
      // Re-focus
      setTimeout(() => {
        if (inputRef.current) {
          inputRef.current.focus();
        }
      }, 100);
    }

    setValidando(false);
  };

  const handlePinChange = (e) => {
    const value = e.target.value.replace(/\D/g, '');
    if (value.length <= 4) {
      setPin(value);
      setError('');
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      handleSubmit();
    }
  };

  // ── Loading config ──────────────────────────────────
  if (configLoading) {
    return <div className={styles.loadingConfig}>Cargando...</div>;
  }

  // ── No requiere PIN — pasar directo ─────────────────
  if (!requierePin) {
    return children;
  }

  // ── Requiere PIN — success flash ────────────────────
  if (showSuccess) {
    return (
      <div className={styles.overlay}>
        <div className={styles.successCard}>
          <CheckCircle size={48} className={styles.successIcon} />
          <h2 className={styles.successName}>{operadorActivo?.nombre}</h2>
        </div>
      </div>
    );
  }

  // ── Requiere PIN y ya autenticado — mostrar children + barra ──
  if (operadorActivo) {
    return (
      <div className={styles.wrapper}>
        {children}
        <div className={styles.operadorBar}>
          <div className={styles.operadorInfo}>
            <User size={14} />
            <span className={styles.operadorNombre}>{operadorActivo.nombre}</span>
          </div>
          <button
            onClick={cerrarSesionOperador}
            className={styles.btnCerrarSesion}
            title="Cerrar sesión de operador"
            aria-label="Cerrar sesión de operador"
          >
            <LogOut size={14} />
            Cerrar
          </button>
        </div>
      </div>
    );
  }

  // ── Requiere PIN y NO autenticado — mostrar lock ──────
  return (
    <div className={styles.overlay}>
      <div className={styles.lockCard}>
        <div className={styles.lockIcon}>
          <Lock size={32} />
        </div>
        <h2 className={styles.lockTitle}>Identificación requerida</h2>
        <p className={styles.lockDesc}>
          Ingresá tu PIN de 4 dígitos para acceder a este tab.
        </p>

        <div className={styles.pinContainer}>
          <input
            ref={inputRef}
            type="password"
            inputMode="numeric"
            maxLength={4}
            value={pin}
            onChange={handlePinChange}
            onKeyDown={handleKeyDown}
            className={`${styles.pinInput} ${error ? styles.pinInputError : ''}`}
            placeholder="----"
            autoComplete="off"
            disabled={validando}
          />

          {/* Dots indicator */}
          <div className={styles.pinDots}>
            {[0, 1, 2, 3].map((i) => (
              <span
                key={i}
                className={`${styles.dot} ${i < pin.length ? styles.dotFilled : ''}`}
              />
            ))}
          </div>
        </div>

        {error && <p className={styles.pinError}>{error}</p>}
        {validando && <p className={styles.pinValidando}>Validando...</p>}
      </div>
    </div>
  );
}
