## Qué hace este PR

<!-- Explica el cambio en 2-3 frases. Si cierra un issue: "Closes #123". -->

## Trazabilidad

<!-- Una de las tres. Si es un chore trivial, marca N/A. -->

- **Jira:** `ABC-000` | N/A   <!-- ABC = clave del proyecto en Jira; se define al iniciarlo -->
- **Issue:** Closes #000 | N/A

> Si hay clave de Jira, repítela al final del título del PR: `feat(scope): subject [ABC-000]`.

## Tipo de cambio

- [ ] `feat` - funcionalidad nueva
- [ ] `fix` - corrección de bug
- [ ] `refactor` - cambio interno sin alterar comportamiento
- [ ] `perf` - mejora de rendimiento
- [ ] `docs` / `test` / `chore` / `ci` / `build`
- [ ] **Breaking change** (describe la migración abajo)

## Cómo probarlo

<!-- Pasos concretos para que quien revise lo verifique. Incluye datos de prueba si aplica. -->

1.
2.

## Checklist

- [ ] La rama sale de `develop` y apunta a `develop`.
- [ ] El título del PR sigue Conventional Commits: `type(scope): subject`.
- [ ] `ruff check .` en verde localmente.
- [ ] Las pruebas sin servidor pasan: `test_liveness`, `test_voice`, `test_digits`, `test_replay`, `test_speaker_embedding`.
- [ ] Si toqué la API: las pruebas con servidor pasan (`test_full_api`, `test_apikeys`, `test_challenge_api`, `test_voice_duplicates`).
- [ ] No hay valores hardcodeados (secretos, contraseñas, URLs, umbrales).
- [ ] No añadí comentarios ni docstrings al código; la explicación va en `docs/` o en el README.
- [ ] Si toqué el esquema: **migración aditiva nueva** en `scripts/`; no modifiqué migraciones existentes.
- [ ] Si añadí endpoints: están en la tabla de permisos de `required_scope()` en `backend/main.py` **y** documentados en `docs/api/`.
- [ ] Si añadí variables de entorno: están en `.env.example` **y** en `docs/empezar/configuracion.md`.
- [ ] Añadí o actualicé pruebas para la lógica crítica.

## Impacto biométrico

<!-- Rellena solo si tocaste backend/biometrics/, backend/config.py o algún umbral. Si no, marca N/A. -->

- [ ] N/A - este PR no toca biometría ni umbrales.
- [ ] **Umbrales modificados:** cuál, valor anterior → nuevo, y **con qué medición** lo justifico.
- [ ] Remedí con `scripts/diagnose_voice_db.py` / `calibrate_face.py` / `calibrate_voice.py` y adjunto los números.
- [ ] Actualicé `docs/operacion/limitaciones.md` si el cambio corrige o introduce una limitación conocida.

> Un umbral no se cambia "porque va mejor". Se cambia con FAR/FRR medidos y la población
> sobre la que se midieron. Si la población son voces TTS o impostores visualmente lejanos,
> **dilo**: la cifra está inflada a favor.

## Datos personales

- [ ] No añadí ninguna ruta que guarde imágenes, audio o vectores biométricos en disco o en logs.
- [ ] No subí datos biométricos reales al repositorio (`datos_*/` y `frames_liveness/` están en `.gitignore`).

## Capturas / evidencia

<!-- Obligatorio si el PR toca el portal (static/). Antes y después. -->

## Notas para quien revisa

<!-- Decisiones de diseño, deuda técnica asumida, riesgos, qué mirar con lupa. -->
