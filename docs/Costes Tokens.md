---
tags: [ia, costes, economia]
---

# Costes Tokens

## Modelo elegido
`claude-haiku-4-5-20251001` — el más barato de la familia Claude 4.

## Tarifas aproximadas (Haiku 4.5)
| | Precio |
|---|---|
| Input | $0.80 / M tokens |
| Output | $4.00 / M tokens |

## Coste por operación estimado

### leer_factura (factura típica ~20 líneas)
- Input: ~1.500–3.000 tokens (texto pdfplumber + prompt + schema)
- Output: ~600–800 tokens (JSON con 20 líneas)
- **Coste ≈ $0.005–0.008 por factura** (menos de 1 céntimo)

### /pregunta (stock de un producto)
- Input: ~400–600 tokens (contexto producto + pregunta)
- Output: ~80–150 tokens (4 frases)
- **Coste ≈ $0.001 por pregunta** (fracción de céntimo)

## Por qué Haiku y no Opus/Sonnet
- Facturas son extracción estructurada, no razonamiento complejo → Haiku suficiente
- Preguntas de stock son cortas y factuales → Haiku suficiente
- Ahorrar ~10–20× vs Opus para el mismo resultado práctico

## Antes
Se usó `claude-opus-4-6` brevemente → mismo resultado, mucho más caro.
Cambiado a Haiku tras confirmación del usuario.

## Relaciones
- [[IA Anthropic]] — configuración del modelo
- [[Prompts IA]] — tamaño de prompts determina coste
- [[Feature Facturas]] — operación más costosa
- [[Config y Deploy]] — la API key en `.env` / Render env
