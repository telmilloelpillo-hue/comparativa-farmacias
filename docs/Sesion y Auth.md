---
tags: [auth, backend, seguridad]
---

# Sesión y Auth

## Mecanismo
Contraseña única compartida entre las dos farmacias.
Flask session cookie firmada con `secret_key`.

```python
PASSWORD = "farmacias2026"
app.secret_key = 'farmacias_barris_zarzuelo_2026'

@app.before_request
def check_auth():
    if request.endpoint in ('login', 'static'):
        return
    if not session.get('authenticated'):
        return redirect(url_for('login'))
```

## Rutas públicas
- `GET/POST /login`
- `GET /static/*`

Todo lo demás requiere `session['authenticated'] = True`.

## Login
`POST /login` con `password` en form-data.
Si coincide → `session['authenticated'] = True` → redirect a `/`.
Si no → render login con error.

## Logout
`GET /logout` → `session.clear()` → redirect a `/login`.

## Seguridad
- No hay usuarios individuales ni roles
- Secret key hardcodeada (funcional, no crítico para uso interno)
- Para producción en Render, podría moverse a variable de entorno (ver [[Config y Deploy]])

## Relaciones
- [[App Flask]] — `check_auth()` hook global
- [[Config y Deploy]] — `SECRET_KEY` como mejora futura
- [[Frontend Templates]] — `login.html`
