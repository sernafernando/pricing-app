# 🔘 BUTTONS TESLA - Guía de Uso

## ✅ Sistema de Botones Implementado

### 🎨 Variantes Disponibles

#### **Primary** - Acción principal
```jsx
<button className="btn-tesla primary">Guardar</button>
<button className="btn-tesla primary">Calcular Precio</button>
```
**Visual:** Gradiente azul eléctrico, sombra al hover, se eleva

---

#### **Secondary** - Acción secundaria
```jsx
<button className="btn-tesla secondary">Cancelar</button>
<button className="btn-tesla secondary">Volver</button>
```
**Visual:** Fondo gris, borde sutil, elevación mínima

---

#### **Success** - Confirmar, guardar exitoso
```jsx
<button className="btn-tesla success">✓ Confirmar</button>
<button className="btn-tesla success">Guardar Cambios</button>
```
**Visual:** Gradiente verde, sombra verde al hover

---

#### **Danger** - Eliminar, acción crítica
```jsx
<button className="btn-tesla danger">🗑️ Eliminar</button>
<button className="btn-tesla danger">Borrar Todo</button>
```
**Visual:** Gradiente rojo, sombra roja al hover

---

#### **Ghost** - Acción sutil
```jsx
<button className="btn-tesla ghost">Más Opciones</button>
<button className="btn-tesla ghost">Ver Detalle</button>
```
**Visual:** Transparente, solo hover con fondo

---

#### **Outline** - Borde sin relleno
```jsx
<button className="btn-tesla outline">Exportar</button>
<button className="btn-tesla outline-success">Aprobar</button>
<button className="btn-tesla outline-danger">Rechazar</button>
```
**Visual:** Borde de color, fondo transparente

---

### 📏 Tamaños

```jsx
<button className="btn-tesla primary sm">Pequeño</button>
<button className="btn-tesla primary">Normal (base)</button>
<button className="btn-tesla primary lg">Grande</button>
```

**Alturas:**
- `sm` = 32px
- `base` = 40px (default)
- `lg` = 48px

---

### 🔲 Full Width

```jsx
<button className="btn-tesla primary full">Botón Ancho Completo</button>
```

---

### 🎭 Estados

#### Disabled
```jsx
<button className="btn-tesla primary" disabled>No Disponible</button>
<button className="btn-tesla primary disabled">Deshabilitado</button>
```

#### Loading
```jsx
<button className="btn-tesla primary loading">Guardando...</button>
```
**Visual:** Spinner animado, texto transparente

---

### 🔘 Icon Buttons (solo icono)

```jsx
<button className="btn-tesla primary icon-only">✏️</button>
<button className="btn-tesla danger icon-only">🗑️</button>
<button className="btn-tesla ghost icon-only sm">⋮</button>
```

---

### 👥 Button Groups

```jsx
<div className="btn-group-tesla">
  <button className="btn-tesla secondary">Cancelar</button>
  <button className="btn-tesla primary">Guardar</button>
</div>

{/* Alineados a la derecha */}
<div className="btn-group-tesla right">
  <button className="btn-tesla secondary">Cancelar</button>
  <button className="btn-tesla primary">Guardar</button>
</div>

{/* Espacio entre botones */}
<div className="btn-group-tesla between">
  <button className="btn-tesla danger">Eliminar</button>
  <button className="btn-tesla primary">Guardar</button>
</div>

{/* Compacto */}
<div className="btn-group-tesla compact">
  <button className="btn-tesla ghost sm">Editar</button>
  <button className="btn-tesla ghost sm">Copiar</button>
  <button className="btn-tesla ghost sm">Eliminar</button>
</div>
```

---

### ✕ Close Button (para modales)

```jsx
<button className="btn-close-tesla" onClick={onClose}>×</button>
```
**Visual:** Rota 90° al hover, top-right absolute position

---

## 🔄 Migración de Botones Existentes

### ANTES (CSS Modules):
```jsx
// ExportModal.jsx
<button className={`${styles.button} ${styles.buttonPrimary}`}>
  Exportar
</button>
<button className={`${styles.button} ${styles.buttonSecondary}`}>
  Cancelar
</button>
```

