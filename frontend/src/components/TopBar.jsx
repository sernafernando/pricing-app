import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { useTheme, useBrandFromPermisos } from '../contexts/ThemeContext';
import { Menu, CloudRain, Droplets, Wind, Fingerprint } from 'lucide-react';

import ThemeToggleSimple from './ThemeToggleSimple';
import NotificationBell from './NotificationBell';
import FreeShippingBadge from './FreeShippingBadge';
import MejoresOfertasBadge from './MejoresOfertasBadge';
import TicketBadge from './TicketBadge';
import BirthdayBadge from './BirthdayBadge';
import { useWeather } from '../hooks/useWeather';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import { businessToday } from '../utils/dateRangePresets';
import { toLocalDateString } from '../utils/dateUtils';
import { defaultView } from '../utils/metricasMlUrl';
import { buildMetricasMLParams } from '../utils/metricasMlParams';
import { tpRequestParams } from '../utils/metricasMlTp';
import { isTpSolo } from './ventasMl/tpMode';
import styles from './TopBar.module.css';
import logoIcon from '../assets/white-g-logo.png';

// Served from public/: the TP-Link logo is a brand asset, not a bundled icon.
export const TPLINK_LOGO_SRC = '/brand/tplink-logo-white.png';

/**
 * The request Métricas ML makes for today with nothing else chosen: its "Facturado bruto" is the chip's amount.
 * One row is enough, the KPIs sum the whole board.
 */
function facturadoHoyParams(tpSolo, today = businessToday()) {
  const view = defaultView(today);
  // The API reads the day as YYYY-MM-DD: a Date would travel as a UTC timestamp and get a 422.
  const day = toLocalDateString(today);
  return {
    ...buildMetricasMLParams({ ...view, fechaDesde: day, fechaHasta: day, tpSolo }),
    ...tpRequestParams(tpSolo),
    sort: view.sort.key,
    sort_dir: view.sort.desc ? 'desc' : 'asc',
    limit: 1,
    offset: 0,
  };
}

