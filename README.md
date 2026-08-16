# Login Biométrico — Rostro y Voz

Microservicio de autenticación biométrica construido con FastAPI. Está pensado
para usarse **desde otros sistemas**: cada sistema cliente se autentica con su
propia API key y recibe el `uuid` del usuario como identificador estable para
vincularlo con sus propios registros.

El reconocimiento de **voz** está implementado desde cero sobre NumPy (MFCC,
GMM-EM, UBM-MAP). El reconocimiento **facial** usa dos redes ONNX ejecutadas por
OpenCV y ONNX Runtime: **YuNet** para detectar (MIT), **SFace** para el embedding
de identidad (Apache 2.0) y **OpenSeeFace** para los 66 landmarks faciales que
sostienen la deteccion de parpadeo (BSD 2-clause). Las tres se ejecutan
localmente, sin llamadas externas.

> Este servicio trata **datos biométricos**, que la Ley 1581 de Colombia
> clasifica como dato sensible. Requieren autorización previa, explícita e
> informada del titular. Ver [Limitaciones conocidas](#limitaciones-conocidas).

---

## Índice

1. [Arquitectura](#arquitectura)
2. [Instalación y arranque](#instalación-y-arranque)
3. [Configuración (.env)](#configuración-env)
4. [Cómo funciona el reconocimiento facial](#cómo-funciona-el-reconocimiento-facial)
5. [Cómo funciona la detección de vida](#cómo-funciona-la-detección-de-vida-liveness)
6. [Protocolo de captura para el cliente](#protocolo-de-captura-para-el-cliente-cualquier-lenguaje)
7. [Cómo funciona el reconocimiento de voz](#cómo-funciona-el-reconocimiento-de-voz)
8. [Modelo de seguridad](#modelo-de-seguridad)
9. [API](#api)
10. [Rendimiento medido](#rendimiento-medido)
11. [Calibración de umbrales](#calibración-de-umbrales)
12. [Scripts](#scripts)
13. [Limitaciones conocidas](#limitaciones-conocidas)

---

## Arquitectura

```
backend/
  main.py              app FastAPI, middlewares de acceso, montaje de estáticos
  config.py            configuración tipada leída de .env
  security.py          emisión/validación de JWT, anti-replay, rate limiting
  database.py          motor SQLAlchemy y sesión por petición
  models.py            tablas users, portal_users, api_clients, *_templates
  schemas.py           modelos de petición/respuesta de la API
  api_clients.py       resolución y caché de API keys contra la base de datos
  routers/
    portal.py          login de operadores y gestión de operadores
    clients.py         alta, listado, rotación y revocación de API keys
    auth.py            login por contraseña
    face.py            registro, verificación, login con liveness, identificación
    voice.py           registro y verificación de locutor
    users.py           alta combinada, consulta por uuid, listado y borrado
  biometrics/
    face/
      embedder.py      YuNet + SFace (ONNX), instancias por hilo
      landmarks.py     66 landmarks faciales (OpenSeeFace) y Eye Aspect Ratio
      detector.py      decodificación, recorte y normalización para calidad
      liveness.py      señal de apertura ocular y detección de parpadeo
      quality.py       puerta de calidad de captura (nitidez, tamaño, contraste)
      models/          pesos ONNX (fuera de git, ver scripts/fetch_models.py)
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

### Versión de Python

El proyecto está desarrollado y probado sobre **Python 3.12** (en concreto
3.12.10). No es una preferencia: `numpy 2.2.1` y `opencv-python 4.10.0.84`
publican ruedas precompiladas para 3.12, y en otras versiones `pip` intenta
compilar desde fuente y la instalación falla.

**Si algo falla en la instalación o al arrancar, lo primero que hay que
comprobar es la versión de Python.** Debe responder `3.12.x`:

```bash
.venv\Scripts\python.exe --version
```

### Gestionar varias versiones de Python en Windows

Windows permite tener varias versiones instaladas a la vez y elegir cuál usa cada
proyecto mediante el **lanzador `py`**, que viene con el instalador oficial:

```powershell
winget install Python.Python.3.12
```

Instalado así, `py` queda disponible y se pueden listar y elegir versiones:

```powershell
py -0p              # lista todas las versiones instaladas y su ruta
py -3.12 --version  # comprueba que la 3.12 está disponible
```

> **Aviso.** Si instalaste Python desde la **Microsoft Store**, el lanzador `py`
> **no** se instala y `py -3.12 ...` fallará con «py no se reconoce». La Store
> además redirige rutas de escritura a una carpeta virtualizada, lo que complica
> los despliegues. Para producción usa la versión de `winget` (o el instalador de
> [python.org](https://www.python.org/downloads/)) y marca «Add python.exe to
> PATH». Puedes comprobar de dónde salió tu entorno mirando la línea `home` de
> `.venv/pyvenv.cfg`.

### Puesta en marcha

```bash
py -3.12 -m venv .venv        # o: python -m venv .venv  (si ya es 3.12)
.venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env          # y rellena los valores obligatorios

python scripts/fetch_models.py    # descarga YuNet, SFace y landmarks (~52 MB)
python scripts/create_db.py       # crea la base en PostgreSQL
python scripts/migrate_v05.py     # uuid de usuario, operadores y API keys
python scripts/migrate_voice.py   # columnas de calibración de voz

uvicorn backend.main:app --reload
```

`fetch_models.py` es **obligatorio antes del primer arranque**: los pesos ONNX no
están versionados en git (pesan 52 MB) y el servicio se niega a arrancar si
faltan, con un mensaje que remite a ese script. Se guardan en
`backend/biometrics/face/models/`, dentro del proyecto. Es idempotente: si los
ficheros ya están y su tamaño coincide, no vuelve a descargarlos.

El portal queda en `http://127.0.0.1:8000`. Las rutas `/docs`, `/redoc` y
`/openapi.json` piden Basic Auth con las credenciales de `.env`.

Los scripts de prueba que hablan con la API por HTTP necesitan además
`pip install requests`.

`onnxruntime` (MIT) es una dependencia nueva: OpenCV no puede cargar el modelo de
landmarks, que usa operadores propios de ONNX Runtime.

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

`PORTAL_USER` / `PORTAL_PASSWORD` ya **no son la credencial permanente**: solo
crean el primer operador en la base de datos si la tabla está vacía. A partir de
ahí los operadores se gestionan desde el portal y las credenciales viven
hasheadas en `portal_users`. Ver [Modelo de seguridad](#modelo-de-seguridad).

| Variable | Por defecto | Qué hace |
|---|---|---|
| `DATABASE_URL` | — | Cadena de conexión de SQLAlchemy. Obligatoria. |
| `DB_POOL_SIZE` | `20` | Conexiones permanentes del pool. |
| `DB_MAX_OVERFLOW` | `40` | Conexiones adicionales bajo carga. |
| `DB_POOL_RECYCLE` | `1800` | Segundos tras los que se recicla una conexión. |
| `JWT_SECRET` | — | Clave de firma de los tokens. Obligatoria. |
| `JWT_ALGORITHM` | `HS256` | Algoritmo de firma. |
| `JWT_EXPIRE_MINUTES` | `60` | Vigencia del token del portal. |
| `SESSION_EXPIRE_MINUTES` | `15` | Vigencia del token de sesión de usuario. |
| `API_KEY_PEPPER` | vacío | Pimienta del hash de las API keys. Vacío = usa `JWT_SECRET`. |
| `API_KEY_DEFAULT_DAYS` | `365` | Caducidad por defecto de una API key nueva. |
| `FACE_THRESHOLD` | `0.363` | Similitud coseno mínima para aceptar un rostro. |
| `VOICE_LLR_THRESHOLD` | `0.4` | Log-verosimilitud mínima frente al UBM (vía principal). |
| `VOICE_Z_THRESHOLD` | `-2.5` | z-score mínimo (solo en el modo de reserva). |
| `VOICE_RATIO_THRESHOLD` | `-3.0` | Ventaja mínima sobre la cohorte (modo de reserva). |
| `LIVENESS_MIN_FACES` | `6` | Frames con rostro necesarios para evaluar el parpadeo. |
| `LIVENESS_MAX_GAP_RATIO` | `0.4` | Fracción máxima de frames sin rostro admitida. |
| `REPLAY_WINDOW_SECONDS` | `300` | Ventana en la que se rechaza una captura repetida. |
| `AUTH_RATE_LIMIT` | `10` | Intentos de login permitidos por ventana. |
| `AUTH_RATE_WINDOW_SECONDS` | `60` | Duración de la ventana de rate limiting. |
| `CORS_ORIGINS` | vacío | Orígenes permitidos, separados por comas. Vacío = solo mismo origen. |
| `PORTAL_USER` / `PORTAL_PASSWORD` | — | Operador inicial, solo si no hay ninguno. Obligatorias. |
| `DOCS_USER` / `DOCS_PASSWORD` | heredan del portal | Credenciales de la documentación. |

---

## Cómo funciona el reconocimiento facial

### 1. Detección con YuNet (`embedder.py`)

`cv2.FaceDetectorYN` ejecuta la red YuNet sobre la imagen en color y devuelve,
por cada rostro, su caja y **cinco puntos de referencia**: los dos ojos, la nariz
y las dos comisuras de la boca. Se conserva el rostro de mayor área.

Las redes de OpenCV **no son seguras entre hilos**, y FastAPI ejecuta estos
endpoints en un pool de hilos. Por eso el módulo mantiene una instancia por hilo
(`threading.local`) en lugar de una global compartida.

### 2. Embedding de identidad con SFace

`cv2.FaceRecognizerSF` alinea el rostro usando los cinco puntos (`alignCrop`) y
produce un vector de **128 dimensiones**, que se normaliza L2. La identidad se
compara con el **producto escalar** de dos vectores normalizados, es decir la
similitud coseno, en el rango −1 a 1.

Alinear por landmarks en vez de por proporciones fijas es lo que permite tolerar
giros de cabeza: el recorte queda canónico independientemente de la pose.

### 3. Por qué se sustituyó el descriptor LBPH anterior

Las versiones previas usaban un descriptor LBPH artesanal de 7552 dimensiones.
Se retiró tras medirlo con **14 fotos reales de webcam** de una misma persona:

| | LBPH | YuNet + SFace |
|---|---|---|
| Fotos detectadas | 7 / 14 | **13 / 14** |
| Separación (3 plantillas de una misma sesión) | **−0.0105** | — |
| Separación (3 plantillas de sesiones distintas) | +0.2194 | **+0.2268** |

Los dos hallazgos que motivaron el cambio:

- **LBPH no detectaba ninguna foto con la cabeza girada.** Las cascadas Haar solo
  responden a rostros frontales, y aflojar sus parámetros producía falsos
  positivos sobre el fondo (llegó a detectar una puerta de madera como rostro).
- **Con fotos de una misma sesión la separación era negativa**, es decir, no
  existía ningún umbral válido: dos fotos consecutivas de la misma persona se
  parecían entre sí un 0.94–0.96, pero dos fotos suyas de momentos distintos solo
  un 0.57–0.71. LBPH medía la iluminación y la pose tanto como la identidad.

SFace es además mucho más compacto: 128 dimensiones frente a 7552, lo que reduce
en ~59× el almacenamiento de plantillas y el coste de comparar.

### 4. Varias plantillas por usuario

Cada usuario puede tener varias plantillas (el portal captura 3 fotos) y la
verificación toma el **máximo** de las similitudes contra todas ellas.

Al matricular se descartan las fotos casi idénticas: si una supera una similitud
de `0.90` con otra ya aceptada, no aporta información nueva y se rechaza. El
portal guía al usuario para que las tres capturas varíen en pose e iluminación.

### 5. Puerta de calidad (`quality.py`)

Una captura mala no produce un error honesto: produce un descriptor degradado.
Dos caras **distintas** pero ambas borrosas se parecen más entre sí que una cara
nítida y su versión borrosa. Por eso el servicio **rechaza la captura** en lugar
de puntuarla, con un mensaje accionable:

| Métrica | Mínimo | Motivo |
|---|---|---|
| Lado del rostro | 80 px | Rostro lejano: pocos píxeles para el embedding. |
| Nitidez (varianza del laplaciano) | 70 | El desenfoque es el mayor destructor de identidad. |
| Contraste (desviación típica) | 22 | Sin contraste no hay estructura que medir. |
| Píxeles quemados o negros | < 28 % | Contraluz o sobreexposición. |

El umbral de nitidez está en 70 porque una webcam con la cabeza en movimiento
puntúa 106.9: un corte más alto rechazaba capturas legítimas. Como referencia,
las 14 fotos reales de prueba puntúan entre 79 y 306, y dan un lado de rostro de
400–500 px.

La caja de YuNet es **más ajustada** que la de las cascadas Haar anteriores, que
se expandían artificialmente un 12 % en horizontal y un 6 % en vertical. El mismo
umbral de 80 px es por tanto algo más estricto que antes.

En el login facial la puerta se aplica **por frame**: los frames borrosos se
descartan para la identidad, pero siguen contando para el liveness.

---

## Cómo funciona la detección de vida (liveness)

El objetivo es distinguir una persona presente de una fotografía. El cliente graba
una ráfaga de ~28 frames en 2.6 s y **le indica al usuario el momento exacto de
parpadear**. Ese aviso no es cosmético: sin él, los parpadeos caen en cualquier
punto de la ráfaga y una parte se vuelve indetectable (ver más abajo).

### La señal de apertura: Eye Aspect Ratio

La apertura de cada ojo se mide con el **Eye Aspect Ratio**, calculado sobre los
seis puntos del contorno del párpado que da el modelo de landmarks:

```
EAR = (‖p2−p6‖ + ‖p3−p5‖) / (2 · ‖p1−p4‖)
```

Es decir, la altura del ojo dividida por su anchura. La señal final es la media
de ambos ojos. Medido sobre fotos reales: **ojos cerrados 0.065–0.068, ojos
abiertos 0.220–0.394**, sin solape.

Lo decisivo es que el EAR mide **geometría**, no contraste.

### Por qué no basta con medir contraste

La versión anterior usaba la energía de bordes de la banda ocular, normalizada
contra la banda de la boca. Funcionaba con buena luz y **fallaba sistemáticamente
con luz media**. La causa, medida sobre las mismas capturas:

| Sesión | Energía ojo abierto | Energía ojo cerrado | Rango útil |
|---|---|---|---|
| Buena luz | 30–32 | 24–25 | 20–24 % |
| Luz media | 21–23 | 19–21 | 9–11 % |

La energía de la boca (el denominador) se mantenía estable; lo que se hundía era
el ojo **abierto**. Al bajar la luz se pierde justo lo que hace "ruidoso" a un ojo
abierto —el borde del iris, la frontera con la esclerótica, el reflejo especular—
mientras que el párpado cerrado es piel con textura, y la textura sobrevive mucho
mejor. El techo de la señal caía y el suelo se quedaba: el margen se partía por la
mitad, hasta quedar pegado al 6 % que produce la deriva por movimiento.

Se probaron y **descartaron por evidencia** dos correcciones: restar el suelo de
ruido del sensor (estimador de Immerkær) no movía la aguja, y amplificar el
contraste local con CLAHE lo **empeoraba**, porque realza la textura del párpado
cerrado tanto como las estructuras del ojo abierto.

Por eso la señal pasó a ser geométrica. La forma del párpado no depende de la luz.

### La detección del parpadeo

Un frame se marca *cerrado* si su señal baja del `BLINK_CLOSED_RATIO` (75 %) del
percentil 80 de la ráfaga: umbral relativo, para adaptarse a cada cámara y luz.
Se acepta un parpadeo cuando concurren tres condiciones:

1. Patrón **abierto → cerrado → abierto**, con al menos 2 frames cerrados
   consecutivos y 1 frame abierto a cada lado.
2. **Profundidad mínima de la caída** (`MIN_BLINK_DROP`, 25 %) respecto al mejor
   valor de los 2 frames vecinos a cada lado.
3. Ningún frame de la racha descartado por movimiento.

La condición 2 es la que distingue un parpadeo de una deriva lenta de la señal.
Medido sobre ráfagas reales etiquetadas a mano:

| Ráfaga | EAR mínimo | ¿Parpadeo real? |
|---|---|---|
| con parpadeo (8 ráfagas) | 0.070 – 0.099 | sí |
| sin parpadeo (3 ráfagas) | 0.222 – 0.268 | no |

Separación total. El acierto es 11/11 **en toda la rejilla de parámetros
probada** (`BLINK_CLOSED_RATIO` de 0.65 a 0.85, `MIN_BLINK_DROP` de 0.15 a 0.35),
así que los valores por defecto no están en el filo de nada.

**Solo se exige 1 frame abierto antes del cierre, no 2.** Exigir 2 hacía
estructuralmente indetectables los parpadeos que empiezan al principio de la
ráfaga: en las pruebas reales, 2 de cada 7 parpadeos caían ahí y **ninguna
combinación de señal o umbral podía detectarlos**.

**Los frames sin rostro no cuentan como ojos cerrados.** Se marcan como huecos e
interrumpen cualquier racha. Tratarlos como "cerrado" era explotable: agitar una
foto impresa hace fallar la detección dos frames seguidos y eso bastaba para
simular un parpadeo. Se rechaza además la ráfaga completa si más del 40 % de los
frames carecen de rostro, la firma de una foto en movimiento.

### Descarte por movimiento

Si el centro de los ojos se desplaza más de `MAX_MOTION_RATIO` (22 % de la
distancia interocular) entre dos frames consecutivos, el frame se descarta. El
desenfoque de movimiento destruye los bordes oculares igual que un párpado, y sin
este filtro un giro brusco de cabeza se leía como parpadeo.

La respuesta de `/api/face/login` incluye `n_usable` y `n_moved` para que el
cliente pueda decirle al usuario que se quede quieto.

---

## Protocolo de captura para el cliente (cualquier lenguaje)

El servicio es una API: el portal incluido es solo una implementación de
referencia. Cualquier front —web, Android, iOS, escritorio— debe respetar este
protocolo, porque **los umbrales de liveness están calibrados sobre él**.

### Parámetros de la ráfaga

| Parámetro | Valor | Por qué |
|---|---|---|
| Duración | 2.6 s | Margen para abierto → cerrado → abierto sin cansar al usuario. |
| Cadencia | ~11 fps (28 frames) | Un parpadeo dura 100–400 ms: a 11 fps deja 2–4 frames cerrados, y el mínimo exigido es 2. |
| Resolución | 640×480 o superior | El rostro debe dar al menos 80 px de lado tras el recorte. |
| Formato | JPEG, calidad ≈ 0.85 | Compresión mayor destruye los bordes que mide la señal. |
| Orden | estrictamente cronológico | La detección es temporal; desordenar los frames la invalida. |

Bajar de ~8 fps hace que un parpadeo normal ocupe menos de 2 frames y deje de
detectarse. Subir de ~15 fps no aporta y multiplica el coste de subida.

### Secuencia que debe implementar el cliente

```
1. Abrir la cámara y mostrar la vista previa.
2. Cuenta atrás de 3 s con el mensaje "Mantén los ojos abiertos".
   (Evita que el usuario parpadee antes de que empiece la grabación.)
3. Empezar a grabar. Mostrar "Grabando · ojos abiertos".
4. Al 45 % de la ráfaga (~1.2 s), mostrar un aviso BIEN VISIBLE:
   "PARPADEA AHORA".
   Debe destacar: color de acento, tamaño grande, sobre la vista previa.
5. Terminar la ráfaga, cerrar la cámara y enviar los frames.
```

El aviso del paso 4 es **obligatorio**. Sin él el usuario parpadea al azar y una
fracción de los intentos cae al principio de la ráfaga, donde la detección es
menos fiable. El portal lo implementa en `static/app.js` (`captureBurst` con
`BLINK_CUE_AT = 0.45`) y `record_blink.py` hace lo mismo por consola.

### Envío

`POST /api/face/login`, `multipart/form-data`:

| Campo | Contenido |
|---|---|
| `username` | nombre de usuario |
| `frames` | **repetido**, un JPEG por frame, en orden |

```bash
curl -X POST http://TU_HOST/api/face/login   -H "X-API-Key: lbs_..."   -F "username=maria"   -F "frames=@f000.jpg" -F "frames=@f001.jpg" -F "frames=@f002.jpg"
```

### Respuesta

```json
{
  "verified": true,
  "username": "maria",
  "uuid": "3f25ea28-...",
  "liveness_passed": true,
  "similarity": 0.83,
  "threshold": 0.363,
  "n_frames": 28,
  "n_faces": 28,
  "n_usable": 26,
  "n_moved": 2,
  "blink_detected": true,
  "access_token": "eyJ...",
  "expires_in": 900,
  "reason": null
}
```

Guarda el `uuid`: es el identificador estable del usuario. Cuando `verified` es
`false`, `reason` trae un mensaje ya redactado para mostrar tal cual al usuario.

### Cómo reaccionar a cada fallo

| Situación | Qué hacer en el cliente |
|---|---|
| `n_faces` mucho menor que `n_frames` | Pedir que mire de frente y mejore la luz. |
| `n_moved` alto / `n_usable` bajo | Pedir que se quede quieto y repetir. |
| `blink_detected` false | Repetir insistiendo en parpadear **con el aviso**. |
| `similarity` bajo el umbral | No es un problema de captura: la cara no coincide. |
| HTTP 409 | Ráfaga repetida (anti-replay). Hay que grabar de nuevo, no reenviar. |
| HTTP 429 | Demasiados intentos. Esperar antes de reintentar. |

**Nunca reenvíes la misma ráfaga.** El servicio guarda su hash y devuelve 409:
es la protección contra capturar el tráfico de un login válido y repetirlo.

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

### La población de fondo: el punto más frágil del sistema

Esta es la parte que más fácilmente se rompe en la práctica, y casi siempre por
los **datos**, no por el código. Conviene leerla entera antes de poner voz en
producción.

El servicio tiene tres regímenes según cuántos **locutores de fondo** haya, es
decir, cuántos usuarios con voz registrada distintos del que se verifica:

| Locutores de fondo | Modo (`scoring`) | Qué decide | Fiabilidad |
|---|---|---|---|
| 2 o más | `ubm-map` | LLR contra el UBM | ~20 % EER (el modo bueno) |
| 1 | `gmm-z` | z-score **y** ratio contra esa única voz | mala, y depende de quién sea esa voz |
| 0 | `gmm-z` | solo z-score (`ratio` es `None`) | inservible |

La respuesta de `/api/voice/verify` indica siempre cuál se usó en `scoring` y
cuántos había en `n_background_speakers`. **Compruébalo**: si no pone `ubm-map`,
la verificación no es de fiar.

#### Varias grabaciones de la misma persona NO cuentan

«Locutores distintos» significa **personas distintas**. Registrar tres veces tu
propia voz con tres nombres de usuario no activa nada útil: al contrario, lo
empeora.

El UBM es un *Universal Background Model*, o sea el modelo de «cualquier otra
persona». La decisión es una resta:

```
LLR = log P(audio | modelo del usuario) − log P(audio | modelo de fondo)
```

Si el modelo de fondo es la misma persona, la resta se anula y el sistema deja de
discriminar. Medido troceando una grabación real en tres para simularlo:

| Fondo del UBM | LLR genuino | LLR impostor | Margen |
|---|---|---|---|
| La misma voz (3 trozos) | 10.94 | **+3.92** | 7.03 |
| Una voz distinta | 15.50 | −4.86 | 20.36 |

Con el umbral en `0.4`, el impostor de la primera fila **entra**.

#### Los locutores sintéticos contaminan la cohorte

`scripts/synth.py` genera locutores sintéticos para poder probar sin micrófono, y
`scripts/test_full_api.py` deja un usuario `alice` con voz sintética. **Son datos
de prueba y no deben convivir con usuarios reales.**

Si la única voz de fondo es sintética, el sistema compara a la persona que se
autentica contra un tono generado por ordenador y concluye —correctamente— que se
parece más a sí misma que a un sintetizador. El ratio sale enorme y **acepta a
cualquiera**. Es un fallo silencioso: la API responde `verified: true` sin ninguna
señal de alarma.

Antes de registrar personas reales, borra los usuarios de prueba:

```bash
curl -X DELETE http://TU_HOST/api/users/alice -H "Authorization: Bearer <token>"
```

#### El z-score por sí solo no separa

En el modo de reserva sin cohorte, la única barrera es `VOICE_Z_THRESHOLD`
(`-2.5`). Medido con datos reales del repositorio, un impostor puntuó **−2.444**:
pasa el umbral por **0.056**. Y bajo adaptación MAP el z-score mide **50.4 % de
EER**, que es exactamente lanzar una moneda.

Dicho de otro modo: cuando `scoring` vale `gmm-z` y `ratio` es `None`, el servicio
no está verificando al locutor de forma significativa.

#### Recomendación

- **Para probar:** al menos 3 personas reales distintas con voz registrada, y cero
  usuarios sintéticos en la misma base.
- **Para producción:** un **UBM congelado** entrenado sobre un corpus público
  (Mozilla Common Voice es CC0 y tiene español). Resuelve además el problema de
  escala: hoy se entrena un UBM por usuario (*leave-one-out*), que es O(N).

Nota histórica: cuando había menos de dos usuarios, la cohorte llegó a construirse
con la **propia voz del objetivo**, comparando al usuario consigo mismo. Eso se
eliminó, pero el caso de la voz sintética es la misma clase de error con otro
disfraz: un fondo que no representa a «los demás».

---

## Modelo de seguridad

### Tres formas de acceder

| Credencial | Cabecera | Quién la usa |
|---|---|---|
| Token de portal (JWT, scope `portal`) | `Authorization: Bearer …` | Operadores humanos del portal web. |
| API key | `X-API-Key: lbs_…` | Sistemas clientes (hoteles, gestión, etc.). |
| Token de sesión (JWT, scope `user`) | — | Identifica al usuario final ante el sistema cliente. |

El token de **sesión** se emite al superar una autenticación (contraseña, rostro
o voz) y **no sirve** para acceder a `/api/*`: el middleware exige explícitamente
`scope == "portal"`. Caduca en `SESSION_EXPIRE_MINUTES` (15 por defecto) e
incluye el `uuid` del usuario en el campo `uid`, para que el sistema cliente
pueda vincularlo con sus propios registros.

### Operadores del portal

Los operadores viven en la tabla `portal_users` con la contraseña hasheada con
bcrypt. `PORTAL_USER` / `PORTAL_PASSWORD` de `.env` solo **siembran el primer
operador** cuando la tabla está vacía; después son irrelevantes. Desde el portal
un operador puede crear otros, cambiar su contraseña y desactivarlos.

No se puede desactivar el último operador activo: el servicio devuelve 409 en vez
de dejar el portal inaccesible.

### API keys por sistema cliente

Cada sistema que consuma el servicio recibe su propia API key, creada desde el
portal. El formato es `lbs_<prefijo>_<secreto>`:

- El **prefijo** es lo que se busca en la base de datos (columna indexada).
- El **secreto** nunca se almacena. Solo se guarda su HMAC-SHA256 con la pimienta
  `API_KEY_PEPPER`, y se compara en tiempo constante.
- La clave completa **se muestra una sola vez**, al crearla. No hay forma de
  recuperarla después; si se pierde, se rota.

Cada key lleva **permisos** y **caducidad**:

| Permiso | Qué habilita |
|---|---|
| `auth` | Verificar, login e identificar. Es el uso normal de un sistema cliente. |
| `enroll` | Además, dar de alta usuarios. |
| `admin` | Además, listar y borrar usuarios y gestionar keys. Concédelo con cuidado. |

Una key sin el permiso que exige la ruta recibe 403, no 401: el fallo es de
autorización, no de identidad. Las keys se pueden **revocar** (desactivar) o
**rotar** (nueva clave, la anterior deja de valer al instante).

Para no consultar la base de datos en cada petición, las keys se cachean 60 s en
memoria. Ver la nota sobre despliegue con varios procesos en
[Limitaciones conocidas](#limitaciones-conocidas).

### Identificador público de usuario

Cada usuario tiene un `uuid` estable, independiente de su `id` interno y de su
nombre. Es el identificador que deben guardar los sistemas clientes para vincular
a la persona, y se devuelve en el alta, en las verificaciones correctas y en
`GET /api/users/by-uuid/{uuid}`. Exponer el `id` autoincremental habría filtrado
cuántos usuarios hay dados de alta.

### Protecciones implementadas

- **Contraseñas en el cuerpo de la petición.** `/api/auth/login` recibe un JSON;
  antes iban como parámetros de consulta y quedaban registrados en los logs de
  acceso, el historial del navegador y cualquier proxy intermedio.
- **Comparación en tiempo constante** (`hmac.compare_digest`) para las
  credenciales de la documentación y para el secreto de las API keys.
- **Alta de usuario a prueba de carreras.** Dos peticiones simultáneas con el
  mismo nombre pasaban ambas la comprobación previa de existencia y la segunda
  reventaba con un 500 de PostgreSQL. Ahora se captura `IntegrityError` y se
  devuelve 409. El portal además bloquea el botón mientras envía.
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

Todas las rutas `/api/*` salvo `/api/portal/auth` exigen **o** un token de portal
(`Authorization: Bearer …`) **o** una API key (`X-API-Key: lbs_…`) con el permiso
que indica la columna «Permiso».

Ejemplo de llamada desde un sistema cliente:

```bash
curl -X POST http://127.0.0.1:8000/api/face/verify \
  -H "X-API-Key: lbs_a1b2c3d4e5f6_EL_SECRETO" \
  -F "username=maria" -F "image=@foto.jpg"
```

| Método | Ruta | Permiso | Descripción |
|---|---|---|---|
| `POST` | `/api/portal/auth` | — | Login de operador. Devuelve token con scope `portal`. |
| `GET` | `/api/portal/me` | `auth` | Datos del operador del token actual. |
| `GET` | `/api/portal/users` | `admin` | Lista de operadores del portal. |
| `POST` | `/api/portal/users` | `admin` | Crea un operador. |
| `POST` | `/api/portal/users/{uuid}/disable` | `admin` | Desactiva un operador. |
| `POST` | `/api/portal/users/{uuid}/password` | `admin` | Cambia la contraseña de un operador. |
| `POST` | `/api/clients` | `admin` | Crea una API key. Devuelve la clave **una sola vez**. |
| `GET` | `/api/clients` | `admin` | Lista de sistemas cliente y estado de sus keys. |
| `POST` | `/api/clients/{uuid}/revoke` | `admin` | Desactiva una API key. |
| `POST` | `/api/clients/{uuid}/rotate` | `admin` | Genera una clave nueva e invalida la anterior. |
| `POST` | `/api/auth/login` | `auth` | Login por contraseña (JSON). Devuelve token de sesión. |
| `POST` | `/api/users/register` | `enroll` | Alta con contraseña, fotos y/o audio. |
| `GET` | `/api/users` | `admin` | Lista de usuarios y sus plantillas. |
| `GET` | `/api/users/by-uuid/{uuid}` | `auth` | Consulta un usuario por su identificador público. |
| `DELETE` | `/api/users/{username}` | `admin` | Borra usuario y plantillas en cascada. |
| `POST` | `/api/face/register` | `enroll` | Alta solo con rostro. |
| `POST` | `/api/face/verify` | `auth` | Compara una foto contra un usuario. |
| `POST` | `/api/face/login` | `auth` | Login con ráfaga de frames y liveness. Devuelve token. |
| `POST` | `/api/face/identify` | `auth` | Busca a quién pertenece un rostro. |
| `GET` | `/api/face/templates` | `admin` | Lista de plantillas faciales. |
| `DELETE` | `/api/face/templates/{id}` | `admin` | Borra una plantilla facial. |
| `POST` | `/api/voice/register` | `enroll` | Registra o reemplaza la plantilla de voz. |
| `POST` | `/api/voice/verify` | `auth` | Verifica al locutor. Devuelve token si acepta. |
| `GET` | `/api/voice/templates` | `admin` | Lista de plantillas de voz. |
| `DELETE` | `/api/voice/templates/{id}` | `admin` | Borra una plantilla de voz. |

Las respuestas de login incluyen `reason` con una explicación legible cuando la
verificación falla, y `access_token` cuando tiene éxito.

> **Si consumes `/api/voice/verify`, comprueba `scoring`.** El servicio responde
> `verified: true` con normalidad aunque esté funcionando en modo degradado por
> falta de población de fondo. Trata como no fiable cualquier respuesta cuyo
> `scoring` no sea `"ubm-map"`, y revisa `n_background_speakers`. El porqué está en
> [La población de fondo](#la-población-de-fondo-el-punto-más-frágil-del-sistema).

---

## Rendimiento medido

Todas las cifras salen de los scripts del repositorio y son reproducibles.

### Rostro — `python scripts/calibrate_face.py datos_cara`

14 fotos reales de webcam de **una sola persona** más 3 impostores. YuNet detecta
13 de las 14 (la restante tiene un giro de cabeza extremo).

Modo de operación real (matrícula de 3 plantillas, se compara contra la mejor),
2860 comparaciones genuinas y 858 de impostor:

| Umbral | FRR (rechazo de genuinos) | FAR (aceptación de impostores) |
|---|---|---|
| 0.300 | 0.00 % | 0.00 % |
| **0.363** | **0.00 %** | **0.00 %** |
| 0.450 | 0.24 % | 0.00 % |
| 0.500 | 0.84 % | 0.00 % |

Peor genuino 0.4058, mejor impostor 0.2599: una separación de **+0.1460**, con el
umbral por defecto cómodamente en medio. El valor 0.363 es el que recomiendan los
autores de SFace, no uno ajustado a esta muestra, lo que reduce el riesgo de
sobreajustar a una sola persona.

**Con una sola persona genuina y 3 impostores estas cifras no son una promesa de
precisión en producción.** Un FAR del 0 % sobre 858 comparaciones acota el error
real por encima de ~0.3 %, no lo demuestra nulo. Recalibra con tus usuarios.

### Voz

Las cifras de voz son de **locutores sintéticos**, no de personas reales. Sirven
para comparar alternativas entre sí, no para prometer una precisión.

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

### Nota histórica sobre el descriptor anterior

Las mediciones que motivaron retirar LBPH están resumidas en
[Por qué se sustituyó el descriptor LBPH anterior](#3-por-qué-se-sustituyó-el-descriptor-lbph-anterior).
Los scripts que las produjeron (`bench_face.py`, `bench_metrics.py`,
`test_lbph.py`, `test_separation.py`) se eliminaron junto con el algoritmo.

---

## Calibración de umbrales

**Los umbrales por defecto son provisionales.** El facial está validado con una
sola persona y los de voz con locutores sintéticos. Antes de usar el servicio con
un grupo real de personas hay que recalibrar.

### Rostro

```bash
python scripts/calibrate_face.py datos_cara          # usa FACE_THRESHOLD del .env
python scripts/calibrate_face.py datos_cara 0.45     # o prueba otro umbral
```

Estructura esperada:

```
datos_cara/
  maria/   foto1.jpg  foto2.jpg  foto3.jpg
  andres/  foto1.jpg  foto2.jpg
  ...
```

El script informa de dos bloques. El de **todos los pares** compara cada foto con
cada otra. El de **modo real** reproduce lo que hace de verdad la API: matricula
3 fotos y compara el resto contra la mejor de las tres. **El segundo es el que
importa** para elegir umbral; el primero es más pesimista porque incluye pares
entre dos fotos malas que en producción nunca serían ambas plantillas.

Para un portal conviene subir el umbral por encima del EER: es preferible pedir
un segundo intento que dejar entrar a un impostor.

Usa fotos de **sesiones distintas** (otro día, otra luz, otra ropa). Esto no es
un consejo genérico: medido con las 14 fotos reales, matricular 3 fotos de una
misma sesión daba una separación **negativa** con el descriptor anterior, es
decir, ningún umbral funcionaba. Las capturas consecutivas se parecen entre sí
por la iluminación, no por la identidad, y producen un umbral engañosamente alto
que luego rechaza a la persona cualquier otro día.

Basta una carpeta con una sola foto para que esa persona cuente como impostor;
para medir genuinos hace falta al menos una carpeta con 2 o más.

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

Los umbrales están validados con 7 ráfagas reales de **una sola persona**,
etiquetadas frame a frame. Para recalibrar con otra cámara o con más gente:

```bash
python scripts/record_blink.py frames_liveness      # graba, avisando cuándo parpadear
python scripts/diagnose_liveness.py frames_liveness/<carpeta>
```

`record_blink.py` guarda cada grabación en su propia carpeta con marca de tiempo,
así que nunca se pisan. `diagnose_liveness.py` imprime la señal de cada frame, el
corte y cuántos frames se descartaron por movimiento.

Graba **ráfagas con parpadeo y sin él**, y alguna moviéndote a propósito: el modo
de falso positivo conocido es el desenfoque por movimiento, no el párpado.

Si un parpadeo real no se detecta, sube `BLINK_CLOSED_RATIO` o baja
`MIN_BLINK_DROP`. Si aparecen falsos positivos, haz lo contrario. Mide siempre
sobre varias ráfagas: con una sola es fácil fijar un valor que parece perfecto y
no generaliza.

---

## Scripts

| Script | Qué hace |
|---|---|
| `fetch_models.py` | Descarga YuNet y SFace al proyecto. Obligatorio antes del primer arranque. |
| `create_db.py` | Crea la base de datos en PostgreSQL si no existe. |
| `migrate_v05.py` | Añade `uuid` a los usuarios, crea operadores y API keys, retira plantillas del algoritmo antiguo. |
| `migrate_voice.py` | Añade las columnas de calibración y limpia plantillas de voz obsoletas. |
| `synth.py` | Genera locutores sintéticos para probar sin micrófono. **No mezcles su salida con usuarios reales.** |
| `record_blink.py` | Graba una ráfaga real de parpadeo con tu webcam, con aviso de cuándo parpadear. |
| `test_full_api.py` | Suite de integración completa contra un servidor en marcha. |
| `test_voice.py` | Suite de matrícula y verificación de locutor. |
| `test_liveness.py` | Suite de ataques de presentación y parpadeo. |
| `test_replay.py` | Demuestra que una voz reproducida por altavoz se acepta. |
| `bench_voice.py` | EER de voz con locutores sintéticos: GMM vs UBM-MAP. |
| `calibrate_face.py` | Calcula FAR/FRR/EER faciales con datos reales. |
| `calibrate_voice.py` | Calcula FAR/FRR/EER de voz con datos reales. |
| `diagnose_face.py` | Detección, calidad y matriz de similitud foto a foto. |
| `diagnose_liveness.py` | Vuelca la señal de apertura ocular frame a frame. |

`migrate_v05.py` **borra las plantillas faciales del algoritmo LBPH anterior**,
que son incompatibles con SFace. Los usuarios afectados deben volver a registrar
la cara; el script avisa de cuántos hay.

> **Aviso serio.** `test_full_api.py` **borra todos los usuarios** de la base como
> paso de limpieza, y **deja un usuario `alice` con voz sintética**. Ejecutarlo
> contra una base con usuarios reales tiene dos consecuencias: pierdes los datos, y
> la voz sintética que queda **desarma la verificación de locutor** para todos los
> que vuelvas a registrar (ver
> [La población de fondo](#la-población-de-fondo-el-punto-más-frágil-del-sistema)).
> Úsalo siempre contra una base de datos de pruebas, apuntando `DATABASE_URL` a
> otra base antes de lanzarlo.

Acepta `BASE_URL`, `PORTAL_USER` y `PORTAL_PASSWORD` como variables de entorno.

---

## Limitaciones conocidas

### Defectos abiertos

- **Una foto de cada 14 no se detecta** por giro de cabeza extremo. YuNet recuperó
  las 7 que perdían las cascadas Haar, pero no todas.
- **Los umbrales de liveness salen de una sola persona.** Las 11 ráfagas usadas
  para validar `BLINK_CLOSED_RATIO` y `MIN_BLINK_DROP` son del mismo sujeto y la
  misma cámara, en dos condiciones de luz. La separación es total (EAR 0.070–0.099
  cerrado frente a 0.222–0.268 abierto) y el acierto es 11/11 en toda la rejilla
  probada, pero **no está verificado con gafas, lentillas ni con otras personas**.
  Recalibra con `record_blink.py` antes de abrirlo a usuarios reales.
- **El modelo de landmarks añade ~0.45 s de CPU por login** (16 ms × 28 frames en
  un hilo). Es un 25 % sobre el coste que ya tenía el login facial.

### Limitaciones de diseño

- **Los umbrales están calibrados con una sola persona.** Ver
  [Calibración](#calibración-de-umbrales). Es lo primero que debe hacerse con un
  grupo real de usuarios.
- **El liveness solo cubre ataques de fotografía.**
  Detecta un parpadeo, y eso descarta una foto impresa o en pantalla. **No**
  detecta un vídeo de la persona parpadeando, ni una máscara, ni un deepfake. Un
  sistema de producción necesita análisis de textura, luz estructurada o
  profundidad, y certificación ISO/IEC 30107-3 si el riesgo lo justifica.
- **La verificación de voz sigue siendo débil en términos absolutos.** El
  UBM-MAP la mejoró de 36.2 % a 19.9 % de EER, pero **un 20 % de EER significa que
  uno de cada cinco intentos se clasifica mal** en el punto de igual error. Con
  grabaciones de 3-5 segundos y un GMM diagonal no se llega mucho más lejos; los
  sistemas actuales usan embeddings neuronales (x-vectors, ECAPA). Para decisiones
  sensibles usa el modo **Rostro + Voz**.
- **La voz necesita población, y de personas distintas.** El UBM exige al menos 2
  locutores de fondo **de personas diferentes**; varias grabaciones del mismo
  sujeto no cuentan y empeoran el resultado (impostor con LLR +3.92 frente a un
  umbral de 0.4, es decir, aceptado). Con menos población el sistema cae al modo de
  reserva, donde el z-score mide 50.4 % de EER y un impostor real pasó el umbral
  por 0.056. Un locutor **sintético** de prueba en la base produce el mismo efecto:
  la verificación acepta a cualquiera, en silencio. Ver
  [La población de fondo](#la-población-de-fondo-el-punto-más-frágil-del-sistema).
- **El fallo por población insuficiente es silencioso.** El servicio informa del
  modo en `scoring` y de la población en `n_background_speakers`, pero **no rechaza
  ni avisa** cuando está degradado: responde `verified: true` con normalidad. El
  cliente debe comprobar `scoring == "ubm-map"` por su cuenta.
- **El reconocimiento depende críticamente de cómo se registró el usuario.** Ver
  [Rendimiento medido](#rendimiento-medido). Si la matrícula no cubre condiciones
  variadas, el umbral resultante engaña. El filtro de redundancia mitiga el caso
  peor, pero no sustituye a un registro hecho con cuidado.
- **Las plantillas se guardan sin cifrar.** `voice_templates.features` contiene
  MFCC crudos y `face_templates.features` embeddings de SFace, de los que puede
  extraerse información biométrica. Un despliegue real necesita cifrado en reposo
  con gestión de claves.
- **El anti-replay compara bytes exactos, y eso deja abierto el ataque real.**
  Detiene el reenvío literal de una captura, pero **no** detecta una grabación
  reproducida por altavoz ni un vídeo mostrado a la cámara. Medido con
  `scripts/test_replay.py`: una grabación genuina pasada por altavoz y micrófono
  puntúa 5.48 de LLR frente a un umbral de 0.4, es decir, **se acepta**. Esto no
  es un fallo de calibración: un GMM modela *quién* habla, no *si está vivo*.
  Cerrarlo exige un detector de suplantación aparte (análisis de la banda alta,
  artefactos de altavoz, reverberación, o un desafío de texto aleatorio).

### Límites de escalado

Relevantes si se despliega con más de un proceso, que es lo necesario para
atender miles de peticiones por minuto:

- **Todo el estado compartido vive en memoria del proceso**: anti-replay, rate
  limiter, caché del UBM y caché de API keys. Con varios workers o réplicas cada
  uno tiene el suyo, así que el rate limiting se multiplica por el número de
  procesos y el anti-replay deja de cubrir el caso en que el reenvío cae en otro
  worker. Hace falta un almacén compartido tipo Redis.
- **Revocar una API key tarda hasta 60 s en propagarse.** `invalidate_cache` solo
  limpia la caché del proceso que atiende la revocación; los demás siguen
  aceptando la key hasta que expire su entrada. Con un solo proceso es inmediato.
- **El UBM de voz se entrena por usuario** (leave-one-out), lo que es O(N) sobre
  el número de locutores. Con miles de usuarios hay que entrenar un UBM único
  sobre una muestra y congelarlo.
- **`/api/face/identify` compara contra todas las plantillas.** Es una búsqueda
  lineal; a escala hace falta un índice vectorial.
- **Un login facial cuesta ~2.2 s de CPU** para 28 frames (1.8 s de detección y
  reconocimiento, más 0.45 s de landmarks para el liveness). Se atiende en el pool
  de hilos, así que no bloquea el servidor, pero limita los logins simultáneos por
  instancia y condiciona el número de núcleos.

### Cumplimiento legal

- **Los datos biométricos son dato sensible** bajo la Ley 1581 de 2012. Su
  tratamiento exige autorización **previa, explícita e informada** del titular, y
  el titular puede negarse sin que se le prive del servicio. La SIC ha sancionado
  el uso de reconocimiento facial sin esa autorización (Resolución 52185 de 2025).
- **El servicio no implementa hoy el registro del consentimiento.** No hay tabla
  de autorizaciones ni constancia de qué se informó ni cuándo. Debe resolverse
  antes de tratar datos de personas reales.
- **Si se almacenan las imágenes** (por ejemplo en MinIO), el bucket **no puede
  ser público**: una URL pública de una foto de rostro es exactamente el escenario
  sancionado. Usa bucket privado con URLs firmadas y caducidad. Para autenticar no
  hace falta guardar la foto, solo la plantilla.
