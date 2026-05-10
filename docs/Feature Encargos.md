---
tags: [feature, encargos]
---

# Feature: Encargos

## Qué hace
Gestión de reservas/encargos de pacientes. Frontend JS puro,
sin persistencia en backend (los datos viven en el navegador).

## Rutas implicadas
- `GET /encargos` → sirve `encargos.html`

## Stack
- Sin base de datos
- Sin llamadas AJAX al backend (salvo la ruta estática)
- Toda la lógica en JS del template

## Relaciones
- [[App Flask]] — ruta simple, sin lógica backend
- [[Frontend Templates]] — `encargos.html`
- [[Sesion y Auth]] — protegida por `check_auth()`

## Notas
Al ser puro frontend, los encargos se pierden al cerrar la pestaña.
Si se necesita persistencia → añadir endpoint POST + fichero JSON o SQLite.
