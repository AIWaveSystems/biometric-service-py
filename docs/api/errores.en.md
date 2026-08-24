# Errors

Every error returns JSON with a single field:

```json
{"detail": "Mensaje explicativo"}
```

Messages are written in Spanish and phrased so they can be shown to the end user as they
are, without translating or rewriting.

---

## Codes by category

| Code | Meaning | What the client should do |
| --- | --- | --- |
| `400` | The request or capture is unusable | Fix it and **retry** |
| `401` | Credential missing, invalid or expired | Renew the credential |
| `403` | The API key exists but lacks the scope | Use a different key |
| `404` | The resource does not exist | Do not retry |
| `409` | State conflict | Depends on the case, see below |
| `429` | Too many attempts | Wait and retry |
| `503` | A model is missing or the database is down | Alert operations |

---

## 400 — Invalid request or capture

### Face

| Message | Cause | Fix for the user |
| --- | --- | --- |
| *No se detecto ninguna cara en la imagen* | YuNet found no face | More light, centre the face |
| *No se detecto la cara en suficientes frames...* | Burst with too many gaps | Look straight ahead, do not turn |
| *Ningun frame tiene calidad suficiente para verificar* | All blurry or the face too small | Move closer, hold the camera steady |
| *Se requiere al menos un frame* | Empty `frames` list | Client bug |
| *La captura envio muy pocos frames (N)...* | Fewer than `LIVENESS_MIN_FACES` | Lengthen the capture |
| *No se envio ninguna imagen* | Neither `image` nor `images` | Client bug |

!!! tip "These 400s are not access denials"
    They are capture problems. The frontend should ask the user to retry with a specific
    hint, not show *access denied*.

### Voice

| Message | Cause |
| --- | --- |
| *Lista de digitos invalida (usa 0..9)* | Characters out of range |
| *La lista de digitos tiene repetidos* | A digit appears twice |
| *Se esperaban N digitos y se detectaron M...* | Segmentation does not match |
| *Digitos demasiado breves: X, Y* | Pronounced too quickly |

The audio loader also returns 400 when the WAV cannot be read, is too short to compute the
embedding, or falls below the **-55 dBFS** silence floor.

### Users

| Message | Cause |
| --- | --- |
| *Se requiere al menos una biometria o una contrasena* | Empty registration |
| *Todas las fotos son casi identicas a las que ya tiene el usuario* | All redundant |
| *La contrasena debe tener 6 caracteres o mas* | Password too short |
| *El nombre nuevo es el mismo* | Rename with no change |

---

## 401 — Unauthorised

| Message | Cause |
| --- | --- |
| *API key invalida* | Wrong format, non-existent, revoked or expired |
| *Acceso no autorizado* | No `Authorization: Bearer`, or an invalid, expired or wrong-scope token |
| *Credenciales invalidas* | Failed end-user login |
| *Credenciales de acceso invalidas* | Failed operator login |
| *La contrasena actual no es correcta* | Portal password change |
| *Autenticacion requerida* | Basic Auth on `/docs` |

!!! warning "A session token gives 401 on `/api/*`"
    This is the most common integration mistake. The JWT returned by a login carries
    `scope: "user"` and the middleware only accepts `scope: "portal"`. Client systems use
    an **API key**.

---

## 403 — Missing scope

```json
{"detail": "La API key no tiene el permiso 'admin'"}
```

The key is valid but lacks the scope the route requires. The [scope
table](index.md#which-scope-each-route-requires) says which one each route needs.

The fix is to create a new key with the right scopes: an existing key's scopes cannot be
edited.

---

## 404 — Not found

| Message | Cause |
| --- | --- |
| *Usuario no encontrado* | The `username` or UUID does not exist |
| *Cliente no encontrado* | Non-existent client UUID |
| *Plantilla no encontrada* | Non-existent template id |
| *Usuario de portal no encontrado* | Non-existent operator UUID |
| *El usuario no tiene plantilla facial vigente...* | Exists, but has no face templates |
| *El usuario no tiene plantilla de voz* | Exists, but has no enrolled voice |
| *No hay usuarios registrados* | `identify` against an empty database |

The last three are a 404 on the **biometric resource**, not on the user: the account exists,
the enrolment is missing.

---

## 409 — Conflict

| Message | Cause | Retryable? |
| --- | --- | --- |
| *El usuario ya existe* | Name taken | No, choose another |
| *Ese nombre de usuario existe en varios sistemas cliente...* | Same name in several webs, request from the portal | Yes, sending `user_uuid` |
| *Ya existe un usuario con ese nombre* | Renamed to a taken one | No |
| *Ya existe un cliente con ese nombre* | Client name taken | No |
| *Ya existe un usuario de portal con ese nombre* | Duplicate operator | No |
| *Esta voz ya esta matriculada como 'X'...* | Duplicate voice | No, review the other account |
| *Captura repetida detectada...* | Same burst resent | Yes, **capture again** |
| *Grabacion repetida detectada...* | Same audio resent | Yes, record again |
| *Desafio invalido, caducado o ya usado* | Challenge consumed or expired | Yes, **request a new one** |
| *El usuario tiene N digitos matriculados y hacen falta...* | Incomplete enrolment | No, enrol digits |
| *La matricula de digitos es antigua o incompleta* | No stored CMVN | No, re-enrol |
| *No puedes desactivar el ultimo usuario de portal activo* | Lockout protection | No |

!!! danger "The challenge 409 requires a new challenge"
    Retrying with the same `challenge_id` always returns 409 again: consuming it deletes
    it. The frontend must call `POST /api/voice/challenge` again.

---

## 429 — Too many attempts

```json
{"detail": "Demasiados intentos, espera un momento"}
```

More than `AUTH_RATE_LIMIT` attempts within `AUTH_RATE_WINDOW_SECONDS` for that IP and user
combination. By default, 10 per minute.

The response does **not** include `Retry-After`. Wait for the full window to pass.

---

## 503 — Degraded service

| Source | Message |
| --- | --- |
| `POST /api/voice/identify` | *El modelo de locutor no esta descargado* |
| `GET /health` | Status object with `status: "degraded"` |

`/health` returns 503 when the database is unreachable or the face models are missing:

```json
{
  "status": "degraded",
  "database": false,
  "face_models": true,
  "version": "0.4.0"
}
```

This is the endpoint your load balancer or orchestrator should watch.

---

## Recommended client handling

```python
import httpx

RETRYABLE = {
    "Captura repetida detectada",
    "Grabacion repetida detectada",
}


def handle(response: httpx.Response) -> dict:
    if response.is_success:
        return response.json()

    detail = response.json().get("detail", "Unknown error")

    if response.status_code == 400:
        raise RetryCapture(detail)
    if response.status_code == 429:
        raise WaitAndRetry(detail)
    if response.status_code == 409:
        if any(t in detail for t in RETRYABLE):
            raise RetryCapture(detail)
        if "Desafio" in detail:
            raise RequestNewChallenge(detail)
        raise StateConflict(detail)
    if response.status_code in (401, 403):
        raise CredentialProblem(detail)

    raise ServiceError(detail)
```

The important distinction is between **retry the capture** (environmental, self-healing) and
**state conflict** (something must change first).