export default function TopBar({ sidebarExpanded = true, sidebarHidden = false, onMobileMenuToggle }) {
  const user = useAuthStore((state) => state.user);
  const { highContrast, toggleHighContrast } = useTheme();
  const brand = useBrandFromPermisos();
  const navigate = useNavigate();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [facturadoHoy, setFacturadoHoy] = useState(null);
  const [loadingMetric, setLoadingMetric] = useState(false);
  const { weather } = useWeather();
  const { permisos, tienePermiso } = usePermisos();
  const puedeVerMetricas = tienePermiso('ml_metricas.ver');
  const tpSolo = isTpSolo(permisos);

  // Determinar si el usuario puede ver facturado ML
  // Los que ven $0 o no tienen acceso a la métrica, ven el clima
  const showFacturado = facturadoHoy !== null && Number(facturadoHoy) > 0;

  useEffect(() => {
    if (!user || !puedeVerMetricas) {
      setFacturadoHoy(null);
      setLoadingMetric(false);
      return;
    }
    let cancelled = false;
    setLoadingMetric(true);
    api
      .get('/ml-metricas/board', { params: facturadoHoyParams(tpSolo) })
      .then((res) => {
        if (!cancelled) setFacturadoHoy(res.data?.kpis?.gross?.value ?? null);
      })
      .catch((error) => {
        console.error('Facturado ML Hoy: the Métricas ML board request failed', error);
        if (!cancelled) setFacturadoHoy(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingMetric(false);
      });
    return () => {
      cancelled = true;
    };
  }, [user, puedeVerMetricas, tpSolo]);

  const logout = useAuthStore((state) => state.logout);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const toggleUserMenu = () => setUserMenuOpen(!userMenuOpen);

  const handleUserMenuKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleUserMenu();
    }
  };

  // Cerrar menú al hacer click fuera
  useEffect(() => {
    if (!userMenuOpen) return;

    const handleClickOutside = (e) => {
      if (!e.target.closest('[data-user-menu]')) {
        setUserMenuOpen(false);
      }
    };

    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, [userMenuOpen]);

  const getRoleBadgeColor = (rol) => {
    switch (rol) {
      case 'SUPERADMIN': return styles.roleSuperAdmin;
      case 'ADMIN': return styles.roleAdmin;
      case 'GERENTE': return styles.roleGerente;
      default: return styles.roleDefault;
    }
  };

  return (
    <header
      className={styles.topbar}
      data-sidebar-expanded={sidebarExpanded}
      data-sidebar-hidden={sidebarHidden}
    >
      {/* Left: Hamburguesa (mobile) + Logo */}
      <div className={styles.left}>
        <button 
          className={styles.mobileMenuBtn}
          onClick={onMobileMenuToggle}
          aria-label="Abrir menú"
        >
          <Menu size={24} />
        </button>
        
        <Link to="/productos" className={styles.logoLink}>
          {brand === 'tplink' ? (
            // Global class from brand-tplink.css: the module's .logoIcon inverts
            // the logo in light mode, which the brand header must not do.
            <img src={TPLINK_LOGO_SRC} alt="TP-Link" className="tplink-brand-logo" />
          ) : (
            <img src={logoIcon} alt="Logo" className={styles.logoIcon} />
          )}
        </Link>
      </div>

      {/* Center: Área de métricas / Clima */}
      <div className={styles.metrics}>
        {loadingMetric && (
          <div className={styles.metricCard}>
            <span className={styles.metricLabel}>Facturado ML Hoy</span>
            <span className={styles.metricValue}>...</span>
          </div>
        )}
        {!loadingMetric && showFacturado && (
          <Link to="/metricas-ml" className={styles.metricCard} title="Facturado ML hoy - Click para ver métricas">
            <span className={styles.metricLabel}>Facturado ML Hoy</span>
            <span className={styles.metricValue}>
              ${Number(facturadoHoy).toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </span>
          </Link>
        )}
        {!loadingMetric && !showFacturado && weather && (
          <div className={styles.weatherWidget} title={`${weather.city} — ${weather.description}`}>
            <div className={styles.weatherMain}>
              <img
                src={weather.icon_url}
                alt={weather.description}
                className={styles.weatherIcon}
              />
              <span className={styles.weatherTemp}>{weather.temp}°</span>
            </div>
            <div className={styles.weatherDetails}>
              <span className={styles.weatherDesc}>{weather.description}</span>
              <div className={styles.weatherMeta}>
                <span className={styles.weatherMetaItem}>
                  <Droplets size={12} />
                  {weather.humidity}%
                </span>
                <span className={styles.weatherMetaItem}>
                  <Wind size={12} />
                  {weather.wind_speed} m/s
                </span>
                {weather.is_rainy && (
                  <span className={`${styles.weatherMetaItem} ${styles.weatherRain}`}>
                    <CloudRain size={12} />
                    Lluvia
                  </span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Right: Alerts, Notifications, User Menu */}
      <div className={styles.right}>
        <BirthdayBadge />
        <TicketBadge />
        <FreeShippingBadge />
        <MejoresOfertasBadge />
        <NotificationBell />
        
        <div 
          className={styles.userMenu} 
          onClick={toggleUserMenu}
          onKeyDown={handleUserMenuKeyDown}
          role="button"
          tabIndex={0}
          data-user-menu
        >
          <div className={styles.userAvatar}>
            {user?.nombre?.charAt(0).toUpperCase() || user?.username?.charAt(0).toUpperCase() || 'U'}
          </div>
          
          {userMenuOpen && (
            <div className={styles.userDropdown}>
              <div className={styles.userDropdownHeader}>
                <span className={styles.dropdownUserName}>{user?.nombre || user?.username}</span>
                <span className={`${styles.dropdownUserRole} ${getRoleBadgeColor(user?.rol)}`}>
                  {user?.rol}
                </span>
              </div>
              
              <div className={styles.dropdownDivider}></div>
              
              <div className={styles.dropdownItem}>
                <ThemeToggleSimple />
              </div>
              
              <div className={styles.dropdownItem}>
                <button 
                  className={`${styles.highContrastBtn} ${highContrast ? styles.active : ''}`}
                  onClick={toggleHighContrast}
                  type="button"
                >
                  {highContrast && <span className={styles.checkmark}>✓</span>}
                  Alto contraste
                </button>
              </div>
              
              {user?.tiene_empleado && (
                <>
                  <div className={styles.dropdownDivider}></div>
                  <Link
                    to="/fichaje"
                    className={styles.fichajeLink}
                    onClick={() => setUserMenuOpen(false)}
                  >
                    <Fingerprint size={16} />
                    Fichaje
                  </Link>
                </>
              )}

              <div className={styles.dropdownDivider}></div>
              
              <button onClick={handleLogout} className={styles.logoutBtn}>
                Cerrar sesión
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
