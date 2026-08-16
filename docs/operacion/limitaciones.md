# Limitaciones conocidas

Esta pagina recoge cada defecto medido, con sus numeros. No es una lista de deseos: es lo
que se sabe que falla y con que magnitud.

!!! danger "Lectura obligatoria antes de produccion"
    Varias de estas limitaciones afectan directamente a la seguridad. Conocerlas es
    condicion para decidir si este servicio puede proteger lo que quieres proteger.

---

## Como se hicieron las mediciones

Con **una sola persona real** y un puñado de audios sinteticos e imagenes publicas. Eso
tiene una consecuencia que atraviesa toda la pagina:

!!! warning "Toda cifra de FAR de esta pagina esta inflada a favor"
    Las cuentas de prueba de voz eran **sintetizadores de texto a voz**, no personas.
    Distinguir TTS de habla humana es facil para cualquier modelo de locutor, asi que un
    0% de falsa aceptacion contra esa poblacion no significa nada sobre impostores
    humanos.

    Lo mismo con el rostro: los impostores probados son visualmente muy distintos del
    titular.

---

## Poca luz en el login facial

**Gravedad: alta. Sin corregir.**

Con iluminacion baja el sistema falla de dos formas contradictorias: o rechaza a todo el
mundo, o acepta a quien no debe.

### Rechazo total

Por debajo de cierta luz, YuNet no detecta rostro:

| Ganancia | Frames con cara (de 28) |
| --- | --- |
| 1.0 | 28 |
| 0.3 | 9 |
| 0.2 | **0** |

Con 0 frames, la respuesta es 400 *No se detecto la cara en suficientes frames*.

### Aceptacion indebida

Son dos causas que se multiplican.

**Causa 1 — el ruido comprime el espacio de embeddings.** La similitud del impostor sube
sin que se parezca mas: SFace pierde informacion y todos los vectores se acercan a un punto
comun.

| Condicion | `impostor_a` | `messi` |
| --- | --- | --- |
| Luz normal | 0.179 | 0.224 |
| Luz media + ruido | 0.197 | 0.234 |
| Poca luz + ruido | 0.230 | 0.293 |
| Muy poca luz + ruido | — | **0.326** |

Con un umbral de 0.363, el margen pasa de 0.14 a **0.037**: se consume el 74%.

Otras degradaciones empujan en la misma direccion:

| Degradacion | `impostor_a` |
| --- | --- |
| Base | 0.179 |
| Desenfoque | 0.254 |
| Cara pequena o lejana | 0.231 |

**Causa 2 — el login se queda con el maximo de la rafaga.**

```python
best = max((_best_similarity(f, templates) for f in feature_list), default=0.0)
```

`_best_similarity` ya toma el maximo sobre las plantillas. Con 28 frames y 13 plantillas
son hasta **364 comparaciones**, y basta que **una** cruce el umbral.

Con un impostor en poca luz (media 0.241, desviacion 0.036), el maximo esperado crece con
el numero de frames:

| Frames | Maximo esperado |
| --- | --- |
| 1 | 0.244 |
| 5 | 0.281 |
| 14 | 0.298 |
| 28 | 0.307 |
| 120 | 0.320 |

Es un problema de comparaciones multiples. Y el ruido **aumenta la desviacion**, asi que la
cola crece justo cuando el margen se ha estrechado.

### Por que el filtro de calidad no lo detiene

`quality.check` mide **nitidez y tamano**, y ambos disparan correctamente. Pero **no hay
ninguna comprobacion de brillo ni de relacion senal-ruido**. Una imagen oscura y ruidosa,
con la cara a buen tamano y bordes definidos, pasa el filtro como valida.

!!! note "Que falta por medir"
    En estas pruebas ningun impostor llego a cruzar 0.363: el maximo fue 0.326. El
    mecanismo esta reproducido y cuantificado, pero **el caso concreto no**, porque no se
    dispuso de la rafaga real. Un impostor visualmente cercano arranca mas alto y con
    0.037 de margen cruzaria sin esfuerzo.

**Mitigaciones posibles**, ninguna aplicada todavia:

1. Anadir un control de brillo y SNR a `quality.check`
2. Sustituir el `max()` por una **mediana** o un percentil alto sobre los frames
3. Subir el umbral cuando el brillo medio de la rafaga sea bajo
4. Rechazar la captura por debajo de un brillo minimo, pidiendo mas luz

---

## Modo `gmm-z`: no verifica

**Gravedad: alta. Mitigado, no eliminado.**

