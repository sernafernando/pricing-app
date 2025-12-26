# 📘 Guía de Migración al Nuevo Sistema de Diseño

## ✅ Fase 1: COMPLETADA

- ✅ `design-tokens.css` creado e importado
- ✅ `components.css` creado e importado
- ✅ Verificación: Tienda.css NO es duplicado (tiene lógica Gremio)
- ✅ Componente ejemplo: `StatCard.jsx` creado

---

## 🎯 Cómo Usar el Nuevo Sistema

### 1. **Stat Cards** (Ejemplo Práctico)

**ANTES (custom CSS):**
```jsx
// Productos.jsx
<div className="stat-card clickable" onClick={handleClick}>
  <div className="stat-label">Productos Activos</div>
  <div className="stat-value blue">1,234</div>
</div>
```

**DESPUÉS (usando StatCard):**
```jsx
// Importar componente
import StatCard from '../components/StatCard';

// Usar con props
<StatCard 
  label="Productos Activos"
  value="1,234"
  color="blue"
  onClick={handleClick}
/>

// Con sub-items (markup negativo)
<StatCard 
  label="Markup Negativo"
  color="red"
  subItems={[
    { label: 'ML', value: '15', color: 'red', onClick: handleMLClick },
    { label: 'Web', value: '8', color: 'orange', onClick: handleWebClick },
  ]}
/>
```

---

### 2. **Botones** (Sistema Global)

**ANTES (CSS custom en cada archivo):**
```jsx
<button className={styles.botonCalcular}>Calcular</button>
<button className="btn-clear">Limpiar</button>
<button className="btn-apply">Aplicar</button>
```

**DESPUÉS (clases globales):**
```jsx
<button className="btn btn-primary">Calcular</button>
<button className="btn btn-secondary btn-sm">Limpiar</button>
<button className="btn btn-success btn-lg">Aplicar</button>

{/* Variantes disponibles: */}
btn-primary     // Azul eléctrico (acción principal)
btn-secondary   // Gris (acción secundaria)
btn-success     // Verde (guardar, confirmar)
btn-danger      // Rojo (eliminar, cancelar)
btn-ghost       // Transparente (acciones sutiles)
btn-outline     // Borde sin relleno

{/* Tamaños: */}
btn-sm          // 32px altura
(default)       // 40px altura
btn-lg          // 48px altura
```

---

### 3. **Modales** (Estructura Estandarizada)

**ANTES (cada modal con su estructura):**
```jsx
// PricingModal.module.css - 250 líneas custom
<div className={styles.modalOverlay}>
  <div className={styles.modal}>
    {/* estructura custom */}
  </div>
</div>
```

**DESPUÉS (estructura global):**
```jsx
<div className="modal-overlay">
  <div className="modal">
    <div className="modal-header">
      <h2 className="modal-title">Calcular Precio</h2>
      <button className="modal-close" onClick={onClose}>×</button>
    </div>
    
    <div className="modal-body">
      {/* Tu contenido aquí */}
    </div>
    
    <div className="modal-footer">
      <button className="btn btn-secondary" onClick={onClose}>
        Cancelar
      </button>
      <button className="btn btn-primary" onClick={onSave}>
        Guardar
      </button>
    </div>
  </div>
</div>
```

**Beneficio:** Todos los modales se ven consistentes, sin escribir CSS custom.

---

### 4. **Inputs** (Formularios Estandarizados)

**ANTES:**
```jsx
<input 
  type="text" 
  className={styles.customInput}
  style={{ padding: '10px 14px', fontSize: '14px' }}
/>
```

**DESPUÉS:**
```jsx
<input type="text" className="input" placeholder="Buscar..." />
<input type="number" className="input input-sm" />
<input type="email" className="input input-error" /> {/* Con error */}
```

---

### 5. **Cards** (Tarjetas)

**ANTES:**
```css
.mi-card {
  background: var(--bg-primary);
  padding: 20px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
```

**DESPUÉS:**
```jsx
<div className="card">
  <div className="card-header">
    <h3 className="card-title">Título</h3>
  </div>
  <div className="card-body">
    Contenido aquí
  </div>
</div>

{/* Card clickeable con hover */}
<div className="card card-hover" onClick={handleClick}>
  Contenido
</div>
```

---

### 6. **Tablas** (Sistema Único)

**DESPUÉS:**
```jsx
<div className="table-container">
  <table className="table table-striped">
    <thead>
      <tr>
        <th>Producto</th>
        <th>Precio</th>
        <th>Stock</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Item 1</td>
        <td>$1,234</td>
        <td>10</td>
      </tr>
    </tbody>
  </table>
</div>
```

---

### 7. **Badges** (Insignias)

