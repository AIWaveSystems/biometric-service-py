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
9. [Calibración de umbrales](#calibración-de-umbrales)
10. [Scripts](#scripts)
11. [Limitaciones conocidas](#limitaciones-conocidas)

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

| Variable | Por defecto | Qué hace |
|---|---|---|
| `DATABASE_URL` | — | Cadena de conexión de SQLAlchemy. Obligatoria. |
| `JWT_SECRET` | — | Clave de firma de los tokens. Obligatoria. |
| `JWT_ALGORITHM` | `HS256` | Algoritmo de firma. |
| `JWT_EXPIRE_MINUTES` | `60` | Vigencia del token del portal. |
| `SESSION_EXPIRE_MINUTES` | `15` | Vigencia del token de sesión de usuario. |
| `FACE_THRESHOLD` | `0.70` | Similitud coseno mínima para aceptar un rostro. |
| `VOICE_Z_THRESHOLD` | `-2.5` | z-score mínimo frente a la matrícula. |
| `VOICE_RATIO_THRESHOLD` | `-3.0` | Ventaja mínima sobre la cohorte. |
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

### 6. Verificación

Se calculan dos estadísticos:

- **z-score**: `(verosimilitud − self_score) / sigma`. Al dividir por la
  desviación, el umbral no depende de la escala de verosimilitud de cada locutor.
- **ratio de cohorte**: `verosimilitud_objetivo − verosimilitud_cohorte`, donde la
  cohorte es un GMM entrenado con las voces de **los demás** usuarios. Responde a
  "¿se parece más a esta persona que a la población general?".

Se acepta si el z-score supera su umbral **y** el ratio supera el suyo. Cuando no
hay otros usuarios registrados no existe cohorte y la decisión recae solo en el
z-score; la respuesta lo indica con `used_cohort: false`.

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
- **La verificación de voz con 3 segundos es intrínsecamente débil.** En las
  pruebas, un impostor acústicamente cercano al objetivo puede puntuar mejor que
  un genuino grabado con ruido. Para decisiones sensibles conviene el modo
  **Rostro + Voz**, que exige superar ambos factores.
- **Las plantillas se guardan sin cifrar.** `voice_templates.features` contiene
  MFCC crudos, de los que puede reconstruirse información de la voz. Un despliegue
  real necesita cifrado en reposo con gestión de claves.
- **El anti-replay vive en memoria del proceso.** Funciona con una sola instancia;
  con varios workers o réplicas haría falta un almacén compartido tipo Redis. Lo
  mismo aplica al rate limiter.
- **El anti-replay compara bytes exactos.** Detiene el reenvío literal de una
  captura, no una regrabación de un vídeo mostrado a la cámara.
- **Un único juego de credenciales para todo el portal.** Quien tenga
  `PORTAL_USER`/`PORTAL_PASSWORD` puede listar y borrar cualquier usuario. No hay
  roles ni auditoría.
- **`eigenfaces.py` no se usa.** Está implementado y es funcional, pero la API
  emplea LBPH. Se conserva como material del proyecto.
- **Un login facial cuesta ~1.8 s de CPU** para 28 frames. Se atiende en el pool
  de hilos, así que no bloquea el servidor, pero limita el número de logins
  simultáneos por instancia.
