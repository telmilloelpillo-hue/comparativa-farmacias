---
tags: [ia, prompts, facturas]
---

# Prompts IA

## Prompt: leer_factura
Enviado a [[IA Anthropic]] (`claude-haiku-4-5-20251001`, max 8192 tokens).

### Cuando se usa texto pdfplumber
```
"A continuación tienes el texto extraído de una factura o albarán de farmacia española.
El texto fue extraído automáticamente de un PDF, por lo que puede haber saltos de línea
en medio de descripciones.

Extrae los datos de las líneas de producto y devuelve ÚNICAMENTE un objeto JSON..."
+ json_schema
+ "\n\nTEXTO EXTRAÍDO DEL PDF:\n" + extracted_text
```

### Cuando se adjunta PDF binario (fallback)
```
"Analiza esta factura o albarán de farmacia española y extrae los datos..."
+ json_schema
```

### Reglas clave en el schema
```
- Incluye SOLO líneas con precio unitario > 0
- NO incluyas: subtotales, descuentos globales, portes, cuotas IVA
- precio_neto_unitario: con descuentos, SIN IVA
- iva_porcentaje: 4, 5, 10 o 21
- cada línea de producto es INDEPENDIENTE; no mezcles descripciones entre líneas
- Si descripción ocupa dos renglones, únelos en un solo campo 'nombre'
```

## Prompt: /pregunta
```
"Eres un experto en gestión de stock de farmacia. Responde de forma concisa y directa
(máximo 4 frases) basándote únicamente en los datos facilitados."

Contexto: stock, ventas año actual/anterior, consumo medio, tendencia, días cobertura × 2 farmacias
Pregunta: lo que escribe el usuario
```

## Notas de ingeniería
- Haiku devuelve a veces markdown fences (` ```json `) → stripping en backend
- El JSON schema se manda como string de Python (no como JSON Schema formal)
- `max_tokens=8192` en facturas → facturas largas (50+ líneas) no se truncan
- `max_tokens=350` en preguntas → respuesta corta, coste mínimo

## Problema actual
Descripciones multi-línea en PDFs tabulares pueden mezclarse.
La regla explícita en el prompt ayuda pero no lo resuelve completamente.
Ver [[PDF Processing]] para mejoras en el pipeline de extracción.

## Relaciones
- [[IA Anthropic]] — modelo y cliente
- [[Feature Facturas]] — usa leer_factura
- [[PDF Processing]] — su output alimenta estos prompts
- [[Costes Tokens]] — cada prompt tiene un coste estimado
