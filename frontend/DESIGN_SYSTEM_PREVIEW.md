# 🎨 PREVIEW - Sistema de Diseño Tesla Completo

## ✅ Componentes Implementados

### 1. **StatCards** ✅
- Diseño Tesla con glassmorphism
- Hover con elevación
- Animaciones suaves
- **Ubicación:** Productos, Dashboards

### 2. **Tabla** ✅
- Bordes sutiles multicapa
- Headers con glassmorphism
- Zebra stripes
- Hover effects
- **Ubicación:** Productos, Tienda

### 3. **Botones** ✅ (RECIÉN AGREGADO)
- 6 variantes (primary, secondary, success, danger, ghost, outline)
- 3 tamaños (sm, base, lg)
- Estados (hover, active, disabled, loading)
- Icon buttons
- Close button especial
- **Ubicación:** Modales, Navbar, Tablas, Filtros

---

## 🎯 Sistema Completo Disponible

### Archivos CSS Globales:
```
frontend/src/styles/
├── design-tokens.css    ← Espaciado, tipografía, transitions
├── theme.css            ← Colores dark/light mode
├── buttons-tesla.css    ← Botones estandarizados ✨ NUEVO
├── table-tesla.css      ← Tablas mejoradas
└── components.css       ← Cards, modals base
```

### Componentes React:
```
frontend/src/components/
└── StatCard.jsx         ← Stat cards estandarizados
```

---

## 🔘 Preview de Botones

### Variantes:
```html
<!-- Primary -->
<button class="btn-tesla primary">Guardar</button>
<!-- Azul eléctrico con gradiente -->

<!-- Secondary -->
<button class="btn-tesla secondary">Cancelar</button>
<!-- Gris sutil con borde -->

<!-- Success -->
<button class="btn-tesla success">✓ Confirmar</button>
<!-- Verde con gradiente -->

<!-- Danger -->
<button class="btn-tesla danger">🗑️ Eliminar</button>
<!-- Rojo con gradiente -->

<!-- Ghost -->
<button class="btn-tesla ghost">Más opciones</button>
<!-- Transparente -->

<!-- Outline -->
<button class="btn-tesla outline">Exportar</button>
<!-- Solo borde -->
```

### Tamaños:
```html
<button class="btn-tesla primary sm">Pequeño (32px)</button>
<button class="btn-tesla primary">Normal (40px)</button>
<button class="btn-tesla primary lg">Grande (48px)</button>
```

### Estados:
```html
<button class="btn-tesla primary" disabled>Deshabilitado</button>
<button class="btn-tesla primary loading">Cargando...</button>
```

### Button Groups:
```html
<div class="btn-group-tesla right">
  <button class="btn-tesla secondary">Cancelar</button>
  <button class="btn-tesla primary">Guardar</button>
</div>
```

---

## 📊 Tabla Tesla Preview

```html
<div class="table-container-tesla">
  <table class="table-tesla striped">
    <thead class="table-tesla-head">
      <tr>
        <th class="sortable">Código</th>
        <th class="sortable sorted">Precio</th>
        <th>Stock</th>
      </tr>
    </thead>
    <tbody class="table-tesla-body">
      <tr>
        <td>001</td>
        <td class="numeric">$1,234.56</td>
        <td><span class="badge badge-success">En stock</span></td>
      </tr>
      <tr class="selected">
        <td>002</td>
        <td class="numeric">$5,678.90</td>
        <td><span class="badge badge-warning">Bajo</span></td>
      </tr>
    </tbody>
  </table>
</div>
```

---

## 🎴 StatCard Preview

```jsx
import StatCard from '../components/StatCard';

<StatCard
  label="📦 Total Productos"
  value="3,710"
  onClick={handleClick}
/>

<StatCard
  label="📊 Stock & Precio"
  subItems={[
    { label: 'Con Stock:', value: '1,046', color: 'green', onClick: handleFilter },
    { label: 'Sin Stock:', value: '135', color: 'red', onClick: handleFilter }
  ]}
/>
```

---

## 🎨 Design Tokens Disponibles

