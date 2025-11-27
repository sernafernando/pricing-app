import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useState } from 'react';
import styles from './Navbar.module.css';
import logo from '../assets/white-g-logo.png';
import { useAuthStore } from '../store/authStore';
import ThemeToggle from './ThemeToggle';
import NotificationBell from './NotificationBell';

export default function Navbar() {
  const location = useLocation();
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(null);
  const puedeVerAdmin = ['SUPERADMIN', 'ADMIN'].includes(user?.rol);
  const puedeVerHistorial = ['SUPERADMIN', 'ADMIN', 'GERENTE'].includes(user?.rol);

  const isDropdownActive = (paths) => {
    return paths.some(path => location.pathname === path);
  };

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
          <a href="/productos" onClick={(e) => { e.preventDefault(); window.location.href = '/productos'; }}>
            <img src={logo} alt="Logo" className={styles.logo} />
          </a>
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

          <Link
            to="/mla-banlist"
            className={`${styles.link} ${isActive('/mla-banlist') ? styles.active : ''}`}
          >
            🚫 Banlist
          </Link>

          <Link
            to="/items-sin-mla"
            className={`${styles.link} ${isActive('/items-sin-mla') ? styles.active : ''}`}
          >
            📋 Items sin MLA
          </Link>

          {/* Dropdown Reportes */}
          <div
            className={styles.dropdown}
            onMouseEnter={() => setDropdownOpen('reportes')}
            onMouseLeave={() => setDropdownOpen(null)}
          >
            <div
              className={`${styles.link} ${styles.dropdownTrigger} ${isDropdownActive(['/dashboard-ventas', '/dashboard-metricas-ml', '/calculos', '/ultimos-cambios']) ? styles.active : ''}`}
              onClick={() => setDropdownOpen(dropdownOpen === 'reportes' ? null : 'reportes')}
            >
              📊 Reportes ▾
            </div>
            {dropdownOpen === 'reportes' && (
              <div
                className={styles.dropdownMenu}
                onMouseEnter={() => setDropdownOpen('reportes')}
              >
                <Link
                  to="/dashboard-ventas"
                  className={`${styles.dropdownItem} ${isActive('/dashboard-ventas') ? styles.activeDropdown : ''}`}
                  onClick={() => setDropdownOpen(null)}
                >
                  📊 Dashboard Ventas
                </Link>
                <Link
                  to="/dashboard-metricas-ml"
                  className={`${styles.dropdownItem} ${isActive('/dashboard-metricas-ml') ? styles.activeDropdown : ''}`}
                  onClick={() => setDropdownOpen(null)}
                >
                  📈 Métricas ML
                </Link>
                <Link
                  to="/calculos"
                  className={`${styles.dropdownItem} ${isActive('/calculos') ? styles.activeDropdown : ''}`}
                  onClick={() => setDropdownOpen(null)}
                >
                  🧮 Cálculos
                </Link>
                {puedeVerHistorial && (
                  <Link
                    to="/ultimos-cambios"
                    className={`${styles.dropdownItem} ${isActive('/ultimos-cambios') ? styles.activeDropdown : ''}`}
                    onClick={() => setDropdownOpen(null)}
                  >
                    📋 Últimos Cambios
                  </Link>
                )}
              </div>
            )}
          </div>

          {/* Dropdown Gestión (solo para admins) */}
          {puedeVerAdmin && (
            <div
              className={styles.dropdown}
              onMouseEnter={() => setDropdownOpen('gestion')}
              onMouseLeave={() => setDropdownOpen(null)}
            >
              <div
                className={`${styles.link} ${styles.dropdownTrigger} ${isDropdownActive(['/gestion-pm', '/admin']) ? styles.active : ''}`}
                onClick={() => setDropdownOpen(dropdownOpen === 'gestion' ? null : 'gestion')}
              >
                ⚙️ Gestión ▾
              </div>
              {dropdownOpen === 'gestion' && (
                <div
                  className={styles.dropdownMenu}
                  onMouseEnter={() => setDropdownOpen('gestion')}
                >
                  <Link
                    to="/gestion-pm"
                    className={`${styles.dropdownItem} ${isActive('/gestion-pm') ? styles.activeDropdown : ''}`}
                    onClick={() => setDropdownOpen(null)}
                  >
                    👤 Gestión PMs
                  </Link>
                  <Link
                    to="/admin"
                    className={`${styles.dropdownItem} ${isActive('/admin') ? styles.activeDropdown : ''}`}
                    onClick={() => setDropdownOpen(null)}
                  >
                    ⚙️ Admin
                  </Link>
                </div>
              )}
            </div>
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
          <NotificationBell />
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

          <Link
            to="/mla-banlist"
            className={`${styles.mobileLink} ${isActive('/mla-banlist') ? styles.active : ''}`}
            onClick={handleLinkClick}
          >
            🚫 Banlist MLAs
          </Link>

          <Link
            to="/dashboard-ventas"
            className={`${styles.mobileLink} ${isActive('/dashboard-ventas') ? styles.active : ''}`}
            onClick={handleLinkClick}
          >
            📊 Dashboard Ventas
          </Link>

          <Link
            to="/calculos"
            className={`${styles.mobileLink} ${isActive('/calculos') ? styles.active : ''}`}
            onClick={handleLinkClick}
          >
            🧮 Cálculos
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
          <>
          <Link
            to="/gestion-pm"
            className={`${styles.mobileLink} ${isActive('/gestion-pm') ? styles.active : ''}`}
            onClick={handleLinkClick}
          >
            👤 Gestión PMs
          </Link>
          <Link
            to="/admin"
            className={`${styles.mobileLink} ${isActive('/admin') ? styles.active : ''}`}
            onClick={handleLinkClick}
          >
            ⚙️ Admin
          </Link>
          </>
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
