---
tags: [herramientas, claude-code, skills, ia]
---

# Skills Matt Pocock — Referencia rápida

Plugin instalado globalmente (scope: user) desde [github.com/mattpocock/skills](https://github.com/mattpocock/skills).

Instalado en: `~/.claude/plugins/cache/mattpocock/skills/1.0.0`

---

## Uso general

Invocar con `/nombre-skill` en cualquier conversación de Claude Code.
Lo más importante: usar **antes** de ponerse a codificar, no después.

---

## Engineering — Skills de desarrollo

### `/diagnose`
Bucle disciplinado para bugs difíciles y regresiones de rendimiento.
Flujo: reproducir → minimizar → hipotetizar → instrumentar → corregir → test de regresión.
**Cuándo**: cuando un bug no está claro o has intentado más de 1 fix sin éxito.

### `/grill-with-docs`
Sesión de "interrogatorio" que cuestiona tu plan contra el modelo de dominio existente,
afina terminología y actualiza `CONTEXT.md` y ADRs en línea.
**Cuándo**: antes de cualquier feature nueva o cambio de arquitectura.

### `/triage`
Gestiona issues a través de una máquina de estados de roles de triage.
**Cuándo**: para priorizar el backlog.

### `/improve-codebase-architecture`
Busca oportunidades de mejora arquitectónica informadas por el lenguaje del dominio
en `CONTEXT.md` y las decisiones en `docs/adr/`.
**Cuándo**: cada pocos días para combatir la entropía del código.

### `/setup-matt-pocock-skills`
Configura el repo (issue tracker, vocabulario de etiquetas, layout de docs).
**Ejecutar una sola vez** antes de usar `to-issues`, `to-prd`, `triage`, `diagnose`,
`tdd`, `improve-codebase-architecture` o `zoom-out`.

### `/tdd`
TDD con bucle rojo-verde-refactor. Construye features o corrige bugs un slice vertical a la vez.
**Cuándo**: para cualquier feature nueva o bugfix.

### `/to-issues`
Desglosa cualquier plan, spec o PRD en GitHub issues independientes usando slices verticales.
**Cuándo**: cuando tienes un PRD o plan escrito.

### `/to-prd`
Convierte el contexto de conversación actual en un PRD y lo envía como GitHub issue.
No entrevista — sintetiza lo que ya se ha discutido.
**Cuándo**: al final de una sesión de diseño/alineación.

### `/zoom-out`
Le dice al agente que haga zoom out y dé contexto más amplio o perspectiva de alto nivel
sobre una sección de código desconocida.
**Cuándo**: cuando el agente está demasiado enfocado en detalles y pierde el panorama.

### `/prototype`
Construye un prototipo desechable para validar un diseño. Puede ser una app de terminal
para lógica de negocio, o varias variaciones de UI radicalmente diferentes desde una ruta.
**Cuándo**: cuando no estás seguro de cómo debe funcionar algo antes de construirlo.

---

## Productivity — Herramientas de flujo de trabajo

### `/caveman`
Modo de comunicación ultra-comprimido. Reduce el uso de tokens ~75% eliminando relleno
pero manteniendo precisión técnica completa.
**Cuándo**: sesiones largas donde el contexto empieza a escasear.

### `/grill-me`
Sesión de interrogatorio implacable sobre un plan o diseño hasta resolver cada rama
del árbol de decisión.
**Cuándo**: antes de empezar cualquier feature — el más recomendado del repo.

### `/write-a-skill`
Crea nuevas skills con estructura correcta, divulgación progresiva y recursos agrupados.
**Cuándo**: cuando quieres codificar un flujo de trabajo repetible.

---

## Misc — Herramientas ocasionales

### `/git-guardrails-claude-code`
Configura hooks de Claude Code para bloquear comandos git peligrosos
(push, reset --hard, clean…) antes de que se ejecuten.

### `/setup-pre-commit`
Configura hooks Husky pre-commit con lint-staged, Prettier, type checking y tests.

---

## Flujo recomendado para una feature nueva

```
1. /grill-me          → alinear qué se quiere construir exactamente
2. /grill-with-docs   → contrastar con arquitectura existente, actualizar CONTEXT.md
3. /to-prd            → documentar decisión como PRD/issue
4. /tdd               → implementar con red-green-refactor
5. /zoom-out          → revisar que encaja en el sistema completo
```

---

## Relaciones
- [[PDF_PARSER]] — ejemplo de uso de `/diagnose` para bugs del parser
- [[Feature Comparativa]] — candidato a `/improve-codebase-architecture`
- [[000 MOC]] — mapa de contenidos del vault
