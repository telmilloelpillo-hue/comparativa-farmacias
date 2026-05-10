---
tags: [feature, facturas, ia]
---

# Feature: Facturas

## Qué hace
Sube una factura o albarán (PDF o imagen) → [[IA Anthropic]] extrae las líneas de producto →
tabla editable donde se calcula el PVP según proveedor → exporta CSV.

## Flujo
```
Usuario sube archivo (PDF/JPG/PNG)
  → POST /leer_factura
  → pdfplumber extrae tablas/texto (ver [[PDF Processing]])
  → Si texto OK → Claude Haiku recibe texto plano
  → Si no → Claude recibe PDF binario como 'document'
  → JSON con: proveedor, numero_factura, fecha, lineas[]
  → facturas.html renderiza tabla editable
  → Usuario ajusta IVA y PVP manual si necesario
  → "Exportar CSV" → descarga con pvpManual o calculado
```

## Datos extraídos por línea
```json
{
  "cn": "123456",
  "nombre": "OMEPRAZOL 20MG 28 CAPS",
  "cantidad": 10,
  "precio_neto_unitario": 2.15,
  "precio_neto_total": 21.50,
  "iva_porcentaje": 4,
  "recargo": 0
}
```

## Cálculo PVP
`PVP = precio_neto_unitario × factor`
Factores en [[Datos Proveedores]]. El usuario puede sobrescribir (campo azul = manual).
Ver [[Prompts IA]] para el prompt exacto que manda a Claude.

## Persistencia UI
sessionStorage guarda el archivo y los resultados. Al recargar, se restaura sin pedir de nuevo.
`SESSION_KEY = 'factura_session'` en [[Frontend Templates]].

## Panel preview
Preview del PDF/imagen con zoom + pan independiente de la tabla.
Pinch zoom con 10% de sensibilidad (damping para precisión).
Handle de resize entre tabla y preview.

## Problema conocido
PDFs con descripciones multi-línea a veces mezclan texto entre filas.
Mejora en curso: pdfplumber con `layout=True` + prompt con reglas explícitas.
Ver [[PDF Processing]] y [[Prompts IA]].
