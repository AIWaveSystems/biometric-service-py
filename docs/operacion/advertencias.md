# Advertencias de desarrollo

!!! danger "Software en desarrollo activo, aún no liberado"
    Este servicio **no tiene una versión estable publicada**. Está en desarrollo,
    su API puede cambiar sin aviso entre confirmaciones y ningún componente ha
    sido auditado por un tercero. No lo uses con biometría de personas reales
    hasta haber leído esta página completa y
    [Limitaciones conocidas](limitaciones.md).

---

## El login por voz exige validación y ajuste propio en cada sistema

**No existe una configuración de voz que sirva para todos los despliegues.** Los
umbrales (`VOICE_EMBEDDING_THRESHOLD`, `VOICE_DUPLICATE_THRESHOLD`,
`VOICE_LLR_THRESHOLD`) dependen de la población real de cada sistema: micrófonos,
canales de audio, ruido ambiente, acentos y edad de los usuarios. Los valores de
fábrica salieron de mediciones con **una sola persona real y voces sintéticas**,
as que son un punto de partida, no una configuración.

Cada sistema que integre el login por voz debe:

1. Registrar **al menos 3 personas reales distintas** (más es mejor) en
   condiciones parecidas a las de producción.
2. Medir con `scripts/diagnose_voice_db.py` y `scripts/calibrate_voice.py`
   contra sus propias tomas.
3. Ajustar los umbrales del `.env` según el resultado, priorizando el equilibrio
   entre rechazar legítimos (FRR) y aceptar impostores (FAR).
4. Repetir la medición cuando cambien dispositivos, micrófonos o entorno.

Es probable que además haya que **ajustar código**: cambiar la vía de puntuación,
congelar un UBM propio, exigir el desafío de dígitos o endurecer el guardia de
duplicados. Verifica siempre que las respuestas reportan
`scoring: "ubm-map"` o `"embedding"`; con `gmm-z` el sistema **no está
verificando nada fiable**.

## Cuántos usuarios distintos hacen falta antes de fijar configuración

Ninguna cifra de FAR/FRR significa nada por debajo de una población mínima de
**personas distintas** matriculadas en condiciones reales de captura. Con pocos
usuarios los cuantiles de impostor son ruido estadístico: un umbral «sugerido»
por debajo de ese mínimo sirve solo para detectar problemas groseros (cuentas
duplicadas), nunca para fijar la configuración de un sistema.

| Módulo | Mínimo para pruebas | Base recomendada para producción | Medición |
| --- | --- | --- | --- |
| Voz | 3 personas reales distintas | 10 o más, con micrófonos y ambiente de producción | `diagnose_voice_db.py`, `calibrate_voice.py` |
| Rostro | 10 personas distintas | 15-30; repetir la medición cada vez que crezca la base | `calibrate_face_db.py` |
| Desafío de dígitos | 1 persona valida su propia matrícula | Igual: es por usuario, no poblacional | `test_digits.py`, `test_challenge_api.py` |
| Parpadeo (liveness) | No depende de la población | Igual | `test_liveness.py` |

Mientras un módulo esté por debajo del mínimo:

- Trata su verificación como ayuda al segundo intento, nunca como factor único.
- Usa la banda `borderline` del login facial para pedir repetición en lugar de
  subir el umbral global (subirlo castiga a los genuinos con la muestra corta).
- Mide de nuevo al incorporar usuarios: los números se estabilizan con la
  población, no con el tiempo.

## El login facial también exige validación y ajuste propio

Igual que la voz, el rostro se calibró con una muestra mínima: 14 fotos reales de
una persona y 3 impostores visualmente muy distintos. Cada sistema debe
recalibrar contra su propia población, ahora con dos vías complementarias:

1. Matricula usuarios reales por la vía normal (API o portal) y mide directamente
   sobre las plantillas guardadas: `python scripts/calibrate_face_db.py`. Si
   aparecen pares impostores altos, son cuentas duplicadas: exclúyelos con
   `--excluir-sospechosos`, corrige las cuentas y vuelve a medir.
2. Para condiciones controladas (luz baja, contraluz, cámaras distintas,
   distancia) usa `python scripts/calibrate_face.py datos_cara` con carpetas por
   persona.
3. Elige umbral con esas curvas FAR/FRR y los cuantiles por FAR objetivo, no con
   el valor de fábrica (`0.363`), y respeta la población mínima definida arriba.

Ten presente que el liveness **solo detecta fotografía estática**: ni vídeos en
pantalla, ni máscaras, ni deepfakes. Si tu sistema necesita resistencia a esos
ataques, hay que añadir mecanismos adicionales por código.

## Una persona, una cuenta

Matricular a la misma persona en dos cuentas rompe la seguridad sin que ningún
componente falle: la cara coincide porque es la misma, pero abre la cuenta
equivocada. Medido en la base de desarrollo: dos cuentas gemelas puntuaban hasta
**0.79** entre sí, muy por encima del umbral 0.363, mientras los impostores
legítimos rara vez superan 0.40. Es la causa clásica del «a veces se entra con la
cara de otro».

