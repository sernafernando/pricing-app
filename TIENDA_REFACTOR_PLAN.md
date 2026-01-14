# PLAN DE REFACTOR: Tienda.jsx

Basado en los fixes aplicados en Productos.jsx (commits dc820ac, dbff94c, 843ddac, 9ec79dc, 21705bf, ea62297)

## FASE 1: Bugs Críticos (PRIORIDAD ALTA)

### 1. Fix function name
- Cambiar `export default function Productos()` → `export default function Tienda()`

### 2. Fix API_URL
- Buscar hardcoded API URLs
- Agregar: `const API_URL = import.meta.env.VITE_API_URL || 'https://pricing.gaussonline.com.ar';`
- Reemplazar todas las URLs hardcoded con `${API_URL}`

### 3. Fix CSS imports
- Eliminar: `import styles from './Productos.module.css';`
- Eliminar: `import dashboardStyles from './DashboardMetricasML.module.css';`
- Verificar que use solo `./Tienda.css`

### 4. Fix scroll (3 cambios):
```javascript
// A. Cambiar scrollIntoView de smooth a auto
filaActiva.scrollIntoView({
  behavior: 'auto',  // NO smooth
  block: 'nearest',
  inline: 'nearest'
});

// B. En Tienda.css agregar:
.table-tesla-body tr {
  scroll-margin-top: 60px;
}

// C. En table-tesla.css agregar (si no existe):
.table-tesla-body::after {
  content: '';
  display: table-row;
  height: 200px;
}
```

### 5. Fix toggle functions (R y O keys)
- **toggleRebateRapido**: Agregar lógica para desactivar cuando ya está activo
- **toggleOutOfCardsRapido**: Convertir en toggle real (activar/desactivar)
- **handleKeyDown**: Hacer async y agregar lógica especial para R y O cuando editando

### 6. Fix onClick handlers con && roto
- Buscar: `onClick={() => puedeEditar && setEditando(...) && setTemp(...)}`
- Cambiar a:
```javascript
onClick={() => {
  if (puedeEditar) {
    setEditando(...);
    setTemp(...);
  }
}}
```

## FASE 2: Limpieza de Código (PRIORIDAD MEDIA)

### 7. Eliminar console statements (34)
```bash
rg "console\.(log|error|warn)" frontend/src/pages/Tienda.jsx
# Eliminar todos
```

### 8. Reemplazar alert() con showToast() (12)
```bash
rg "alert\(" frontend/src/pages/Tienda.jsx
# Cambiar: alert('mensaje') → showToast('mensaje', 'error')
```

### 9. Agregar error handling a catch blocks vacíos (3+)
```javascript
} catch (error) {
  
}
// Cambiar a:
} catch (error) {
  showToast('Error al [acción]', 'error');
}
```

### 10. Fix setTimeout cleanup
```javascript
// Agregar useRef
const toastTimeoutRef = useRef(null);

// En showToast:
if (toastTimeoutRef.current) {
  clearTimeout(toastTimeoutRef.current);
}
toastTimeoutRef.current = setTimeout(...);

// Agregar useEffect cleanup:
useEffect(() => {
  return () => {
    if (toastTimeoutRef.current) {
      clearTimeout(toastTimeoutRef.current);
    }
  };
}, []);
```

## FASE 3: Design Tokens & Accesibilidad (PRIORIDAD MEDIA)

### 11. Crear variables CSS para colores
En Tienda.css:
```css
:root {
  --product-urgent-bg: #fee2e2;
  --product-urgent-text: #991b1b;
  /* ... copiar las 14 variables de Productos.css */
}
```

### 12. Reemplazar hardcoded colors (46)
- COLORES_DISPONIBLES: usar var(--product-*)
- getMarkupColor(): usar var(--error/warning/success)
- Borders: var(--border-primary)
- Backgrounds: var(--bg-primary/secondary)

### 13. Agregar aria-labels (0 → 30+)
- Botones icon-only: 🔍📋⚙️🎨✓✗
- Color picker buttons
- Checkboxes en filtros

### 14. Validación de inputs
```javascript
const isValidNumericInput = (value) => {
  if (value === '' || value === null || value === undefined) return true;
  const num = parseFloat(value);
  return !isNaN(num) && isFinite(num);
};

// En guardarPrecio:
if (!isValidNumericInput(precioNormalizado) || precioNormalizado <= 0) {
  showToast('El precio debe ser un número válido mayor a 0', 'error');
  return;
}
```

### 15. Definir constantes para magic strings
```javascript
const FILTER_VALUES = {
  TODOS: 'todos',
  CON_STOCK: 'con_stock',
  SIN_STOCK: 'sin_stock',
  // ... etc
};
```

## COMANDOS ÚTILES PARA VERIFICAR

```bash
# Contar problemas restantes
rg "console\." frontend/src/pages/Tienda.jsx | wc -l
rg "alert\(" frontend/src/pages/Tienda.jsx | wc -l
rg "#[0-9a-fA-F]{6}" frontend/src/pages/Tienda.jsx | wc -l
rg "aria-label=" frontend/src/pages/Tienda.jsx | wc -l

# Buscar bugs específicos
rg "scrollIntoView.*smooth" frontend/src/pages/Tienda.jsx
rg "setEdita.*&&.*setTemp" frontend/src/pages/Tienda.jsx
rg "} catch.*{$" frontend/src/pages/Tienda.jsx -A 2 | rg "^\s*}$"
```

## ORDEN RECOMENDADO DE EJECUCIÓN

1. Function name + API_URL + CSS imports (5 min)
2. Scroll fixes (10 min)
3. Toggle R/O keys (15 min)
4. onClick handlers rotos (10 min)
5. Console/alert/catch blocks (20 min)
6. setTimeout cleanup (5 min)
7. Design tokens (30 min)
8. Aria-labels (20 min)
9. Validación + constantes (15 min)

**TOTAL ESTIMADO: 2 horas**

## COMMITS SUGERIDOS

```
fix: corregir function name y imports en Tienda.jsx
fix: agregar VITE_API_URL y arreglar scroll en Tienda.jsx
fix: toggle R/O keys y onClick handlers rotos en Tienda.jsx
refactor: eliminar console/alert y agregar error handling en Tienda.jsx
refactor: design tokens y accesibilidad en Tienda.jsx
```
