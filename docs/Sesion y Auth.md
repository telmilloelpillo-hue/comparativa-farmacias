---
tags: [auth, backend, seguridad]
---

# Sesión y Auth

## Acceso público
La web y las rutas API se abren directamente, sin contraseña ni indicador
`authenticated`. Se retiraron el filtro global de login y las comprobaciones
de autenticación de las rutas individuales.

## Sesión de comparativa
La cookie de sesión de Flask sigue firmada con `secret_key`. Conserva el token
de la comparativa, el laboratorio y los datos de anotaciones para las descargas.
Esta sesión representa el trabajo activo en el navegador.

## Enlaces antiguos
- `GET/POST /login` redirige a `/`.
- `GET /logout` ejecuta `session.clear()` y vuelve a `/`.

Las plantillas no muestran botones de cerrar sesión. Las rutas de comparación,
facturas y encargos mantienen su validación habitual de archivos y parámetros.

## Comprobaciones
`tests/test_public_access.py` comprueba páginas y API con un cliente nuevo,
incluida la compatibilidad de `/login` y el reinicio de `/logout`.

## Relaciones
- [[App Flask]] — `check_auth()` hook global
- [[Config y Deploy]] — `SECRET_KEY` como mejora futura
- [[Frontend Templates]] — `login.html`