- La voz tiene guardia automático que rechaza matrículas duplicadas
  (`VOICE_REJECT_DUPLICATES`). El rostro **no lo tiene**: es responsabilidad del
  proceso de alta de cada sistema cliente garantizar que una persona tenga una
  sola cuenta.
- Detección: `POST /api/voice/identify` con `ambiguous: true` delata voces
  compartidas; `scripts/calibrate_face_db.py` lista los pares de plantillas
  faciales con similitud sospechosa entre usuarios distintos.
- Corrección: borrar o volver a matricular la cuenta duplicada con otra persona,
  y repetir la medición.

!!! note "El alcance es por sistema cliente"
    «Una cuenta» significa una cuenta **dentro de cada web conectada**. Cada cliente
    API tiene su propio espacio de nombres: la misma persona puede (y suele) tener
    una cuenta en cada web que la usa, con su propio `username` — incluso el mismo
    nombre en varias webs. Lo que no debe existir son dos cuentas de la misma
    persona **dentro del mismo sistema**.

## Un sistema biométrico falla de forma lógica e inevitable

Esto no es un defecto puntual sino una propiedad del problema:

- **Falsos positivos y falsos negativos siempre existen.** Bajar el umbral deja
  entrar impostores; subirlo rechaza usuarios legítimos. No hay un valor sin
  error, solo errores más caros o más baratos según el caso de uso.
- **La biometría no es un secreto.** Una contraseña filtrada se cambia; una cara
  o una voz filtradas no. Las plantillas hoy se guardan **sin cifrar** en la
  base de datos.
- **Los ataques de presentación evolucionan.** Grabaciones, síntesis de voz en
  tiempo real y vídeo de la persona son escenarios que este servicio no cubre
  por completo; el desafío de dígitos mitiga la grabación, no la clonación.
- **El fallo puede ser silencioso.** Con población de fondo insuficiente, la
  verificación de voz responde `verified: true` con normalidad en modo
  degradado. El cliente **debe comprobar** `scoring` y `n_background_speakers`
  en cada respuesta.

Trata cada respuesta biométrica como una opinión probabilística, nunca como una
verdad absoluta, y diseña el flujo del sistema integrador con un segundo factor.

## Estado general del proyecto

| Área | Estado |
| --- | --- |
| Versionado | Rama `develop`; sin releases estables; cambios rompientes esperados |
| Calibración | Una persona real (facial), una persona real + sintéticos (voz) |
| Auditoría de seguridad | Ninguna |
| Consentimiento (Ley 1581 de 2012) | Sin tabla de registro; requisito legal pendiente |
| Cifrado de plantillas | Sin implementar |
| Escalado multi-worker | Anti-replay, rate limit y caché de keys en memoria del proceso |
| Suite de pruebas | Scripts de integración manuales; `test_full_api.py` es destructivo |

Recomendaciones mientras no exista release:

- Despliega solo en entornos de prueba con `DATABASE_URL` apuntando a una base
  desechable.
- Fija un commit concreto si necesitas reproducibilidad; no persigas `develop`
  en producción.
- Revisa el diff antes de actualizar: la API y las migraciones pueden cambiar.
- Nunca mezcles usuarios de prueba (`scripts/synth.py`, `test_full_api.py`) con
  personas reales en la misma base: contamina la verificación en silencio.

---

## Cómo proponer soluciones

Las correcciones y mejoras se reciben como pull requests dirigidas a la rama
`develop` del repositorio original
([AIWaveSystems/biometric-service-py](https://github.com/AIWaveSystems/biometric-service-py)).

Paso a paso:

1. **Haz un fork** del repositorio desde GitHub (botón *Fork*), que crea
   `TU_USUARIO/biometric-service-py`.
2. Clona tu fork y sincroniza la rama base:

    ```bash
    git clone https://github.com/TU_USUARIO/biometric-service-py.git
    cd biometric-service-py
    git remote add upstream https://github.com/AIWaveSystems/biometric-service-py.git
    git fetch upstream
    git checkout develop
    git merge --ff-only upstream/develop
    ```

3. Crea una rama descriptiva desde `develop`:

    ```bash
    git checkout -b fix/nombre-corto-del-cambio
    ```

4. Implementa el cambio siguiendo el estilo del proyecto: mensajes de commit
   convencionales (`feat:`, `fix:`, `docs:`, `test:`), sin comentarios
   innecesarios en el código y sin romper los flujos existentes. Si el cambio
   toca la base de datos, añade un script de migración aditivo en `scripts/`.

5. Verifica antes de proponer:

    - Que los scripts de integración relevantes siguen pasando contra un servidor
      local.
    - Si el cambio es de precisión, adjunta la medición antes/después (EER, FAR,
      FRR o margen) producida con los scripts de calibración.

6. Sube la rama a tu fork y abre el PR **contra `AIWaveSystems/
   biometric-service-py` → `develop`** (no contra `main`). Describe qué problema
   resuelve, cómo reproducirlo y qué mediste.

7. Mantén el PR pequeño y enfocado a un solo cambio; si necesitas varios,
   abre PR separados.
