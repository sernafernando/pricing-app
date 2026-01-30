import { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { usePermisos } from '../contexts/PermisosContext';
import SidebarSection from './SidebarSection';
import { Package, ClipboardList, BarChart3, Settings, PanelLeftClose, PanelLeft, ChevronsDown, ChevronsUp } from 'lucide-react';
import styles from './Sidebar.module.css';

export default function Sidebar() {
  // Estado persistido: true = expandido fijo, false = colapsado
  const [isPinned, setIsPinned] = useState(() => {
    const saved = localStorage.getItem('sidebarPinned');
    return saved === null ? true : saved === 'true';
  });
  
  // Estado temporal para hover peek
  const [isHovering, setIsHovering] = useState(false);
  
  // Estado para expandir/colapsar todos los menús
  const [expandAll, setExpandAll] = useState(false);
  
  const { tienePermiso, tieneAlgunPermiso } = usePermisos();
  const location = useLocation();

  // Persiste el estado de pin
  useEffect(() => {
    localStorage.setItem('sidebarPinned', isPinned);
  }, [isPinned]);

  const togglePin = () => {
    setIsPinned(!isPinned);
    setIsHovering(false); // Reset hover state al cambiar pin
  };

  const handleMouseEnter = () => {
    if (!isPinned) {
      setIsHovering(true);
    }
  };

  const handleMouseLeave = () => {
    if (!isPinned) {
      setIsHovering(false);
    }
  };

  // Determina si el sidebar está efectivamente expandido
  const isExpanded = isPinned || isHovering;

  // Menú de navegación estructurado
  const menuSections = [
    {
      id: 'productos',
      title: 'Productos',
      icon: Package,
      defaultOpen: true,
      items: [
        { label: 'Productos', path: '/productos', permiso: 'productos.ver' },
        { label: 'Tienda', path: '/tienda', permiso: 'productos.ver_tienda' },
        { label: 'Precios por Lista', path: '/precios-listas', permiso: 'productos.ver' },
        { label: 'Banlist MLAs', path: '/mla-banlist', permiso: 'admin.gestionar_mla_banlist' },
        { label: 'Items sin MLA', path: '/items-sin-mla', permiso: 'admin.gestionar_mla_banlist' },
      ],
    },
    {
      id: 'operaciones',
      title: 'Operaciones',
      icon: ClipboardList,
      defaultOpen: false,
      items: [
        { label: 'Preparación', path: '/pedidos-preparacion', permiso: 'ordenes.ver_preparacion' },
        { label: 'Turbo', path: '/turbo-routing', permiso: 'ordenes.gestionar_turbo_routing' },
        { label: 'Clientes', path: '/clientes', permiso: 'clientes.ver' },
      ],
    },
    {
      id: 'reportes',
      title: 'Reportes',
      icon: BarChart3,
      defaultOpen: false,
      items: [
        { label: 'Dashboard Ventas', path: '/dashboard-ventas', permiso: 'ventas_ml.ver_dashboard,ventas_fuera.ver_dashboard,ventas_tn.ver_dashboard', multiple: true },
        { label: 'Métricas ML', path: '/dashboard-metricas-ml', permiso: 'ventas_ml.ver_dashboard' },
        { label: 'Ventas por Fuera', path: '/dashboard-ventas-fuera', permiso: 'ventas_fuera.ver_dashboard' },
        { label: 'Tienda Nube', path: '/dashboard-tienda-nube', permiso: 'ventas_tn.ver_dashboard' },
        { label: 'Cálculos', path: '/calculos', permiso: 'reportes.ver_calculadora' },
        { label: 'Últimos Cambios', path: '/ultimos-cambios', permiso: 'productos.ver_auditoria' },
      ],
    },
    {
      id: 'gestion',
      title: 'Gestión',
      icon: Settings,
      defaultOpen: false,
      items: [
        { label: 'Gestión PMs', path: '/gestion-pm', permiso: 'admin.gestionar_pms' },
        { label: 'Admin', path: '/admin', permiso: 'admin.ver_panel' },
      ],
    },
  ];

  return (
    <aside
      className={styles.sidebar}
      data-pinned={isPinned}
      data-expanded={isExpanded}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* Expand/Collapse All - Arriba */}
      {isExpanded && (
        <button
          onClick={() => setExpandAll(!expandAll)}
          className={styles.expandAllBtn}
          aria-label={expandAll ? 'Colapsar todos' : 'Expandir todos'}
          title={expandAll ? 'Colapsar todos' : 'Expandir todos'}
        >
          {expandAll ? <ChevronsUp size={16} /> : <ChevronsDown size={16} />}
        </button>
      )}

      {/* Navigation */}
      <nav className={styles.nav}>
        {menuSections.map((section) => {
          // Filtrar ítems con permisos
          const visibleItems = section.items.filter((item) => {
            if (item.multiple) {
              // Si tiene múltiples permisos separados por coma
              const permisos = item.permiso.split(',');
              return tieneAlgunPermiso(permisos);
            }
            return tienePermiso(item.permiso);
          });

          // Solo mostrar sección si tiene ítems visibles
          if (visibleItems.length === 0) return null;

          return (
            <SidebarSection
              key={section.id}
              title={section.title}
              icon={section.icon}
              items={visibleItems}
              defaultOpen={section.defaultOpen}
              isExpanded={isExpanded}
              currentPath={location.pathname}
              forceOpen={expandAll}
            />
          );
        })}
      </nav>

      {/* Toggle Sidebar - Abajo */}
      <button
        onClick={togglePin}
        className={styles.toggleBtn}
        aria-label={isPinned ? 'Colapsar sidebar' : 'Expandir sidebar'}
        title={isPinned ? 'Colapsar sidebar' : 'Expandir sidebar'}
      >
        <span style={{ transform: isPinned ? 'none' : 'scaleX(-1)', display: 'flex' }}>
          <PanelLeftClose size={20} />
        </span>
      </button>
    </aside>
  );
}
