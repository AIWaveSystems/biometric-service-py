# Login Biométrico — Rostro y Voz

Servicio de autenticación biométrica construido con FastAPI. Todos los algoritmos
biométricos (LBP, MFCC, GMM-EM, PCA) están implementados desde cero sobre NumPy;
OpenCV se usa únicamente para decodificar imágenes, detectar rostros con cascadas
Haar y aplicar filtros de imagen.

---

## Índice

1. [Arquitectura](#arquitectura)
2. [Instalación y arranque](#instalación-y-arranque)
3. [Configuración (.env)](#configuración-env)
4. [Cómo funciona el reconocimiento facial](#cómo-funciona-el-reconocimiento-facial)
5. [Cómo funciona la detección de vida](#cómo-funciona-la-detección-de-vida-liveness)
6. [Cómo funciona el reconocimiento de voz](#cómo-funciona-el-reconocimiento-de-voz)
7. [Modelo de seguridad](#modelo-de-seguridad)
8. [API](#api)
9. [Rendimiento medido](#rendimiento-medido)
10. [Calibración de umbrales](#calibración-de-umbrales)
11. [Scripts](#scripts)
12. [Limitaciones conocidas](#limitaciones-conocidas)

---

## Arquitectura

```
backend/
  main.py              app FastAPI, middlewares de acceso, montaje de estáticos
  config.py            configuración tipada leída de .env
  security.py          emisión/validación de JWT, anti-replay, rate limiting
  database.py          motor SQLAlchemy y sesión por petición
  models.py            tablas users, face_templates, voice_templates
  schemas.py           modelos de petición/respuesta de la API
  routers/
    portal.py          login del portal (credenciales de .env)
    auth.py            login por contraseña
    face.py            registro, verificación, login con liveness, identificación
    voice.py           registro y verificación de locutor
    users.py           alta combinada, listado y borrado
  biometrics/
    face/
      detector.py      detección Haar, alineación por ojos, CLAHE, normalización
      lbph.py          patrones binarios locales uniformes multiescala
      matcher.py       métricas de distancia y similitud
      liveness.py      señal de apertura ocular y detección de parpadeo
      quality.py       puerta de calidad de captura (nitidez, tamaño, contraste)
      eigenfaces.py    PCA desde cero (implementado, no usado por la API)
    voice/
      wav.py           lectura de WAV PCM y remuestreo con filtro antialiasing
      mfcc.py          preénfasis, ventaneo, banco Mel, DCT-II, deltas
      gmm.py           mezcla de gaussianas con k-means++ y EM
      pipeline.py      VAD, CMVN, matrícula, calibración y verificación
static/                portal web (HTML, CSS, JS sin dependencias externas)
scripts/               pruebas, calibración y utilidades
```

El flujo de una petición biométrica es:

```
navegador → middleware DocsBasicAuth → middleware PortalApiAuth → router
          → biometrics/* (NumPy/OpenCV) → SQLAlchemy → PostgreSQL
```

---

## Instalación y arranque

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python scripts/create_db.py       # crea la base en PostgreSQL
python scripts/migrate_voice.py   # aplica columnas de calibración de voz

uvicorn backend.main:app --reload
```

El portal queda en `http://127.0.0.1:8000`. Las rutas `/docs`, `/redoc` y
`/openapi.json` piden Basic Auth con las credenciales de `.env`.

Los scripts de prueba que hablan con la API por HTTP necesitan además
`pip install requests`.

---

## Configuración (.env)

Copia [`.env.example`](.env.example) a `.env` y rellénalo. Ese archivo explica
cada variable en detalle: rango útil, cómo calibrarla y qué implica subirla o
bajarla. La tabla siguiente es el resumen.

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # para JWT_SECRET
```

Sin `DATABASE_URL`, `JWT_SECRET`, `PORTAL_USER` y `PORTAL_PASSWORD` el servicio
no arranca.

| Variable | Por defecto | Qué hace |
|---|---|---|
| `DATABASE_URL` | — | Cadena de conexión de SQLAlchemy. Obligatoria. |
| `JWT_SECRET` | — | Clave de firma de los tokens. Obligatoria. |
| `JWT_ALGORITHM` | `HS256` | Algoritmo de firma. |
| `JWT_EXPIRE_MINUTES` | `60` | Vigencia del token del portal. |
| `SESSION_EXPIRE_MINUTES` | `15` | Vigencia del token de sesión de usuario. |
| `FACE_THRESHOLD` | `0.70` | Similitud coseno mínima para aceptar un rostro. |
| `VOICE_LLR_THRESHOLD` | `0.4` | Log-verosimilitud mínima frente al UBM (vía principal). |
| `VOICE_Z_THRESHOLD` | `-2.5` | z-score mínimo (solo en el modo de reserva). |
| `VOICE_RATIO_THRESHOLD` | `-3.0` | Ventaja mínima sobre la cohorte (modo de reserva). |
| `LIVENESS_MIN_FACES` | `6` | Frames con rostro necesarios para evaluar el parpadeo. |
| `LIVENESS_MAX_GAP_RATIO` | `0.4` | Fracción máxima de frames sin rostro admitida. |
| `REPLAY_WINDOW_SECONDS` | `300` | Ventana en la que se rechaza una captura repetida. |
| `AUTH_RATE_LIMIT` | `10` | Intentos de login permitidos por ventana. |
| `AUTH_RATE_WINDOW_SECONDS` | `60` | Duración de la ventana de rate limiting. |
| `CORS_ORIGINS` | vacío | Orígenes permitidos, separados por comas. Vacío = solo mismo origen. |
| `PORTAL_USER` / `PORTAL_PASSWORD` | — | Credenciales de acceso al portal. Obligatorias. |
| `DOCS_USER` / `DOCS_PASSWORD` | heredan del portal | Credenciales de la documentación. |

---

## Cómo funciona el reconocimiento facial

### 1. Detección y normalización (`detector.py`)

1. La imagen se decodifica y se pasa a escala de grises.
2. Una cascada Haar frontal localiza rostros sobre la imagen ecualizada; se
   conserva el de mayor área.
3. El recorte se expande un 12 % en horizontal y un 6 % en vertical para incluir
   frente y mentón.
4. Una cascada de ojos busca ambos ojos dentro del recorte. Si los encuentra, se
   calcula el ángulo entre sus centros y la cara se rota para dejarlos
   horizontales. Esto elimina la variación por inclinación de cabeza.
5. Se aplica CLAHE (ecualización adaptativa con límite de contraste), que
   compensa iluminación desigual sin saturar zonas ya contrastadas.
6. El resultado se reescala a 200×200.

Separar `find_face_rect` de `normalize_face` permite detectar una sola vez por
frame y reutilizar el rectángulo para identidad y liveness.

### 2. Descriptor LBPH (`lbph.py`)

Para cada píxel se comparan sus 8 vecinos situados a un radio dado; cada
comparación aporta un bit, formando un código de 8 bits. Con radios no enteros
los vecinos se obtienen por interpolación bilineal.

Los 256 códigos posibles se reducen a **59 bins uniformes**: los 58 patrones con
como mucho dos transiciones 0↔1 circulares, más un bin que agrupa el resto. Los
patrones uniformes concentran la información de bordes y esquinas y son estables
frente al ruido.

La cara se divide en una rejilla de 8×8 bloques. En cada bloque se acumula el
histograma de 59 bins y se normaliza L2. El proceso se repite con radios 1 y 2
para capturar textura fina y gruesa. La concatenación da un vector de
`2 × 64 × 59 = 7552` dimensiones, normalizado L2 de nuevo.

### 3. Comparación (`matcher.py`)

Se usa **similitud coseno** entre descriptores. Medida sobre las imágenes de
prueba del repositorio, es la métrica que mejor separa:

| Métrica | Genuino (mínimo) | Impostor | Separación |
|---|---|---|---|
| Coseno | 0.7734 | 0.5611 | **+0.2124** |
| Coseno con raíz cuadrada | 0.8856 | 0.7465 | +0.1391 |
| Chi-cuadrado | 0.4056 | 0.2587 | +0.1469 |

El módulo también expone `chi_square`, `euclidean` y `distance_to_similarity`
para experimentar con otras métricas.

Cada usuario puede tener varias plantillas (el portal captura 3 fotos). La
verificación toma el **máximo** de las similitudes contra todas ellas.

### 4. Puerta de calidad (`quality.py`)

Una captura mala no produce un error honesto: produce un descriptor degradado.
Medido sobre el banco de degradaciones, dos caras **distintas** pero ambas
borrosas se parecen más entre sí que una cara nítida y su versión borrosa. Forzar
la detección sobre entradas malas empeoró la separación de +0.087 a −0.145.

Por eso el servicio **rechaza la captura** en lugar de puntuarla, con un mensaje
accionable:

| Métrica | Mínimo | Motivo |
|---|---|---|
| Lado del rostro | 80 px | Rostro lejano: poca textura para el LBP. |
| Nitidez (varianza del laplaciano) | 100 | El desenfoque es el mayor destructor de identidad. |
| Contraste (desviación típica) | 22 | Sin contraste no hay patrones locales. |
| Píxeles quemados o negros | < 28 % | Contraluz o sobreexposición. |

El umbral de nitidez sale de los datos: las variantes borrosas puntúan 30 y 54,
y la siguiente peor variante puntúa 149 con una similitud aceptable de 0.865. El
corte en 100 separa ambos grupos sin ambigüedad.

En el login facial la puerta se aplica **por frame**: los frames borrosos se
descartan para la identidad, pero siguen contando para el liveness.

---

## Cómo funciona la detección de vida (liveness)

El objetivo es distinguir una persona presente de una fotografía. El portal graba
una ráfaga de ~28 frames en 2.6 s y pide al usuario que parpadee.

### La señal de apertura

Un ojo abierto muestra el iris y la esclerótica, con bordes de alto contraste. Un
ojo cerrado deja piel lisa, con muchos menos bordes. La señal se calcula con la
magnitud del gradiente Sobel sobre la franja ocular del rostro (bandas 0.38–0.55
en vertical, 0.15–0.85 en horizontal).

**La energía absoluta no sirve.** Inclinar una fotografía saca los ojos de esa
franja y hunde la energía, lo que el sistema leería como un parpadeo. Por eso la
señal se **normaliza contra la región inferior del rostro** (nariz y boca, bandas
0.60–0.88), que un parpadeo no altera:

```
apertura = energía_de_bordes(franja_ocular) / energía_de_bordes(región_inferior)
```

Una inclinación rígida escala ambas regiones por igual y el cociente apenas se
mueve; un parpadeo real hunde el numerador y deja el denominador intacto. Medido
sobre una foto inclinada progresivamente:

| Inclinación | Energía ocular | Cociente |
|---|---|---|
| 0° | 67.39 | 1.563 |
| 15° | 68.69 | 1.822 |
| 25° | 9.25 | 1.130 |
| 30° | 8.63 | 1.105 |

La energía absoluta cae un factor 7; el cociente solo un factor 1.4, insuficiente
para cruzar el umbral de parpadeo.

### La detección del parpadeo

Un frame se marca como *cerrado* si su señal baja del 55 % del percentil 80 de la
ráfaga (umbral relativo, para adaptarse a cada cámara e iluminación). Se acepta un
parpadeo cuando aparece el patrón **abierto → cerrado → abierto** con al menos 2
frames abiertos a cada lado y 2 cerrados en medio.

**Los frames sin rostro detectado no cuentan como ojos cerrados.** Se marcan como
huecos e interrumpen cualquier racha. Tratarlos como "cerrado" era explotable:
agitar una foto impresa hace fallar la detección Haar dos frames seguidos y eso
bastaba para simular un parpadeo. Además se rechaza la ráfaga completa si más del
40 % de los frames carecen de rostro, que es la firma de una foto en movimiento.

`scripts/test_liveness.py` cubre estos ataques como pruebas de regresión.

---

## Cómo funciona el reconocimiento de voz

### 1. Audio de entrada (`wav.py`)

El navegador graba PCM float32 a la frecuencia del dispositivo (normalmente
48 kHz) y lo empaqueta como WAV de 16 bits. El servidor lo remuestrea a 16 kHz.

Antes de decimar se aplica un **filtro paso bajo FIR** (sinc enventanado con
Blackman, 101 coeficientes) a la mitad de la frecuencia destino. Sin él, las
componentes por encima de 8 kHz se pliegan sobre la banda útil y contaminan los
MFCC.

### 2. Características MFCC (`mfcc.py`)

1. **Preénfasis** `y[n] = x[n] − 0.97·x[n−1]`, que realza las altas frecuencias
   atenuadas por la radiación labial.
2. **Ventaneo** en tramas de 25 ms con salto de 10 ms y ventana de Hamming.
3. **Espectro de potencia** vía FFT de 512 puntos.
4. **Banco de 26 filtros triangulares en escala Mel**, que imita la resolución
   frecuencial no lineal del oído (`mel = 2595·log10(1 + f/700)`).
5. **Logaritmo** de la energía de cada filtro.
6. **DCT-II ortonormal** para quedarse con 13 coeficientes cepstrales
   decorrelacionados.
7. **Deltas y delta-deltas** por regresión lineal en ventana de ±2 tramas,
   dando 39 dimensiones por trama.

### 3. VAD y normalización (`pipeline.py`)

El **VAD por energía** descarta silencios: se calcula el RMS de cada trama y se
conservan las que superan el 10 % del pico.

El VAD **selecciona tramas ya calculadas**, no recorta la señal. Concatenar los
trozos con voz y calcular después los MFCC introduce discontinuidades en cada
juntura, y esos saltos generan energía espectral falsa. El orden correcto es:
calcular MFCC sobre la señal completa, calcular la máscara de actividad alineada
a las mismas tramas, aplicar CMVN y quedarse con las tramas marcadas.

**CMVN** (normalización cepstral de media y varianza) resta la media y divide por
la desviación de cada coeficiente a lo largo de la grabación. Elimina el sesgo
constante del canal: micrófono, ganancia y distancia. Es lo que permite que una
grabación más floja siga puntuando bien.

### 4. Modelo GMM (`gmm.py`)

Cada locutor se modela con una mezcla de gaussianas de covarianza diagonal:

- **Inicialización k-means++**, que elige centros iniciales separados con
  probabilidad proporcional a la distancia al centro más cercano ya elegido,
  seguida de 15 iteraciones de k-means.
- **Entrenamiento EM**: el paso E calcula las responsabilidades en el dominio
  logarítmico con `logaddexp` para no perder precisión; el paso M actualiza pesos,
  medias y covarianzas, con un suelo de `1e-4` en la varianza para evitar
  gaussianas degeneradas.

El número de componentes se adapta al material disponible: una componente por
cada 25 tramas, con un máximo de 8. Con 8 componentes la separación entre
genuinos e impostores fue de +4.76 nats, frente a +3.70 con 4 componentes; subir
a 16 apenas aportó (+4.86) a cambio de más sobreajuste.

### 5. Matrícula y calibración

Aquí estaba el fallo que rechazaba a usuarios legítimos.

La puntuación de referencia (`self_score`) se calculaba como la verosimilitud
media del modelo **sobre las mismas tramas con las que se entrenó**. Ese valor
está inflado por el sobreajuste: cualquier grabación nueva, aun siendo del mismo
locutor, puntúa muy por debajo, y el margen resultaba negativo.

Ahora la referencia se estima por **validación cruzada en 3 pliegues**: se entrena
un GMM con dos tercios de las tramas y se puntúan las restantes, rotando. De las
puntuaciones retenidas se guardan la media y la desviación típica.

El sesgo medido sobre los locutores sintéticos es de ~2.9 nats:

```
self_score entrenamiento =  1.09
self_score held-out      = -1.78   sigma = 7.30
```

### 6. Verificación: UBM y adaptación MAP

Entrenar un GMM independiente con 3-5 segundos de audio sobreajusta: hay más
parámetros que datos. La solución estándar es **GMM-UBM con adaptación MAP**.

1. Se entrena un **UBM** (Universal Background Model) de 32 componentes con las
   voces de **todos los demás** usuarios registrados. Representa "cómo suena la
   voz humana en general" en este despliegue.
2. El modelo de cada locutor no se entrena desde cero: se **adapta** del UBM
   desplazando sus medias hacia los datos del usuario, con
   `media_nueva = α·centroide + (1−α)·media_UBM`, donde `α = n / (n + r)` y
   `r = 16` es el factor de relevancia. Las componentes con pocos datos apenas se
   mueven y heredan la robustez del UBM.
3. La decisión es la **razón de log-verosimilitudes**:
   `LLR = verosimilitud_locutor − verosimilitud_UBM`.

Medido sobre 12 locutores sintéticos con variación de canal, ganancia y ruido, el
UBM-MAP baja el EER de **36.2 % a 19.9 %**. Ver
[Rendimiento medido](#rendimiento-medido).

El UBM se cachea en memoria y solo se reentrena cuando cambia el conjunto de
plantillas. El modelo del locutor se re-adapta en cada verificación a partir de
sus características almacenadas, de modo que nunca queda desfasado respecto al
UBM vigente.

**Modo de reserva.** El UBM necesita al menos 2 locutores de fondo distintos. Con
menos usuarios registrados no hay población que modelar y el sistema cae al modo
anterior (z-score contra la matrícula más ratio de cohorte). La respuesta indica
cuál se usó en `scoring` (`"ubm-map"` o `"gmm-z"`) y cuántos locutores había en
`n_background_speakers`. **La verificación de voz es notablemente más débil en
modo de reserva**; conviene tener al menos 3 usuarios con voz registrada.

Antes, cuando había menos de dos usuarios, la cohorte se construía con la **propia
voz del objetivo**. Eso comparaba al usuario consigo mismo y hacía el ratio
esencialmente aleatorio. Se eliminó.

---

## Modelo de seguridad

### Dos niveles de token

El servicio distingue dos ámbitos mediante el campo `scope` del JWT:

- **`portal`** — emitido por `/api/portal/auth` con las credenciales de `.env`.
  Da acceso a las rutas `/api/*`. Es la credencial del operador del portal.
- **`user`** — emitido al superar una autenticación (contraseña, rostro o voz).
  Identifica al usuario final y **no sirve** para acceder a `/api/*`.

El middleware exige explícitamente `scope == "portal"`, de modo que un token de
sesión de usuario no puede usarse para listar ni borrar usuarios. Los tokens de
sesión caducan en `SESSION_EXPIRE_MINUTES` (15 por defecto), mucho antes que los
del portal.

### Protecciones implementadas

- **Contraseñas en el cuerpo de la petición.** `/api/auth/login` recibe un JSON;
  antes iban como parámetros de consulta y quedaban registrados en los logs de
  acceso, el historial del navegador y cualquier proxy intermedio.
- **Comparación en tiempo constante** (`hmac.compare_digest`) para las
  credenciales del portal y de la documentación.
- **Verificación de contraseña contra un hash señuelo** cuando el usuario no
  existe, para que el tiempo de respuesta no revele qué usuarios están dados de
  alta.
- **Rate limiting** por IP y usuario en los endpoints de login: 10 intentos por
  minuto, respuesta 429 al superarlo.
- **Anti-replay**: se guarda el SHA-256 de cada captura biométrica durante 5
  minutos. Reenviar la misma ráfaga de frames o el mismo audio devuelve 409. Sin
  esto, capturar el tráfico de un login válido y repetirlo autenticaba de nuevo.
- **CORS restringido**: si `CORS_ORIGINS` está vacío no se añade el middleware y
  solo funciona el mismo origen. Antes era `*`.
- **Rutas síncronas.** Los endpoints biométricos son `def`, no `async def`.
  FastAPI ejecuta los `def` en un pool de hilos; siendo `async def`, los ~1.8 s de
  cómputo NumPy/OpenCV de un login facial bloqueaban el bucle de eventos y con él
  todas las demás peticiones.

---

## API

Todas las rutas `/api/*` salvo `/api/portal/auth` requieren
`Authorization: Bearer <token de portal>`.

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/portal/auth` | Login del portal. Devuelve token con scope `portal`. |
| `POST` | `/api/auth/login` | Login por contraseña (JSON). Devuelve token de sesión. |
| `POST` | `/api/users/register` | Alta con contraseña, fotos y/o audio. |
| `GET` | `/api/users` | Lista de usuarios y sus plantillas. |
| `DELETE` | `/api/users/{username}` | Borra usuario y plantillas en cascada. |
| `POST` | `/api/face/register` | Alta solo con rostro. |
| `POST` | `/api/face/verify` | Compara una foto contra un usuario. |
| `POST` | `/api/face/login` | Login con ráfaga de frames y liveness. Devuelve token. |
| `POST` | `/api/face/identify` | Busca a quién pertenece un rostro. |
| `GET` | `/api/face/templates` | Lista de plantillas faciales. |
| `DELETE` | `/api/face/templates/{id}` | Borra una plantilla facial. |
| `POST` | `/api/voice/register` | Registra o reemplaza la plantilla de voz. |
| `POST` | `/api/voice/verify` | Verifica al locutor. Devuelve token si acepta. |
| `GET` | `/api/voice/templates` | Lista de plantillas de voz. |
| `DELETE` | `/api/voice/templates/{id}` | Borra una plantilla de voz. |

Las respuestas de login incluyen `reason` con una explicación legible cuando la
verificación falla, y `access_token` cuando tiene éxito.

---

## Rendimiento medido

Todas las cifras salen de los scripts del repositorio y son reproducibles. **Son
datos sintéticos y de dos imágenes de prueba, no un conjunto real de personas.**
Sirven para comparar alternativas entre sí, no para prometer una precisión.

### Voz — `python scripts/bench_voice.py`

12 locutores sintéticos, 4 tomas cada uno, con variación de ganancia (0.3–1.0),
filtro de canal y ruido entre matrícula y verificación. EER = tasa de igual error.

| Método | EER (canal variado) | EER (limpio) |
|---|---|---|
| GMM independiente + z-score | 44.2 % | — |
| GMM independiente + ratio de cohorte | 36.2 % | — |
| **UBM-MAP + LLR** | **19.9 %** | **13.8 %** |

La adaptación MAP reduce el error a la mitad. El z-score, que era la vía
principal, resultó ser ruido puro bajo MAP (50.4 %, equivalente a lanzar una
moneda); por eso la decisión pasó a basarse solo en el LLR.

Barrido de hiperparámetros que fijó la configuración actual:

| Componentes UBM | Relevancia | EER variado | EER limpio |
|---|---|---|---|
| 16 | 8 | 25.0 % | 16.3 % |
| 16 | 16 | 22.5 % | 16.3 % |
| 16 | 32 | 22.1 % | 16.3 % |
| 32 | 8 | 22.1 % | 13.8 % |
| **32** | **16** | **19.9 %** | **13.8 %** |

### Por qué se conserva el CMVN

El CMVN destruye parte de la identidad del locutor, pero es imprescindible:

| Normalización | EER limpio | EER canal variado |
|---|---|---|
| Ninguna | **0.0 %** | 50.0 % |
| Solo media (CMN) | 29.8 % | 46.1 % |
| **CMVN** | 16.4 % | **25.0 %** |

Sin normalización el sistema es perfecto mientras no cambie nada y **completamente
inútil** en cuanto cambia el micrófono o la ganancia. El CMVN cambia precisión en
condiciones ideales por funcionar en condiciones reales.

### Rostro — datos reales (14 fotos de webcam + 2 impostores)

Medido con `python scripts/diagnose_face.py datos_cara`.

**La diversidad de la matrícula decide si el sistema funciona.** Con las 7 fotos
utilizables se probaron las 35 combinaciones posibles de 3 plantillas:

| Matrícula | Genuino peor | Impostor mejor | Separación |
|---|---|---|---|
| 3 fotos del mismo momento | 0.6366 | 0.6470 | **−0.0105** |
| 3 fotos de momentos distintos | 0.8397 | 0.6202 | **+0.2194** |

**Todas** las combinaciones tomadas en el mismo momento dan separación negativa:
no existe umbral que las haga funcionar. **Todas** las que mezclan momentos
distintos dan separación positiva. Fotos consecutivas se parecen entre sí un
0.94–0.96; fotos de momentos distintos, un 0.57–0.71.

La causa es que el descriptor LBPH captura tanto la iluminación y la pose como la
identidad. Tres fotos seguidas describen una sola condición, y cualquier cambio
posterior de luz o postura cae fuera.

Verificado de extremo a extremo contra el servicio:

| Matrícula | Plantillas | Aciertos | Falsos rechazos | Falsos positivos |
|---|---|---|---|---|
| 3 fotos del mismo momento | 1 | 2 | 1 | 0 |
| 3 fotos variadas | 2 | **4** | **0** | **0** |

Con matrícula variada los genuinos puntúan 0.836–0.884 y los impostores
0.563–0.593: margen amplio a ambos lados del umbral 0.70.

Por eso el registro **descarta plantillas casi idénticas**
(`MAX_TEMPLATE_SIMILARITY = 0.90` en `quality.py`) y el portal pide cambiar la
distancia y la iluminación entre foto y foto.

### Rostro — banco sintético `python scripts/bench_face.py`

Dos identidades sometidas a 15 degradaciones (rotación, desplazamiento, gamma, luz
lateral, JPEG, desenfoque, ruido, escala, contraste).

| Configuración | Separación (mín. genuino − máx. impostor) |
|---|---|
| **Actual (detección Haar + CLAHE + coseno)** | **+0.0874** |
| Detección forzada multiescala + rotaciones | −0.1446 |
| Añadiendo alineación canónica por ojos | −0.2128 |
| Añadiendo normalización Tan-Triggs | −0.0574 |

**Ninguna de las mejoras "estándar" mejoró nada en esta prueba.** Se probaron y se
descartaron por evidencia, no por criterio. Con solo dos identidades no es posible
distinguir una mejora real de un artefacto, así que el descriptor se dejó como
estaba y el esfuerzo se puso en la puerta de calidad, que sí es defendible sin
conjunto de datos.

---

## Calibración de umbrales

**Los umbrales por defecto son provisionales.** Están fijados a partir de dos
imágenes de prueba y de locutores sintéticos, no de un conjunto real. Antes de
usar el servicio con personas de verdad hay que recalibrar.

### Rostro

```bash
python scripts/calibrate_face.py datos_cara 0.70
```

Estructura esperada:

```
datos_cara/
  maria/   foto1.jpg  foto2.jpg  foto3.jpg
  andres/  foto1.jpg  foto2.jpg
  ...
```

El script compara todos los pares dentro de cada persona (genuinos) y entre
personas distintas (impostores), e informa del umbral de igual error (EER), del
FAR y del FRR con el umbral actual. Para un portal conviene subir el umbral por
encima del EER: es preferible pedir un segundo intento que dejar entrar a un
impostor.

Conviene usar fotos de **sesiones distintas** (otro día, otra luz, otra ropa). Las
variaciones de una misma foto dan una similitud genuina artificialmente alta y
producen un umbral demasiado optimista.

### Voz

```bash
python scripts/calibrate_voice.py datos_voz
```

Estructura esperada:

```
datos_voz/
  maria/   toma1.wav  toma2.wav  toma3.wav
  andres/  toma1.wav  toma2.wav
  ...
```

La primera toma de cada carpeta se usa como matrícula y el resto como intentos
genuinos; las tomas de las demás personas actúan como impostores. El script
informa del EER por separado para el z-score y para el ratio de cohorte.

### Parpadeo

El umbral `BLINK_CLOSED_RATIO` de `liveness.py` no se ha podido validar con
parpadeos reales. Para ajustarlo, guarda los frames de una captura propia y
ejecuta:

```bash
python scripts/diagnose_liveness.py frames_liveness
```

Imprime la señal de apertura de cada frame junto al umbral de corte, de forma que
se ve directamente si el parpadeo lo cruza.

---

## Scripts

| Script | Qué hace |
|---|---|
| `create_db.py` | Crea la base de datos en PostgreSQL si no existe. |
| `migrate_voice.py` | Añade las columnas de calibración y limpia plantillas de voz obsoletas. |
| `synth.py` | Genera locutores sintéticos para probar sin micrófono. |
| `test_voice.py` | Suite de matrícula y verificación de locutor. |
| `test_liveness.py` | Suite de ataques de presentación y parpadeo. |
| `test_lbph.py` | Comprobaciones del descriptor LBPH. |
| `test_separation.py` | Similitud genuino/impostor con las imágenes de ejemplo. |
| `bench_metrics.py` | Compara métricas de distancia bajo distintas transformaciones. |
| `bench_voice.py` | EER de voz con locutores sintéticos: GMM vs UBM-MAP. |
| `bench_face.py` | Separación facial bajo 15 degradaciones controladas. |
| `test_replay.py` | Demuestra que una voz reproducida por altavoz se acepta. |
| `test_api.py` | Prueba manual de los endpoints faciales. |
| `test_full_api.py` | Suite de integración completa contra un servidor en marcha. |
| `calibrate_face.py` | Calcula FAR/FRR/EER faciales con datos reales. |
| `calibrate_voice.py` | Calcula FAR/FRR/EER de voz con datos reales. |
| `diagnose_liveness.py` | Vuelca la señal de apertura ocular frame a frame. |

`test_full_api.py` **borra todos los usuarios** como paso de limpieza. No lo
ejecutes contra una base con datos que quieras conservar. Acepta `BASE_URL`,
`PORTAL_USER` y `PORTAL_PASSWORD` como variables de entorno.

---

## Limitaciones conocidas

Estas son limitaciones reales del diseño, no defectos pendientes de arreglo.

- **Los umbrales no están calibrados con datos reales.** Ver
  [Calibración](#calibración-de-umbrales). Es lo primero que debe hacerse.
- **El liveness solo cubre ataques de fotografía.** Detecta un parpadeo, y eso
  descarta una foto impresa o en pantalla. **No** detecta un vídeo de la persona
  parpadeando, ni una máscara, ni un deepfake. Un sistema de producción necesita
  análisis de textura, luz estructurada o profundidad.
- **La verificación de voz sigue siendo débil en términos absolutos.** El
  UBM-MAP la mejoró de 36.2 % a 19.9 % de EER, pero **un 20 % de EER significa que
  uno de cada cinco intentos se clasifica mal** en el punto de igual error. Con
  grabaciones de 3-5 segundos y un GMM diagonal no se llega mucho más lejos; los
  sistemas actuales usan embeddings neuronales (x-vectors, ECAPA). Para decisiones
  sensibles usa el modo **Rostro + Voz**.
- **La voz necesita población.** El UBM exige al menos 2 locutores de fondo
  distintos. Con uno o dos usuarios el sistema cae al modo de reserva, que es
  sustancialmente peor. Registra al menos 3 usuarios con voz.
- **La detección falla con la cara girada.** `haarcascade_frontalface` solo
  encuentra rostros de frente. Sobre 14 fotos reales de webcam, **7 no se
  detectaron** por giro de cabeza. Ninguna cascada de OpenCV (`alt`, `alt2`,
  `alt_tree`, `profileface`) las recupera de forma fiable, y aflojar
  `scaleFactor`/`minNeighbors` produce **falsos positivos sobre el fondo** en vez
  de detecciones buenas: en una prueba la cascada devolvió la puerta de madera de
  la pared. Arreglarlo de verdad exige un detector DNN (YuNet o similar), no
  ajustar parámetros.
- **El reconocimiento depende críticamente de cómo se registró el usuario.** Ver
  [Rendimiento medido](#rendimiento-medido). Si la matrícula no cubre condiciones
  variadas, no hay umbral que funcione. El filtro de redundancia mitiga el caso
  peor, pero no sustituye a un registro hecho con cuidado.
- **Las mejoras habituales de LBPH no ayudaron.** Alineación canónica por ojos,
  Tan-Triggs y detección multiescala se probaron y **empeoraron** la separación,
  así que no se incluyeron.
- **Las plantillas se guardan sin cifrar.** `voice_templates.features` contiene
  MFCC crudos, de los que puede reconstruirse información de la voz. Un despliegue
  real necesita cifrado en reposo con gestión de claves.
- **El anti-replay vive en memoria del proceso.** Funciona con una sola instancia;
  con varios workers o réplicas haría falta un almacén compartido tipo Redis. Lo
  mismo aplica al rate limiter.
- **El anti-replay compara bytes exactos, y eso deja abierto el ataque real.**
  Detiene el reenvío literal de una captura, pero **no** detecta una grabación
  reproducida por altavoz ni un vídeo mostrado a la cámara. Medido con
  `scripts/test_replay.py`: una grabación genuina pasada por altavoz y micrófono
  puntúa 5.48 de LLR frente a un umbral de 0.4, es decir, **se acepta**. Esto no
  es un fallo de calibración: un GMM modela *quién* habla, no *si está vivo*.
  Cerrarlo exige un detector de suplantación aparte (análisis de la banda alta,
  artefactos de altavoz, reverberación, o un desafío de texto aleatorio).
- **Un único juego de credenciales para todo el portal.** Quien tenga
  `PORTAL_USER`/`PORTAL_PASSWORD` puede listar y borrar cualquier usuario. No hay
  roles ni auditoría.
- **`eigenfaces.py` no se usa.** Está implementado y es funcional, pero la API
  emplea LBPH. Se conserva como material del proyecto.
- **Un login facial cuesta ~1.8 s de CPU** para 28 frames. Se atiende en el pool
  de hilos, así que no bloquea el servidor, pero limita el número de logins
  simultáneos por instancia.
