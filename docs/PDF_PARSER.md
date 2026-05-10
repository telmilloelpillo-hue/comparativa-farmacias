---
tags: [backend, pdf, debug, parser]
---

# PDF Parser — Guía de diagnóstico

## Estructura esperada de la tabla de estadísticas

```
Código | Descripción | Stock | S.mín | Año | Ene | Feb | … | Dic | Total
```

- **Código**: 6 chars alfanuméricos en x ≈ 20–60
- **Descripción**: texto en x ≈ 63–315
- **Stock / S.mín**: enteros en x ≈ 216 / 244 (pero varía por lab)
- **Año**: "20XX" en x ≈ 255–268 (pero varía por lab)
- **12 meses**: columnas equidistantes a la derecha del año
- **Total**: suma de meses, en x ≈ 318 (pero varía por lab)

Hay dos patrones de layout:
- **Patrón A**: código + datos en la misma fila (año, meses, total)
- **Patrón B**: código + descripción en una fila; datos en la fila siguiente

---

## Cómo funciona la detección de columnas (3 niveles)

### Nivel 1 — Cabecera de página (`_detect_columns`)
Busca palabras como "Ene", "Feb", "Mar"… en la cabecera de la tabla.
Si encuentra ≥ 6 meses, deduce todas las posiciones X desde ahí.
**Falla si:** el PDF usa "ENE", "ene.", "enero", o no tiene cabecera estándar.

Desde la versión actual: matching **case-insensitive** + strip de `.` → cubre "ENE", "Ene.", "ene".

### Nivel 2 — Inferencia desde datos (`_detect_columns_from_data`)
Escanea las primeras 10 filas con código de producto.
Busca el cluster "20XX" (año) como ancla → deriva el resto de posiciones por offset.
**Funciona sin cabecera.** Requiere ≥ 3 filas con año visible.

### Nivel 3 — Posiciones hardcoded (último recurso)
Valores calibrados para el formato de estadísticas original:
`STOCK_X=216, SMIN_X=244, YEAR_X0=255, YEAR_X1=268, TOTAL_X=318, MONTH_X=[357…794]`
**Peligroso si el PDF tiene layout diferente** — puede leer el año como mes.

---

## Síntomas y causas de errores

### Total = año + ventas reales (ej: 2129 en lugar de 103)
**Causa**: `_detect_columns` falla (nivel 1), `_detect_columns_from_data` falla (nivel 2),
y el fallback hardcodeado pone MONTH_X[0]=357 justo donde el PDF tiene la columna de año.
El año "2026" se lee como Enero → total = 2026 + ventas_reales.

**Fixes activos:**
- `_month_value` rechaza cualquier valor ≥ 1900 (el año nunca puede ser una venta mensual)
- Capa 3: si total ≥ 1500, elimina meses con valor ≥ 500

### S.365 muestra año en vez de stock (ej: 2028)
**Causa**: `extract_situation` lee la fecha de caducidad "07/2028" y el "2028" cae
en la franja X del stock (410–445 px).
**Fix**: `extract_situation` rechaza valores ≥ 1900 como stock.

### Descripción vacía
**Causas posibles:**
1. El código está en la última línea de un bloque multi-línea → el backward scan
   sube hasta 5 filas recogiendo descripciones sin código propio.
2. El PDF no tiene descripción en la hoja de ventas → se usa la descripción del
   informe de situación como fallback (`compare_products`).
3. **`extract_situation` no encuentra el producto** porque la columna Código está
   en una posición X distinta a los rangos hardcodeados.
   **Fix**: `_detect_situation_columns(words)` detecta las posiciones X de
   "Código", "Descripción", "Stock", "Caducidad" desde la cabecera de cada página.
   Si no encuentra cabecera, usa rangos amplios de fallback (código: x=30–110).

### Pedido = ~500 (ej: 506, 507, 528)
**Causa derivada**: si total_current = 2027, entonces
`pedido = ceil(2027/4) - stock = 507 - stock`. Fijando el total corrige el pedido.

---

## Diagnóstico de un PDF nuevo

```bash
# Desde la raíz del proyecto
venv/bin/python3 -c "
from pdf_parser import diagnose_pdf
diagnose_pdf('ruta/al/archivo.pdf')
"
```

La salida muestra por página:
- Si `_detect_columns` encontró cabecera (OK / None)
- Palabras del encabezado con sus posiciones X
- Primeros 5 productos con sus clusters de dígitos y posición X
- Si `_detect_columns_from_data` infirió las columnas correctamente

### Qué buscar en la salida

```
=== PÁGINA 1 ===
  _detect_columns → None (no header found)
  Header words: [('ENE', 354), ('FEB', 394), ('MAR', 434), ...]
  123456  yr=2026  clusters=[(1, 218), (0, 247), (2026, 354), (5, 394), ...]
  _detect_columns_from_data → OK
    year=[346.0-366.0]  months: ['394', '434', '474', ...]
```

- `_detect_columns → None` + header words con "ENE": el PDF usa mayúsculas (debería capturarse con el fix case-insensitive).
- Cluster `(2026, 354)` en x=354 y MONTH_X[0]=357: confirma el bug de año-como-mes.
- `_detect_columns_from_data → OK` con year=[346-366]: nivel 2 resuelve el problema.

---

## Labs probados

| Lab | Formato | Nivel usado | Notas |
|-----|---------|-------------|-------|
| Eucerin | Patrón A estándar | Nivel 1 | Funcionando |
| Pierre Fabre | Mayúsculas + year ~x354 | Nivel 2 | Fix case-insensitive + year-anchor |
| _(nuevo)_ | — | — | Ejecutar `diagnose_pdf` primero |

---

## Relaciones
- [[Feature Comparativa]] — flujo completo de comparativa
- [[PDF Processing]] — notas generales de extracción
- [[Scripts Análisis]] — uso de los datos extraídos