```jsx
<span className="badge badge-primary">Activo</span>
<span className="badge badge-success">Publicado</span>
<span className="badge badge-warning">Pendiente</span>
<span className="badge badge-danger">Pausado</span>
<span className="badge badge-neutral">Borrador</span>
```

---

### 8. **Utility Classes** (Espaciado, Tipografía)

```jsx
{/* Padding */}
<div className="p-4">Padding 16px</div>
<div className="p-6">Padding 24px</div>

{/* Margin */}
<div className="m-2">Margin 8px</div>
<div className="m-4">Margin 16px</div>

{/* Tipografía */}
<span className="text-xs">Extra pequeño (12px)</span>
<span className="text-sm">Pequeño (14px)</span>
<span className="text-base">Normal (16px)</span>
<span className="text-lg">Grande (18px)</span>
<span className="text-xl">Extra grande (20px)</span>

{/* Font weights */}
<span className="font-normal">Normal (400)</span>
<span className="font-medium">Medium (500)</span>
<span className="font-semibold">Semi-bold (600)</span>
<span className="font-bold">Bold (700)</span>

{/* Border radius */}
<div className="rounded">4px radius</div>
<div className="rounded-lg">8px radius</div>
<div className="rounded-full">Completamente redondo</div>

{/* Shadows */}
<div className="shadow-sm">Sombra pequeña</div>
<div className="shadow-md">Sombra media</div>
<div className="shadow-lg">Sombra grande</div>
```

---

### 9. **Design Tokens en CSS Custom**

Si necesitás crear CSS custom, usá los tokens:

```css
.mi-componente-custom {
  /* Espaciado */
  padding: var(--spacing-md);  /* 16px */
  gap: var(--spacing-sm);      /* 8px */
  margin-bottom: var(--space-6); /* 24px */
  
  /* Tipografía */
  font-size: var(--font-sm);   /* 14px */
  font-weight: var(--font-medium); /* 500 */
  
  /* Colores (ya existen en theme.css) */
  background: var(--bg-primary);
  color: var(--text-primary);
  border: var(--border-1) solid var(--border-primary);
  
  /* Border radius */
  border-radius: var(--radius-base); /* 4px */
  
  /* Shadows */
  box-shadow: var(--shadow-sm);
  
  /* Transitions */
  transition: all var(--duration-200) var(--ease-in-out);
}
```

---

## 🔄 Plan de Migración Gradual

### ✅ Ya hecho:
1. Sistema de tokens creado
2. Componentes base definidos
3. Imports agregados a `App.jsx`
4. Componente ejemplo `StatCard.jsx`

### 📋 Siguiente (opcional, cuando quieras):
1. Migrar stat cards de Productos.jsx a usar `<StatCard />`
2. Refactorizar un modal (ej: PricingModal) a estructura global
3. Reemplazar botones custom por clases globales
4. Consolidar inputs de formularios

**NO hay apuro. Todo funciona como está.**

---

## 🚨 Reglas Importantes

1. **NO borrar CSS viejo hasta estar seguro** que el nuevo funciona
2. **Migrar de a poco** (componente por componente)
3. **Testear visualmente** después de cada cambio
4. **Los estilos actuales siguen funcionando** (no hay breaking changes)

---

## 🎨 Ejemplo Real: Stat Card de Productos Activos

### ANTES (en Productos.jsx):
```jsx
<div className="stat-card clickable" onClick={() => setShowActivos(true)}>
  <div className="stat-label">Productos Activos</div>
  <div className="stat-value blue">{stats.activos}</div>
</div>
```

```css
/* Productos.css */
.stat-card {
  flex: 0 1 240px;
  min-width: 200px;
  background: var(--bg-primary);
  padding: 20px;
  border-radius: 8px;
  box-shadow: var(--shadow-sm);
  text-align: center;
  transition: all 0.2s ease;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.stat-card.clickable { cursor: pointer; }
.stat-card.clickable:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.stat-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-value.blue { color: var(--brand-primary); }
```

**Total: ~50 líneas CSS custom**

---

### DESPUÉS (usando StatCard):
```jsx
import StatCard from '../components/StatCard';

<StatCard 
  label="Productos Activos"
  value={stats.activos}
  color="blue"
  onClick={() => setShowActivos(true)}
/>
```

**Total: 0 líneas CSS custom** ✨

---

## 🎯 Beneficios Reales

1. **Menos código:** -80% líneas CSS custom
2. **Consistencia visual:** Todos los componentes se ven iguales
3. **Desarrollo más rápido:** Copy-paste del sistema, no reinventar
4. **Mantenimiento fácil:** Cambio 1 archivo, actualiza toda la app
5. **Onboarding rápido:** Nuevos devs usan componentes documentados

---

¿Querés que migre algún componente específico como ejemplo? Decime cuál y lo hago.