### DESPUÉS (Sistema Tesla):
```jsx
<button className="btn-tesla primary">
  Exportar
</button>
<button className="btn-tesla secondary">
  Cancelar
</button>
```

---

### ANTES (clases globales):
```jsx
// ModalCalculadora.jsx
<button className="btn-primary">Guardar</button>
<button className="btn-secondary">Cancelar</button>
<button className="close-btn">✕</button>
```

### DESPUÉS:
```jsx
<button className="btn-tesla primary">Guardar</button>
<button className="btn-tesla secondary">Cancelar</button>
<button className="btn-close-tesla">×</button>
```

---

## 🎯 Ejemplos Reales de la App

### Footer de Modal (ExportModal, PricingModal, etc.)
```jsx
<div className="btn-group-tesla right">
  <button 
    className="btn-tesla secondary" 
    onClick={onClose}
    disabled={exportando}
  >
    Cancelar
  </button>
  <button 
    className="btn-tesla primary" 
    onClick={handleExport}
    disabled={exportando}
  >
    {exportando ? 'Exportando...' : 'Exportar'}
  </button>
</div>
```

### Navbar Actions
```jsx
<button className="btn-tesla ghost sm">
  Sincronizar
</button>
<button className="btn-tesla outline sm">
  Exportar XLS
</button>
```

### Tabla Actions
```jsx
<button className="btn-tesla ghost icon-only sm" title="Editar">
  ✏️
</button>
<button className="btn-tesla ghost icon-only sm" title="Info">
  ℹ️
</button>
<button className="btn-tesla ghost icon-only sm" title="Eliminar">
  🗑️
</button>
```

### Filtros
```jsx
<div className="btn-group-tesla">
  <button className="btn-tesla secondary sm">
    Limpiar Filtros
  </button>
  <button className="btn-tesla primary sm">
    Aplicar
  </button>
</div>
```

---

## 🎨 Características Premium

✅ **Hover Lift Effect** - Se elevan al pasar mouse
✅ **Gradientes sutiles** - Primary, Success, Danger
✅ **Sombras con color** - Azul/verde/rojo según variante
✅ **Loading state** - Spinner animado integrado
✅ **Close button** - Rotación 90° al hover
✅ **Responsive** - Se adapta a mobile
✅ **Dark mode** - Ajustes automáticos
✅ **Icon support** - Iconos antes/después del texto
✅ **Badge support** - Números/estados dentro del botón

---

## 🚀 Próximos Pasos

### 1. Migrar modales principales:
- [ ] PricingModal
- [ ] ModalCalculadora
- [ ] ExportModal
- [ ] CalcularWebModal
- [ ] ModalInfoProducto

### 2. Migrar páginas:
- [ ] Productos (action buttons)
- [ ] Tienda
- [ ] Admin
- [ ] Navbar

### 3. Crear componente React (opcional):
```jsx
// components/Button.jsx
export default function Button({ 
  variant = 'primary', 
  size = 'base',
  loading,
  icon,
  children,
  ...props 
}) {
  return (
    <button 
      className={`btn-tesla ${variant} ${size} ${loading ? 'loading' : ''}`}
      {...props}
    >
      {icon && <span className="icon-left">{icon}</span>}
      {children}
    </button>
  );
}

// Uso:
<Button variant="primary" onClick={handleSave}>Guardar</Button>
<Button variant="danger" size="sm" loading>Eliminando...</Button>
```

---

## 📊 Comparativa Visual

### ANTES:
```
[Cancelar] [Guardar]
   ↑          ↑
 Gris      Azul simple
Sin sombra  Sin hover effect
```

### AHORA:
```
[Cancelar] [💾 Guardar]
   ↑          ↑
 Elevación  Gradiente + sombra azul
 al hover   Se eleva al hover
            Rotación sutil
```

---

**Build exitoso ✅** - Sistema de botones listo para usar.

**¿Querés que migre algún modal/componente específico para que veas el resultado?**
