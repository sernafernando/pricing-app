import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import ThemeToggle from './ThemeToggle';
import NotificationBell from './NotificationBell';
import styles from './TopBar.module.css';
import logoIcon from '../assets/white-g-logo.png';

export default function TopBar({ sidebarExpanded = true }) {
  const user = useAuthStore((state) => state.user);
  const navigate = useNavigate();
  const [userMenuOpen, setUserMenuOpen] = useState(false);

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

      {/* Center: Área de métricas (vacío por ahora, slot para futuro) */}
      <div className={styles.metrics}>
        {/* Placeholder - aquí irían métricas dinámicas tipo "Facturado Hoy" */}
      </div>

      {/* Right: Notifications, Theme, User Menu */}
      <div className={styles.right}>
        <NotificationBell />
        <ThemeToggle />
        
        <div 
          className={styles.userMenu} 
          onClick={() => setUserMenuOpen(!userMenuOpen)}
          role="button"
          tabIndex={0}
        >
          <div className={styles.userInfo}>
            <span className={styles.userName}>{user?.nombre_usuario}</span>
            <span className={`${styles.userRole} ${getRoleBadgeColor(user?.rol)}`}>
              {user?.rol}
            </span>
          </div>
          
          {userMenuOpen && (
            <div className={styles.userDropdown}>
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
