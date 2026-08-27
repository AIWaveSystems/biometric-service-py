# Configuracion

Todas las opciones se leen de variables de entorno o del archivo `.env` de la raiz, via
`pydantic-settings`. El archivo `.env.example` es la plantilla comentada.

!!! danger "Cuatro variables son obligatorias"
    El arranque falla con `RuntimeError` si falta `DATABASE_URL`, `JWT_SECRET`,
    `PORTAL_USER` o `PORTAL_PASSWORD`.

---

## Base de datos

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `DATABASE_URL` | *(obligatoria)* | Cadena de conexion de SQLAlchemy |
| `DB_POOL_SIZE` | `20` | Conexiones persistentes del pool |
| `DB_MAX_OVERFLOW` | `40` | Conexiones extra bajo carga |
| `DB_POOL_RECYCLE` | `1800` | Segundos tras los que se recicla una conexion inactiva |

!!! warning "Dimensionar el pool"
    Con miles de peticiones por minuto el pool por defecto de SQLAlchemy (5) se agota y
    las peticiones se encolan. Regla practica: `DB_POOL_SIZE >= workers de uvicorn x 4`.
    Vigila el `max_connections` de PostgreSQL:
    `(DB_POOL_SIZE + DB_MAX_OVERFLOW) x n_procesos` debe caber dentro.

---

## Tokens

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `JWT_SECRET` | *(obligatoria)* | Clave de firma. Cambiarla invalida todas las sesiones |
| `JWT_ALGORITHM` | `HS256` | Simetrico, suficiente para un despliegue unico |
| `JWT_EXPIRE_MINUTES` | `60` | Vigencia del token de **portal** |
| `SESSION_EXPIRE_MINUTES` | `15` | Vigencia del token de **sesion de usuario** |

El token de sesion es deliberadamente corto: identifica a una persona, no a un operador,
y no da acceso a `/api/*`.

---

## Umbral facial

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `FACE_THRESHOLD` | `0.363` | Similitud coseno minima contra la mejor plantilla |
| `FACE_DUPLICATE_THRESHOLD` | `0.85` | Umbral para detectar la misma cara en otra cuenta del mismo sistema |
| `FACE_REJECT_DUPLICATES` | `true` | Rechazar (409) la matricula de una cara ya registrada en el mismo sistema |
| `FACE_MAX_TEMPLATES_PER_USER` | `12` | Maximo de plantillas faciales por usuario |

Rango util 0..1. Subirlo aumenta la seguridad y los falsos rechazos.

La guardia de duplicados solo compara dentro del **mismo cliente API** (cada sistema
tiene sus cuentas); entre sistemas distintos el mismo rostro esta permitido.

---

## Umbrales de voz

### Via principal: embedding de locutor

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `VOICE_EMBEDDING_THRESHOLD` | `0.35` | Similitud coseno minima entre embeddings |
| `VOICE_DUPLICATE_THRESHOLD` | `0.35` | Umbral para detectar la misma voz en dos cuentas |
| `VOICE_REJECT_DUPLICATES` | `true` | `true` rechaza con 409 matricular una voz ya registrada |

El modelo ResNet34 trae la poblacion de fondo dentro: no construye un UBM por usuario, no
depende de cuantas personas haya en la base y no cuesta O(N).

!!! warning "Por que existe el control de duplicados"
    Matricular la misma voz en dos cuentas hace que una sola grabacion abra las dos, y
    parece que el sistema acepta a cualquiera cuando en realidad esta acertando. En esta
    base, dos cuentas de la misma voz puntuaban **0.916** entre si; una voz ajena se
    quedaba en 0.05-0.23. El umbral de duplicado es igual al de verificacion a proposito.

### Via de reserva: MFCC + GMM

Se usa solo cuando el usuario no tiene embedding matriculado o el modelo no esta
descargado.

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `VOICE_LLR_THRESHOLD` | `1.2` | Log-verosimilitud del locutor menos la del fondo (`ubm-map`) |
| `VOICE_Z_THRESHOLD` | `-2.5` | Z-score, modo `gmm-z`, sin poblacion de fondo |
| `VOICE_RATIO_THRESHOLD` | `-3.0` | Ventaja minima sobre la cohorte en modo de reserva |

