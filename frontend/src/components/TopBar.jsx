import { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

import ThemeToggleSimple from './ThemeToggleSimple';
import NotificationBell from './NotificationBell';
import axios from 'axios';
import styles from './TopBar.module.css';
import logoIcon from '../assets/white-g-logo.png';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default function TopBar({ sidebarExpanded = true }) {
  const user = useAuthStore((state) => state.user);
  const navigate = useNavigate();
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [facturadoHoy, setFacturadoHoy] = useState(null);

  useEffect(() => {
    if (user) {
      const hoy = new Date().toISOString().split('T')[0];
      api.get(`/dashboard-ml/metricas-generales?fecha_desde=${hoy}&fecha_hasta=${hoy}`)
        .then(res => {
          setFacturadoHoy(res.data.total_ventas_ml);
        })
        .catch(err => {
          console.error('Error cargando facturado:', err);
        });
    }
  }, [user]);

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

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
      {/* Left: Logo pequeño */}
      <div className={styles.left}>
        <Link to="/productos" className={styles.logoLink}>
          <img src={logoIcon} alt="Logo" className={styles.logoIcon} />
        </Link>
      </div>

      {/* Center: Área de métricas */}
      <div className={styles.metrics}>
        {facturadoHoy !== null && (
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
          onClick={() => setUserMenuOpen(!userMenuOpen)}
          role="button"
          tabIndex={0}
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