### Espaciado (escala 8px):
```css
var(--space-1)  /* 4px */
var(--space-2)  /* 8px */
var(--space-4)  /* 16px */
var(--space-6)  /* 24px */
var(--space-8)  /* 32px */

/* Aliases semánticos */
var(--spacing-xs)  /* 4px */
var(--spacing-sm)  /* 8px */
var(--spacing-md)  /* 16px */
var(--spacing-lg)  /* 24px */
var(--spacing-xl)  /* 32px */
```

### Tipografía:
```css
var(--font-xs)    /* 12px */
var(--font-sm)    /* 14px */
var(--font-base)  /* 16px */
var(--font-lg)    /* 18px */
var(--font-xl)    /* 20px */
var(--font-2xl)   /* 24px */

/* Weights */
var(--font-normal)    /* 400 */
var(--font-medium)    /* 500 */
var(--font-semibold)  /* 600 */
var(--font-bold)      /* 700 */
```

### Colores (ya definidos en theme.css):
```css
/* Backgrounds */
var(--bg-primary)
var(--bg-secondary)
var(--bg-tertiary)
var(--bg-hover)
var(--bg-active)

/* Text */
var(--text-primary)
var(--text-secondary)
var(--text-tertiary)
var(--text-inverse)

/* Brand */
var(--brand-primary)        /* #5c8cff dark, #3e6ae1 light */
var(--brand-primary-hover)
var(--brand-primary-light)

/* Semantic */
var(--success)  /* Verde */
var(--warning)  /* Naranja */
var(--error)    /* Rojo */
var(--info)     /* Azul */

/* Shadows */
var(--shadow-sm)
var(--shadow-md)
var(--shadow-lg)
var(--shadow-xl)
```

### Borders & Radius:
```css
var(--radius-base)  /* 4px */
var(--radius-md)    /* 6px */
var(--radius-lg)    /* 8px */
var(--radius-xl)    /* 12px */
var(--radius-full)  /* 9999px */

var(--border-1)  /* 1px */
var(--border-2)  /* 2px */
```

### Transitions:
```css
var(--duration-150)  /* 150ms */
var(--duration-200)  /* 200ms */
var(--duration-300)  /* 300ms */

var(--ease-in-out)  /* cubic-bezier(0.4, 0, 0.2, 1) */
```

---

## 🚀 Cómo Usar el Sistema

### 1. Importar clases globales:
Ya están importadas en `App.jsx`:
```jsx
import './styles/design-tokens.css';
import './styles/buttons-tesla.css';
import './styles/table-tesla.css';
import './styles/theme.css';
```

### 2. Usar en componentes:
```jsx
// Botón simple
<button className="btn-tesla primary">Guardar</button>

// Botón con loading
<button className="btn-tesla primary loading" disabled>
  Guardando...
</button>

// Tabla
<div className="table-container-tesla">
  <table className="table-tesla striped">
    ...
  </table>
</div>

// StatCard
import StatCard from '../components/StatCard';
<StatCard label="Total" value="123" color="blue" />
```

### 3. Usar tokens en CSS custom:
```css
.mi-componente {
  padding: var(--spacing-md);
  margin-bottom: var(--spacing-lg);
  font-size: var(--font-sm);
  color: var(--text-primary);
  background: var(--bg-primary);
  border-radius: var(--radius-lg);
  transition: all var(--duration-200) var(--ease-in-out);
}
```

---

## 📈 Estado Actual del Rediseño

| Componente | Estado | Notas |
|------------|--------|-------|
| **Design Tokens** | ✅ Completo | Espaciado, tipografía, colores |
| **Theme (Dark/Light)** | ✅ Completo | Negro puro + azul eléctrico |
| **StatCards** | ✅ Completo | Glassmorphism, animaciones |
| **Tabla** | ✅ Completo | Sticky header, zebra stripes, hover |
| **Botones** | ✅ Completo | 6 variantes, 3 tamaños, estados |
| **Modales** | ⏳ Pendiente | Siguiente en la lista |
| **Navbar** | ⏳ Pendiente | Refinamiento |
| **Inputs/Forms** | ⏳ Pendiente | Estandarización |

---

## 🎯 Próximos Pasos

1. **Modales** - Estandarizar estructura (header, body, footer)
2. **Navbar** - Refinamiento con botones nuevos
3. **Inputs** - Sistema de formularios consistente

---

**¿Querés que siga con los modales ahora?**
