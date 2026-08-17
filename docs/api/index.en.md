# Conventions and authentication

## Base URL

Every endpoint lives under `/api/`. Outside that prefix there are only three routes:

| Route | Authentication | Contents |
| --- | --- | --- |
| `GET /health` | none | Service, database and model status |
| `GET /` | none | Administration portal |
| `GET /docs`, `/redoc`, `/openapi.json` | Basic Auth | OpenAPI |

---

## The two ways to authenticate against `/api/*`

The `PortalApiAuth` middleware intercepts **every** request to `/api/`. It accepts two
credentials and checks the API key first.

```mermaid
flowchart TD
    A[Request to /api/*] --> B{OPTIONS method?}
    B -->|yes| Z[Pass]
    B -->|no| C{Open route?<br/>/api/portal/auth}
    C -->|yes| Z
    C -->|no| D{X-API-Key header?}
    D -->|yes| E{Key valid,<br/>active and current?}
    E -->|no| F[401 invalid API key]
    E -->|yes| G{Has the scope<br/>the route requires?}
    G -->|no| H[403 missing scope]
    G -->|yes| Z
    D -->|no| I{Authorization: Bearer<br/>with portal scope?}
    I -->|no| J[401 unauthorised]
    I -->|yes| Z
```

### API key (client systems)

```http
X-API-Key: lbs_a1b2c3d4_XoP9wQ...
```

Format: `lbs_<prefix>_<secret>`. The prefix (12 hex characters) identifies the client and
is stored in the clear; the secret is stored only as an HMAC-SHA256 with `API_KEY_PEPPER`.

### Portal token (operators)

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

Accepted only if the JWT carries `scope: "portal"`. A user session token (`scope: "user"`)
**is rejected with 401** even though it is correctly signed.

!!! warning "The API key never reaches the browser"
    Anyone who opens developer tools can read it. Calls carrying an API key originate from
    **your backend**. The browser talks to your backend, and your backend talks to this
    service. See [From a frontend](../integracion/frontend.md).

---

## Scopes

Every API key carries a list of scopes. The requested route determines which one is
required.

| Scope | What it enables |
| --- | --- |
| `auth` | Verify and authenticate: login, verify, identify, challenge, lookups |
| `enroll` | Enrol biometrics: user, face, voice and digit registration |
| `admin` | Administer: delete, rename, change passwords, manage clients |

### Which scope each route requires

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
    Everything else: /api/face/login, /api/face/verify, /api/face/identify,
    /api/voice/verify, /api/voice/identify, /api/voice/challenge,
    /api/voice/challenge/verify, /api/auth/login, /api/voice/digits/{username}
    ```

A portal token has access to **every** route; scopes apply only to API keys.

!!! tip "Least privilege"
    A login frontend needs only `auth`. An enrolment panel needs `auth` and `enroll`.
    `admin` is reserved for internal tooling. Create one API key per system and per
    environment, never a shared one.

---

## Request formats

| Endpoint type | Content-Type |
| --- | --- |
| Biometric (upload images or audio) | `multipart/form-data` |
| Administrative (clients, portal, password login) | `application/json` |

In multipart requests, text fields are form fields, not JSON.

### Accepted file formats

**Images** — anything OpenCV can read: JPEG, PNG, BMP, WEBP. The portal sends JPEG at
quality 0.9.

**Audio** — WAV. Resampled internally to 16 kHz mono. At least about 2 seconds of useful
speech; below that the embedding cannot be computed and the response is 400.

---

## Responses

Every response is JSON. Errors follow the FastAPI format:

```json
{"detail": "Usuario no encontrado"}
```

`detail` messages are written in Spanish and phrased so they can be shown to the end user
as they are. The full list is in [Errors](errores.md).

---

## Rate limiting

Authentication endpoints apply a limiter per **IP + user**:

- `POST /api/auth/login`
- `POST /api/portal/auth` (per IP only)
- `POST /api/face/login`
- `POST /api/voice/verify`
- `POST /api/voice/challenge`
- `POST /api/voice/challenge/verify`

Exceeding `AUTH_RATE_LIMIT` attempts within `AUTH_RATE_WINDOW_SECONDS` returns **429**.

!!! warning "The limiter lives in process memory"
    With several uvicorn workers each keeps its own count, so the effective limit is
    multiplied by the number of workers. Production needs this moved to Redis. See
    [Known limitations](../operacion/limitaciones.md).

---

## Replay guard

`POST /api/face/login` and `POST /api/voice/verify` hash the capture and remember it for
`REPLAY_WINDOW_SECONDS`. Resending exactly the same bytes returns **409**.

It catches literal resubmission of a captured request. It does **not** catch someone
playing a recording through a loudspeaker at the microphone: the
[digit challenge](voz.md#digit-challenge) exists for that.
