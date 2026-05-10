---
tags: [datos, config, facturas]
---

# Datos Proveedores

## labs.json
Contiene los laboratorios conocidos para la [[Feature Comparativa]].
Cada entrada: `{ "nombre": "...", "slug": "...", "keywords": [...] }`
`detect_lab()` en [[PDF Processing]] busca keywords en el header del PDF.

## _CONFIG_PROVEEDORES (app.py)
Usado en [[Feature Facturas]] para calcular PVP.

```python
_CONFIG_PROVEEDORES = {
    'hefame_bida': {
        'nombre': 'Hefame / BIDA',
        'factores': {
            'iva21':        {'etiqueta': 'IVA 21%',           'factor': 1.68},
            'iva10_diet':   {'etiqueta': 'IVA 10% Dietético', 'factor': 1.3585},
            'iva10_nodiet': {'etiqueta': 'IVA 10% No Diet.',  'factor': 1.48},
            'iva5':         {'etiqueta': 'IVA 5%',            'factor': 1.3063},
            'veterinaria':  {'etiqueta': 'VET',               'factor': 1.48},
        },
    },
    'laboratorio': {
        'nombre': 'Laboratorio (directo)',
        'factores': {
            'iva21':        {'factor': 1.8},
            'iva10_diet':   {'factor': 1.3925},
            'iva10_nodiet': {'factor': 1.59},
            'iva4':         {'factor': 1.3933},
            'veterinaria':  {'factor': 0},
        },
    },
}
```

## Fórmula PVP
`PVP = precio_neto_unitario × factor[proveedor][tipo_iva]`

Tipo de IVA determinado por el campo `iva_porcentaje` extraído por la IA.
El usuario puede sobrescribir PVP (campo `pvpManual` en linea).

## Añadir nuevo proveedor
1. Añadir entrada en `_CONFIG_PROVEEDORES` en `app.py`
2. El select de proveedor en [[Frontend Templates]] (`facturas.html`) se genera dinámico desde este dict

## Relaciones
- [[Feature Facturas]] — usa factores para calcular PVP
- [[IA Anthropic]] — extrae iva_porcentaje y precio_neto_unitario
- [[Costes Tokens]] — coste es independiente del proveedor
