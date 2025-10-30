import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import styles from './Navbar.module.css';
import logo from '../assets/white-g-logo.png';
import { useAuthStore } from '../store/authStore';
import ThemeToggle from './ThemeToggle';

export default function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const puedeVerAdmin = ['SUPERADMIN', 'ADMIN'].includes(user?.rol);
  const puedeVerHistorial = ['SUPERADMIN', 'ADMIN', 'GERENTE'].includes(user?.rol);

  const handleLogout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  const isActive = (path) => location.pathname === path;

  const handleLinkClick = () => {
    setMobileMenuOpen(false);
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
    <nav className={styles.navbar}>
      <div className={styles.container}>
        <div className={styles.brand}>
          <img src={logo} alt="Logo" className={styles.logo} />
          <span className={styles.title}>Pricing App</span>
        </div>

        {/* Desktop Links */}
        <div className={styles.links}>
          <Link
            to="/productos"
            className={`${styles.link} ${isActive('/productos') ? styles.active : ''}`}
          >
            📦 Productos
          </Link>

          <Link
            to="/precios-listas"
            className={`${styles.link} ${isActive('/precios-listas') ? styles.active : ''}`}
          >
            💰 Precios por Lista
          </Link>

          {puedeVerHistorial && (
          <Link
            to="/ultimos-cambios"
            className={`${styles.link} ${isActive('/ultimos-cambios') ? styles.active : ''}`}
          >
            📋 Últimos Cambios
          </Link>
          )}

          {puedeVerAdmin && (
          <Link
            to="/admin"
            className={`${styles.link} ${isActive('/admin') ? styles.active : ''}`}
          >
            ⚙️ Admin
          </Link>
          )}
        </div>

        {/* User Info & Logout */}
        <div className={styles.userSection}>
          {user && (
            <div className={styles.userInfo}>
              <span className={styles.userName}>{user.nombre_usuario}</span>
              <span className={`${styles.roleBadge} ${getRoleBadgeColor(user.rol)}`}>
                {user.rol}
              </span>
            </div>
          )}
          <ThemeToggle />
          <button onClick={handleLogout} className={styles.logoutBtn}>
            🚪 Salir
          </button>
        </div>

        {/* Mobile Menu Button */}
        <button
          className={styles.menuButton}
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          aria-label="Toggle menu"
        >
          {mobileMenuOpen ? '✕' : '☰'}
        </button>
      </div>

      {/* Mobile Menu */}
      {mobileMenuOpen && (
        <div className={styles.mobileMenu}>
          <Link
            to="/productos"
            className={`${styles.mobileLink} ${isActive('/productos') ? styles.active : ''}`}
            onClick={handleLinkClick}
          >
            📦 Productos
          </Link>

          <Link
            to="/precios-listas"
            className={`${styles.mobileLink} ${isActive('/precios-listas') ? styles.active : ''}`}
            onClick={handleLinkClick}
          >
            💰 Precios por Lista
          </Link>

          {puedeVerHistorial && (
          <Link
            to="/ultimos-cambios"
            className={`${styles.mobileLink} ${isActive('/ultimos-cambios') ? styles.active : ''}`}
            onClick={handleLinkClick}
          >
            📋 Últimos Cambios
          </Link>
          )}

          {puedeVerAdmin && (
          <Link
            to="/admin"
            className={`${styles.mobileLink} ${isActive('/admin') ? styles.active : ''}`}
            onClick={handleLinkClick}
          >
            ⚙️ Admin
          </Link>
          )}

          {user && (
            <div className={styles.mobileUserInfo}>
              <div className={styles.mobileUserName}>👤 {user.nombre_usuario}</div>
              <div className={`${styles.mobileRoleBadge} ${getRoleBadgeColor(user.rol)}`}>
                {user.rol}
              </div>
            </div>
          )}

          <div className={styles.mobileThemeToggleWrapper}>
            <ThemeToggle />
          </div>

          <button onClick={handleLogout} className={styles.mobileLogoutBtn}>
            🚪 Cerrar Sesión
          </button>
        </div>
      )}
    </nav>
  );
}