Cuando no hay embedding ni locutores de fondo suficientes, la verificacion cae al z-score
sobre GMM.

| Medicion | Resultado |
| --- | --- |
| Impostor real | `z = -2.444` frente a umbral `-2.5` |
| Margen | **0.056** |
| EER bajo adaptacion MAP | **50.4%** |

Un 50.4% de EER es exactamente una moneda al aire.

!!! danger "Comprueba `scoring` en cada respuesta"
    Si vale `"gmm-z"`, no estas verificando. Consulta
    [`GET /api/voice/system`](../api/voz.md#estado-del-sistema-de-voz): `scoring_active`
    debe ser `"embedding"`.

---

## Umbral de voz medido con muy pocos datos

**Gravedad: media. Sin resolver.**

| Medicion con ResNet34 | Valor |
| --- | --- |
| Mismo hablante, peor caso | 0.411 |
| Voz ajena humana, mejor caso | 0.270 |
| **Margen** | **+0.141** |
| Impostores humanos usados | **1** |

Un margen de 0.141 medido con un solo impostor no permite afirmar nada sobre la tasa de
error real.

### El error de CAM++, y por que importa

El modelo anterior (CAM++) estaba **roto en la integracion** y no se detecto durante mucho
tiempo, porque toda la validacion usaba audio sintetico: se estaba midiendo
real-contra-sintetico, una tarea facil, y el resultado parecia excelente (+0.472 de
margen).

Dos audios descargados de personas distintas lo destaparon:

| Medicion | Valor |
| --- | --- |
| Correlacion de formas de onda entre los dos audios | 0.0008 |
| Coseno de sus embeddings CAM++ | **0.9006** |
| F0 de las dos voces | 186 Hz y 154 Hz |
| F0 del titular | 122 Hz |
| `titular ↔ descargado_1` | **0.95** |
| `titular ↔ titular` | 0.93 |

El impostor puntuaba **mas alto que el propio titular**. La correccion fue cambiar a
ResNet34 (`hbredin/wespeaker-voxceleb-resnet34-LM`), ajustar `HIGH_FREQ` de 7600 a 8000 Hz
y bajar los umbrales de 0.40 a 0.35.

!!! danger "La leccion, no el bug"
    Un conjunto de validacion facil hace que un componente roto parezca excelente. Ninguna
    cifra de precision de este servicio significa nada hasta que se remida con **personas
    reales distintas**.

---

## Estado en memoria

**Gravedad: media. Sin resolver.**

Tres mecanismos viven en la memoria del proceso:

| Mecanismo | Consecuencia con varios workers |
| --- | --- |
| Limitador de intentos | El limite real se multiplica por el numero de workers |
| Guarda de repeticion | Una rafaga reenviada puede caer en otro worker y pasar |
| Cache de API keys | Una clave revocada sigue valida hasta **60 s** en los otros workers |

Los desafios de digitos **si** estan en PostgreSQL y no sufren este problema.

**Solucion:** mover los tres a Redis. Pendiente.

!!! warning "Afecta a cualquier despliegue con `--workers > 1`"
    Con 4 workers y `AUTH_RATE_LIMIT=10`, el limite efectivo son 40 intentos por minuto.

---

## Plantillas sin cifrar

**Gravedad: media. Sin resolver.**

Se guardan como `BYTEA` en claro. Quien lea la base obtiene los vectores biometricos de
todo el mundo.

No permiten reconstruir la cara ni la voz, pero **identifican de forma univoca y
permanente**. Una cara no se puede cambiar tras una filtracion.

**Solucion:** cifrado a nivel de columna con clave fuera de la base. Pendiente. Mientras
tanto, cifrado en reposo del volumen y control estricto de acceso.

---

## Sin registro de consentimiento

**Gravedad: alta en lo legal. Sin resolver.**

La Ley 1581 de 2012 exige consentimiento previo, expreso e informado para tratar datos
sensibles. No existe ninguna tabla que registre quien consintio, cuando, a que finalidad y
por cuanto tiempo.

**Solucion:** tabla de consentimientos con marca temporal, version del aviso de privacidad
y finalidad, enlazada al usuario. Pendiente.

---

## `identify` no escala

**Gravedad: baja. Sin resolver.**

`POST /api/face/identify` recorre **todas** las plantillas en un bucle de Python,
comparando una a una. Con miles de usuarios se degrada de forma lineal.

**Solucion:** indice vectorial (`pgvector` con indice HNSW o IVFFlat). Pendiente.

`POST /api/voice/identify` tiene el mismo patron, pero suele haber menos plantillas de voz.

---

## Deteccion facial imperfecta

**Gravedad: baja.**

En el conjunto de pruebas, **1 de cada 14 fotos** no produjo deteccion de rostro con YuNet,
pese a tener una cara claramente visible.

Se mitiga enviando varias fotos en la matricula y una rafaga en el login: basta con que una
funcione. Pero explica por que una foto concreta puede ser rechazada sin motivo aparente.

---

## Sesgo del CMVN en los digitos

**Gravedad: alta. Corregido.**

La normalizacion cepstral se calculaba sobre toda la grabacion. En la matricula eran 10
digitos; en el desafio, 4. Las cifras resultantes no eran comparables.

| Medicion | Resultado |
| --- | --- |
| Desafios fallidos con audio identico | **7 de 20** |

Un primer intento de arreglo (usar solo frames con voz) resulto insuficiente. La solucion
definitiva fue **guardar la CMVN de la matricula** en `voice_digit_templates.cmvn` e
imponerla al verificar.

!!! warning "Las matriculas antiguas hay que repetirlas"
    Una matricula anterior a este cambio no tiene CMVN guardada. Se detecta con
    `cmvn_ok: false` en `GET /api/voice/digits/{username}`, y el servicio se niega a emitir
    desafios para esa cuenta.

---

## Voz duplicada en dos cuentas

**Gravedad: alta. Corregido.**

Dos cuentas tenian la misma voz matriculada, y puntuaban **0.916** entre si. Una sola
grabacion abria las dos, lo que parecia *el sistema acepta a cualquiera* cuando en realidad
el sistema estaba acertando: eran la misma persona.

**Corregido** con el control de duplicados en la matricula
(`VOICE_REJECT_DUPLICATES=true`). `POST /api/voice/identify` sigue siendo la herramienta
para detectar el caso: si devuelve `ambiguous: true`, hay voces compartidas.

---

## Umbral LLR demasiado bajo

**Gravedad: alta. Corregido.**

`VOICE_LLR_THRESHOLD` estaba en `0.4`.

| Medicion | Resultado |
| --- | --- |
| Intentos de impostor aceptados | **6 de 40** |
| FAR | **15%** |

El titular era **siempre** la mejor coincidencia, asi que el fallo estaba en el umbral, no
en el algoritmo. Se subio a `1.2`.

!!! warning "1.2 es un suelo, no un valor calibrado"
    Es mejor que 0.4, que estaba medido como malo. El margen sigue siendo de solo 0.22
    (peor genuino 1.35 frente a mejor impostor 1.13) sobre un rango genuino de ~1.0, y
    ademas medido contra voces TTS.

---

## Audio casi en silencio aceptado

**Gravedad: media. Corregido.**

Un audio a -70 dBFS producia unos 490 frames clasificados como "voz" y se procesaba como si
fuera habla.

**Corregido** con un suelo absoluto de `MIN_RMS_DBFS = -55.0` en `extract_features`.

---

## Procesado de audio del navegador

**Gravedad: media. Corregido en el portal.**

Chrome aplica por defecto cancelacion de eco, supresion de ruido y control automatico de
ganancia. Los tres alteran el timbre lo suficiente como para degradar el embedding y
provocar rechazos de usuarios legitimos.

**Corregido** en el portal capturando con `echoCancellation: false, noiseSuppression:
false, autoGainControl: false, channelCount: 1`.

!!! danger "Tu frontend debe hacer lo mismo"
    Esto no se puede arreglar en el servidor. Cualquier cliente propio tiene que
    desactivarlo. Ver [Desde un frontend](../integracion/frontend.md).

---

## Resumen

| Limitacion | Gravedad | Estado |
| --- | --- | --- |
| Poca luz en el login facial | Alta | **Sin corregir** |
| Sin registro de consentimiento | Alta (legal) | **Sin resolver** |
| Modo `gmm-z` no verifica | Alta | Mitigado |
| Umbral de voz con 1 impostor | Media | **Sin resolver** |
| Estado en memoria con varios workers | Media | **Sin resolver** |
| Plantillas sin cifrar | Media | **Sin resolver** |
| `identify` no escala | Baja | **Sin resolver** |
| Deteccion facial imperfecta | Baja | Mitigado |
| Sesgo del CMVN en digitos | Alta | Corregido |
| Voz duplicada | Alta | Corregido |
| Umbral LLR bajo | Alta | Corregido |
| Audio en silencio aceptado | Media | Corregido |
| Procesado de audio del navegador | Media | Corregido |
