---
name: Reporte de bug
about: Algo no funciona como debería
labels: bug
---

## Descripción
<!-- Qué ocurre. -->

## Pasos para reproducir
1.
2.

## Esperado vs obtenido
- **Esperado:**
- **Obtenido:**

## Entorno
- Rama / commit:
- Entorno: local | develop | test | prod
- Python:
- Navegador / SO (si el fallo es en el portal):

## Si el fallo es biométrico

<!-- Rellena esta sección si el problema es un rechazo o una aceptación indebida.
     Sin estos datos no se puede diagnosticar. Si no aplica, borra la sección. -->

- **Modalidad:** rostro | voz | desafío de dígitos | contraseña
- **Respuesta completa del endpoint** (sin el `access_token`):

```json

```

- **`scoring`** que devolvió (solo voz): `embedding` | `ubm-map` | `gmm-z`
- **Salida de `GET /api/voice/system`** (solo voz):

```json

```

- **Condiciones de captura:** iluminación, distancia a la cámara, ruido de fondo, micrófono
- **¿Ocurre siempre o de forma intermitente?**

## Evidencia
<!-- Logs, capturas, respuesta de la API. -->

> **No adjuntes datos biométricos reales**: ni fotos, ni audio, ni vectores de plantilla.
> Son datos sensibles bajo la Ley 1581 y un issue de GitHub es público. Adjunta las
> puntuaciones y los códigos de respuesta, no el material de origen.
