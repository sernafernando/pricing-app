import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { Menu } from 'lucide-react';

import ThemeToggleSimple from './ThemeToggleSimple';
import NotificationBell from './NotificationBell';
import api from '../services/api';
import styles from './TopBar.module.css';
import logoIcon from '../assets/white-g-logo.png';

export default function TopBar({ sidebarExpanded = true, onMobileMenuToggle }) {
  const user = useAuthStore((state) => state.user);
  const navigate = useNavigate();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [facturadoHoy, setFacturadoHoy] = useState(null);
  const [loadingMetric, setLoadingMetric] = useState(false);

  useEffect(() => {
    if (user) {
      setLoadingMetric(true);
      const hoy = new Date().toISOString().split('T')[0];
      api.get(`/dashboard-ml/metricas-generales?fecha_desde=${hoy}&fecha_hasta=${hoy}`)
        .then(res => {
          setFacturadoHoy(res.data.total_ventas_ml);
        })
        .catch(err => {
          console.error('Error cargando facturado:', err);
          setFacturadoHoy(null);
        })
        .finally(() => {
          setLoadingMetric(false);
        });
    }
  }, [user]);

  const handleLogout = () => {
    localStorage.removeItem('token');
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

      {/* Center: Área de métricas */}
      <div className={styles.metrics}>
        {loadingMetric && (
          <div className={styles.metricCard}>
            <span className={styles.metricLabel}>Facturado ML Hoy</span>
            <span className={styles.metricValue}>...</span>
          </div>
        )}
        {!loadingMetric && facturadoHoy !== null && (
          <Link to="/dashboard-metricas-ml" className={styles.metricCard} title="Facturado ML hoy - Click para ver métricas">
            <span className={styles.metricLabel}>Facturado ML Hoy</span>
            <span className={styles.metricValue}>
              ${Number(facturadoHoy).toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
            </span>
          </Link>
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
