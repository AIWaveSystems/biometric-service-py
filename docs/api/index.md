# Convenciones y autenticacion

## URL base

Todos los endpoints cuelgan de `/api/`. Fuera de ese prefijo solo hay tres rutas:

| Ruta | Autenticacion | Contenido |
| --- | --- | --- |
| `GET /health` | ninguna | Estado del servicio, base de datos y modelos |
| `GET /` | ninguna | Portal de administracion |
| `GET /docs`, `/redoc`, `/openapi.json` | Basic Auth | OpenAPI |

---

## Las dos formas de autenticarse contra `/api/*`

El middleware `PortalApiAuth` intercepta **toda** peticion a `/api/`. Acepta dos
credenciales y comprueba primero la API key.

```mermaid
flowchart TD
    A[Peticion a /api/*] --> B{Metodo OPTIONS?}
    B -->|si| Z[Pasa]
    B -->|no| C{Ruta abierta?<br/>/api/portal/auth}
    C -->|si| Z
    C -->|no| D{Cabecera X-API-Key?}
    D -->|si| E{Clave valida,<br/>activa y vigente?}
    E -->|no| F[401 API key invalida]
    E -->|si| G{Tiene el permiso<br/>que pide la ruta?}
    G -->|no| H[403 sin permiso]
    G -->|si| Z
    D -->|no| I{Authorization: Bearer<br/>con scope portal?}
    I -->|no| J[401 Acceso no autorizado]
    I -->|si| Z
```

### API key (sistemas cliente)

```http
X-API-Key: lbs_a1b2c3d4_XoP9wQ...
```

Formato: `lbs_<prefijo>_<secreto>`. El prefijo (12 caracteres hex) identifica al cliente y
se guarda en claro; el secreto se guarda solo como HMAC-SHA256 con `API_KEY_PEPPER`.

### Token de portal (operadores)

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

Solo se acepta si el JWT tiene `scope: "portal"`. Un token de sesion de usuario
(`scope: "user"`) **se rechaza con 401** aunque este firmado correctamente.

!!! warning "La API key nunca va en el navegador"
    Cualquiera que abra las herramientas de desarrollo puede leerla. Las llamadas con API
    key salen del **backend** de tu sistema. El navegador habla con tu backend, y tu
    backend con este servicio. Ver [Desde un frontend](../integracion/frontend.md).

---

## Permisos

Cada API key lleva una lista de permisos. La ruta que se pide determina cual hace falta.

| Permiso | Que habilita |
| --- | --- |
| `auth` | Verificar y autenticar: login, verify, identify, challenge, consultas |
| `enroll` | Matricular biometria: registro de usuario, rostro, voz, digitos |
| `admin` | Administrar: borrar, renombrar, cambiar contrasenas, gestionar clientes |

### Que permiso pide cada ruta

=== "enroll"

    ```
    POST /api/users/register
    POST /api/face/register
    POST /api/voice/register
    POST /api/voice/digits/enroll
    POST /api/users/{username}/faces
    ```

=== "admin"

    ```
    GET    /api/users
    GET    /api/face/templates
    GET    /api/voice/templates
    GET    /api/voice/system
    POST   /api/users/{username}/password
    POST   /api/users/{username}/rename
    DELETE /api/users/{username}
    DELETE /api/voice/digits/{username}
    DELETE /api/face/templates/{id}
    DELETE /api/voice/templates/{id}
    *      /api/clients/**
    *      /api/portal/users/**
    ```

=== "auth"

    ```
    Todo lo demas: /api/face/login, /api/face/verify, /api/face/identify,
    /api/voice/verify, /api/voice/identify, /api/voice/challenge,
    /api/voice/challenge/verify, /api/auth/login, /api/voice/digits/{username}
    ```

Un token de portal tiene acceso a **todas** las rutas; los permisos solo se aplican a las
API keys.

!!! tip "Principio de minimo privilegio"
    Un frontend de login solo necesita `auth`. Un panel de altas necesita `auth` y
    `enroll`. `admin` se reserva para herramientas internas. Crea una API key por sistema
    y por entorno, no una compartida.

---

## Formatos de peticion

| Tipo de endpoint | Content-Type |
| --- | --- |
| Biometricos (suben imagenes o audio) | `multipart/form-data` |
| Administrativos (clientes, portal, login por contrasena) | `application/json` |

En multipart, los campos de texto van como campos de formulario, no como JSON.

### Formatos de archivo aceptados

**Imagenes** — cualquier formato que lea OpenCV: JPEG, PNG, BMP, WEBP. El portal envia
JPEG de calidad 0.9.

**Audio** — WAV. Se remuestrea a 16 kHz mono internamente. Minimo unos 2 segundos de habla
util; por debajo de eso el embedding no se puede calcular y devuelve 400.

---

## Respuestas

Todas las respuestas son JSON. Los errores siguen el formato de FastAPI:

```json
{"detail": "Usuario no encontrado"}
```

Los mensajes de `detail` estan en espanol y estan escritos para poder mostrarse al usuario
final tal cual. La lista completa esta en [Errores](errores.md).

---

## Limitacion de intentos

Los endpoints de autenticacion aplican un limitador por **IP + usuario**:

- `POST /api/auth/login`
- `POST /api/portal/auth` (solo por IP)
- `POST /api/face/login`
- `POST /api/voice/verify`
- `POST /api/voice/challenge`
- `POST /api/voice/challenge/verify`

Al superar `AUTH_RATE_LIMIT` intentos en `AUTH_RATE_WINDOW_SECONDS` segundos, la respuesta
es **429**.

!!! warning "El limitador vive en memoria del proceso"
    Con varios workers de uvicorn cada uno lleva su propia cuenta, asi que el limite real
    se multiplica por el numero de workers. Para produccion hay que moverlo a Redis. Ver
    [Limitaciones conocidas](../operacion/limitaciones.md).

---

## Guarda de repeticion

`POST /api/face/login` y `POST /api/voice/verify` calculan un hash de la captura y lo
recuerdan durante `REPLAY_WINDOW_SECONDS`. Reenviar exactamente los mismos bytes devuelve
**409**.

Detecta el reenvio literal de una peticion capturada. **No** detecta a alguien que
reproduce una grabacion por altavoz delante del microfono: para eso esta el
[desafio de digitos](voz.md#desafio-de-digitos).
