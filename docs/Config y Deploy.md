---
tags: [config, deploy, devops]
---

# Config y Deploy

## Variables de entorno
| Variable | Dónde | Uso |
|---|---|---|
| `ANTHROPIC_API_KEY` | `.env` (local) / Render env | [[IA Anthropic]] |
| `SECRET_KEY` | hardcodeada en app.py | Flask sessions |
| `PORT` | Render la inyecta | gunicorn bind |

`.env` está en `.gitignore`. En Render se añaden en Dashboard → Environment.

## Estructura de deploys
```
Local dev:    python app.py  (debug=True, puerto 5000)
Producción:   gunicorn app:app  (vía Procfile)
```

## Render
- Conectado por **Public Git Repository URL**
  `https://github.com/telmilloelpillo-hue/comparativa-farmacias`
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Auto-deploy en cada `git push` a `main`
- Plan gratuito: la app duerme tras 15 min inactiva (~30s cold start)

## Git workflow
```bash
# Desarrollo local
git add <ficheros>
git commit -m "descripción"
git push   # → Render despliega automáticamente
```
obsidian-git hace commits automáticos de las notas con mensaje `vault backup: {{date}}`.

## Antes (PythonAnywhere)
WSGI file: `/var/www/telmobarris_pythonanywhere_com_wsgi.py`
Deploy manual: `git pull` + `touch wsgi`. Ya migrado a Render.

## Relaciones
- [[App Flask]] — `Procfile`, `requirements.txt`
- [[IA Anthropic]] — necesita `ANTHROPIC_API_KEY`
- [[Sesion y Auth]] — `SECRET_KEY`
- [[000 MOC]] — visión global
