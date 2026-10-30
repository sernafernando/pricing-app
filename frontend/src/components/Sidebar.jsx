import { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { usePermisos } from '../contexts/PermisosContext';
import { marcasPmAPI } from '../services/api';
import SidebarSection from './SidebarSection';
import { Package, ClipboardList, BarChart3, Settings, PanelLeftClose, PanelLeft, ChevronsDown, ChevronsUp, X, Search, Headset, Truck, Users, Ticket, FileText, Building2, Wallet } from 'lucide-react';
import styles from './Sidebar.module.css';

export default function Sidebar({ mobileOpen = false, onMobileClose }) {
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

  // Sub-PM delegation (sub-pm-scope-marcas): "Mis Sub-PMs" is data-scoped for
  // regular users — only shown to titulares of ≥1 (marca, categoria) pair,
  // discovered via GET /marcas-pm/mis-titularidades. Admins (admin.gestionar_pms)
  // always see it: they manage every pair, even with zero titularidades.
  const [tieneTitularidades, setTieneTitularidades] = useState(false);
  useEffect(() => {
    let cancelado = false;
    marcasPmAPI.misTitularidades()
      .then(({ data }) => {
        if (!cancelado) setTieneTitularidades((data?.total || 0) > 0);
      })
      .catch(() => {
        if (!cancelado) setTieneTitularidades(false);
      });
    return () => { cancelado = true; };
  }, []);

  // Persiste el estado de pin
  useEffect(() => {
    const value = isPinned.toString();
    localStorage.setItem('sidebarPinned', value);
    
    // Disparar custom event para sincronizar AppLayout en la misma tab
    window.dispatchEvent(new CustomEvent('sidebarChange', {
      detail: { key: 'sidebarPinned', value }
    }));
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
  // En mobile, siempre expandido cuando está abierto (no hay hover)
  const isExpanded = isPinned || isHovering || mobileOpen;

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
        { label: 'Items sin MLA', path: '/items-sin-mla', permiso: 'admin.ver_items_sin_mla' },
        { label: 'Prearmadas disponibles', path: '/prearmadas-disponibles', permiso: 'produccion.ver_prearmadas_stats' },
        { label: 'Sell in / Sell out', path: '/sell-in', permiso: 'sell_in.ver' },
      ],
    },
    {
      id: 'operaciones',
      title: 'Operaciones',
      icon: ClipboardList,
      defaultOpen: false,
      items: [
        { label: 'Preparación', path: '/pedidos-preparacion', permiso: 'ordenes.ver_preparacion' },
        { label: 'Producción', path: '/produccion', permiso: 'produccion.ver_combos' },
        { label: 'Prearmado', path: '/prearmado', permiso: 'produccion.prearmar_combos' },
        { label: 'Turbo', path: '/turbo-routing', permiso: 'ordenes.gestionar_turbo_routing' },
        { label: 'Clientes', path: '/clientes', permiso: 'clientes.ver' },
        { label: 'Configuración', path: '/config-operaciones', permiso: 'envios_flex.config' },
        { label: 'Reescribir ^LH', path: '/etiquetas/reescribir-lh', permiso: 'etiquetas.reescribir_lh' },
      ],
    },
    {
      id: 'consultas',
      title: 'Consultas',
      icon: Search,
      defaultOpen: false,
      items: [
        { label: 'Traza', path: '/traza', permiso: 'traza.ver' },
        { label: 'Seguimiento Envíos', path: '/seguimiento-envios', permiso: 'seguimiento_envios.ver' },
        { label: 'Cumpleaños', path: '/cumpleanos' },
      ],
    },
    {
      id: 'soporte',
      title: 'Soporte',
      icon: Headset,
      defaultOpen: false,
      items: [
        { label: 'RMA Seguimiento', path: '/rma', permiso: 'rma.ver' },
        { label: 'Control Depósito', path: '/control-deposito', permiso: 'rma.control_deposito' },
        { label: 'Reclamos ML', path: '/claims', permiso: 'rma.ver' },
        { label: 'Bot de Preguntas ML', path: '/ml-preguntas', permiso: 'ml_bot.ver' },
      ],
    },
    {
      id: 'reportes',
      title: 'Reportes',
      icon: BarChart3,
      defaultOpen: false,
      items: [
        { label: 'Ranking productos', path: '/consultas/ranking', permiso: 'consultas.ver_ranking,consultas.ver_mi_ranking', multiple: true },
        // ODD metricas-ml-tablero (2026-10-01): the new board took the plain
        // name; the old dashboard keeps its URL, relabelled.
        { label: 'Métricas ML', path: '/metricas-ml', permiso: 'ml_metricas.ver', badge: 'Nuevo' },
        { label: 'Gestión Full', path: '/gestion-full', permiso: 'productos.ver,ml_ops.ver', multiple: true, badge: 'Nuevo' },