!!! danger "El modo `gmm-z` no verifica de forma significativa"
    Medido con datos reales, un impostor puntuo `z = -2.444` frente al umbral de `-2.5`:
    paso por 0.056. Bajo adaptacion MAP el z-score da **50.4% de EER**, es decir una
    moneda al aire. Si la respuesta trae `scoring: "gmm-z"`, no estas verificando nada
    solido. Ver [Limitaciones conocidas](../operacion/limitaciones.md).

---

## Desafio de digitos

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `VOICE_CHALLENGE_DIGITS` | `4` | Digitos que pide el servidor en cada desafio |
| `VOICE_CHALLENGE_TTL_SECONDS` | `60` | Segundos de vida del desafio |
| `VOICE_CHALLENGE_MAX_ERRORS` | `0` | Errores de digito tolerados |
| `VOICE_CHALLENGE_MIN_MARGIN` | `0.0` | Ventaja minima del digito ganador sobre el segundo |

Con 4 digitos sobre los 10 matriculados hay **5040 combinaciones ordenadas**: una
grabacion previa no puede responder a un desafio elegido despues de grabarla.

!!! note "Subir `MAX_ERRORS` cuesta caro"
    Pasar de 0 a 1 error tolerado sobre 4 digitos multiplica por unas 37 veces la
    probabilidad de acertar al azar. Mide antes con `scripts/test_digits.py`.

Los desafios se guardan en la tabla `voice_challenges` de PostgreSQL, asi que sobreviven a
reinicios y a varios workers de uvicorn. Cada uno es de un solo uso: consumirlo lo borra,
acierte o falle.

---

## Deteccion de vida

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `LIVENESS_MIN_FACES` | `6` | Frames con rostro necesarios para evaluar el parpadeo |
| `LIVENESS_MAX_GAP_RATIO` | `0.4` | Fraccion maxima de frames sin rostro tolerada |

El portal captura unos 28 frames en 2.6 segundos. Superar el `MAX_GAP_RATIO` rechaza la
captura: es la firma tipica de una foto movida delante de la camara.

---

## Anti-replay y limitacion de intentos

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `REPLAY_WINDOW_SECONDS` | `300` | Segundos que se recuerda el hash de una captura |
| `AUTH_RATE_LIMIT` | `10` | Intentos permitidos por ventana, por IP y usuario |
| `AUTH_RATE_WINDOW_SECONDS` | `60` | Duracion de la ventana |

!!! warning "El anti-replay solo detecta el reenvio literal"
    Reenviar exactamente la misma rafaga o el mismo audio devuelve 409. **No** detecta una
    grabacion reproducida por altavoz. Para eso esta el desafio de digitos: el analisis
    pasivo del canal se midio y no separa una voz en directo de la misma voz por altavoz.

---

## CORS

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `CORS_ORIGINS` | *(vacio)* | Origenes permitidos, separados por comas |

Vacio significa que el middleware **no se anade**, y solo funciona el mismo origen. Es lo
correcto si sirves el portal desde este mismo servicio.

```ini
CORS_ORIGINS=https://portal.midominio.com,http://localhost:5173
```

Cabeceras permitidas: `Authorization`, `Content-Type`, `X-API-Key`.
Metodos: `GET`, `POST`, `DELETE`, `OPTIONS`.

---

## API keys

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `API_KEY_PEPPER` | *(vacio)* | Pimienta para hashear los secretos. Vacia = usa `JWT_SECRET` |
| `API_KEY_DEFAULT_DAYS` | `365` | Validez por defecto al crear una API key |

!!! warning "Separa la pimienta en produccion"
    Si `API_KEY_PEPPER` esta vacia, rotar `JWT_SECRET` invalida ademas **todas las API
    keys** de golpe. Ponle un valor propio y distinto.

Cambiar `API_KEY_PEPPER` invalida todas las API keys existentes.

---

## Credenciales del portal y de la documentacion

| Variable | Por defecto | Descripcion |
| --- | --- | --- |
| `PORTAL_USER` | *(obligatoria)* | Operador inicial si `portal_users` esta vacia |
| `PORTAL_PASSWORD` | *(obligatoria)* | Contrasena de ese operador |
| `DOCS_USER` | *(vacio)* | Basic Auth de `/docs`. Vacio = hereda del portal |
| `DOCS_PASSWORD` | *(vacio)* | Idem |

`PORTAL_USER` y `PORTAL_PASSWORD` solo actuan como arranque en frio: si la tabla
`portal_users` ya tiene filas, se ignoran. A partir de ahi los operadores se gestionan
desde la pestana correspondiente del portal.
