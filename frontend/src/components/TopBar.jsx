import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { useTheme } from '../contexts/ThemeContext';
import { Menu, CloudRain, Droplets, Wind } from 'lucide-react';

import ThemeToggleSimple from './ThemeToggleSimple';
import NotificationBell from './NotificationBell';
import { useWeather } from '../hooks/useWeather';
import api from '../services/api';
import styles from './TopBar.module.css';
import logoIcon from '../assets/white-g-logo.png';

export default function TopBar({ sidebarExpanded = true, onMobileMenuToggle }) {
  const user = useAuthStore((state) => state.user);
  const { highContrast, toggleHighContrast } = useTheme();
  const navigate = useNavigate();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [facturadoHoy, setFacturadoHoy] = useState(null);
  const [loadingMetric, setLoadingMetric] = useState(false);
  const { weather } = useWeather();

  // Determinar si el usuario puede ver facturado ML
  // Los que ven $0 o no tienen acceso a la métrica, ven el clima
  const showFacturado = facturadoHoy !== null && Number(facturadoHoy) > 0;

  useEffect(() => {
    if (user) {
      setLoadingMetric(true);
      const hoy = new Date().toISOString().split('T')[0];
      api.get(`/dashboard-ml/metricas-generales?fecha_desde=${hoy}&fecha_hasta=${hoy}`)
        .then(res => {
          setFacturadoHoy(res.data.total_ventas_ml);
        })
        .catch(() => {
          setFacturadoHoy(null);
        })
        .finally(() => {
          setLoadingMetric(false);
        });
    }
  }, [user]);

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
          <img src={logoIcon} alt="Logo" className={styles.logoIcon} />
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
          <Link to="/dashboard-metricas-ml" className={styles.metricCard} title="Facturado ML hoy - Click para ver métricas">
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

      {/* Right: Notifications, User Menu */}
      <div className={styles.right}>
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
