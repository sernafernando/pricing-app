import { useState, useEffect, useRef } from 'react';
import { rrhhAPI } from '../services/api';
import styles from './BirthdayBadge.module.css';

// SVG de globos de cumpleaños inline
const BalloonsSVG = ({ size = 20 }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
  >
    {/* Globo izquierdo */}
    <ellipse cx="8" cy="8" rx="4.5" ry="5.5" fill="#f59e0b" opacity="0.85" />
    <path d="M8 13.5 L7.5 15 L8.5 15 Z" fill="#f59e0b" />
    <line x1="8" y1="15" x2="9" y2="22" stroke="#d97706" strokeWidth="0.8" />
    {/* Globo derecho */}
    <ellipse cx="15" cy="6.5" rx="4" ry="5" fill="#3b82f6" opacity="0.85" />
    <path d="M15 11.5 L14.5 13 L15.5 13 Z" fill="#3b82f6" />
    <line x1="15" y1="13" x2="13" y2="22" stroke="#2563eb" strokeWidth="0.8" />
    {/* Nudo */}
    <circle cx="11" cy="21.5" r="1" fill="none" stroke="#a3a3a3" strokeWidth="0.6" />
  </svg>
);

export default function BirthdayBadge() {
  const [cumpleanos, setCumpleanos] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const fetchCumpleanos = async () => {
      try {
        const { data } = await rrhhAPI.cumpleanosHoy();
        setCumpleanos(data.empleados || []);
      } catch {
        setCumpleanos([]);
      }
    };
    fetchCumpleanos();

    // Refrescar cada 30 minutos
    const interval = setInterval(fetchCumpleanos, 30 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  // Cerrar al clickear fuera
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  if (cumpleanos.length === 0) return null;

  return (
    <div className={styles.container} ref={ref}>
      <button
        className={styles.badgeButton}
        onClick={() => setOpen(!open)}
        title={`${cumpleanos.length} cumpleaños hoy`}
      >
        <BalloonsSVG size={22} />
        <span className={styles.count}>{cumpleanos.length}</span>
      </button>

      {open && (
        <div className={styles.dropdown}>
          <div className={styles.dropdownHeader}>
            <BalloonsSVG size={16} />
            Cumpleaños hoy
          </div>
          <div className={styles.dropdownList}>
            {cumpleanos.map((c) => (
              <div key={c.empleado_id} className={styles.dropdownItem}>
                <span className={styles.itemNombre}>
                  {c.nombre} {c.apellido}
                </span>
                {c.edad && (
                  <span className={styles.itemEdad}>
                    {c.edad} años
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
