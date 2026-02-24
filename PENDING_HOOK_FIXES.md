# Pre-commit Hook - Violaciones Pre-existentes a Fixear

> Creado: 2026-02-24
> Contexto: El pre-commit hook (Gentleman Guardian Angel v2.6.1) falla por violaciones que ya estaban en el código antes de nuestros cambios. Venimos usando `--no-verify` para bypasear.

---

## backend/app/api/endpoints/productos.py

### 1. Bare `except:` clauses (silencian errores)
- **Lineas**: ~1294, ~1367, ~1613, ~1639, ~1827, ~3248
- **Problema**: `except:` o `except Exception: pass` sin especificar tipo de excepcion
- **Fix**: Reemplazar con excepciones especificas (`except ValueError:`, `except HTTPException:`, etc.) o al menos loggear el error

### 2. Codigo muerto / unreachable
- **Linea**: ~589 - Bloque `if False:` con codigo inalcanzable
- **Fix**: Eliminar el bloque o agregar el parametro que falta

### 3. Imports duplicados dentro de funciones
- **Lineas**: ~1878, ~1997 - `from datetime import timedelta` importado multiples veces
- **Fix**: Mover al top-level del archivo

### 4. Magic numbers hardcodeados (pricelist IDs)
- **Lineas**: ~2680, ~2920 - IDs como `4`, `12`, `17`, `18`, `19`, `20`, `21`, `23`
- **Fix**: Extraer a constantes o config

---

## frontend/src/pages/Productos.jsx

### 1. Emojis usados como iconos
- **Lineas**: Por todo el archivo - emojis en JSX, labels, botones
- **Fix**: Reemplazar con componentes de `lucide-react` (ver tabla en `frontend/AGENTS.md`)

### 2. `alert()` / `confirm()` nativos
- **Fix**: Reemplazar con modales Tesla Design System

### 3. Catch blocks vacios
- **Lineas**: ~83, ~462, ~1016, ~1174, ~1195, ~1260, ~1396, ~1485, ~1557, ~1591
- **Fix**: Agregar manejo de error real o al menos `console.error` con contexto

### 4. Constante `FILTER_VALUES` sin usar (linea ~32)
- **Fix**: Usarla en todos los lugares donde hay magic strings de filtros (`'con_stock'`, `'sin_stock'`, etc.) o eliminarla

### 5. Inline styles excesivos
- **Lineas**: ~3216-3300 (color picker, markup display)
- **Fix**: Mover a CSS Modules

### 6. 60+ useState hooks
- **Fix**: Evaluar consolidar filtros relacionados en un objeto o usar `useReducer`

---

## Estrategia Sugerida

1. **Quick wins primero**: bare excepts, imports duplicados, codigo muerto, constante sin usar
2. **Emojis -> lucide-react**: hacer en un commit aparte (toca muchas lineas)
3. **Inline styles -> CSS Modules**: commit aparte
4. **Refactor useState**: evaluar si vale la pena el riesgo (archivo grande, muchas dependencias)
