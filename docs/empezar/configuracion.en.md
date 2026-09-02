# Configuration

Every option is read from environment variables or from the `.env` file at the repository
root, through `pydantic-settings`. The file `.env.example` is the annotated template.

!!! danger "Four variables are mandatory"
    Startup fails with `RuntimeError` if `DATABASE_URL`, `JWT_SECRET`, `PORTAL_USER` or
    `PORTAL_PASSWORD` is missing.

---

## Database

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | *(required)* | SQLAlchemy connection string |
| `DB_POOL_SIZE` | `20` | Persistent pool connections |
| `DB_MAX_OVERFLOW` | `40` | Extra connections under load |
| `DB_POOL_RECYCLE` | `1800` | Seconds after which an idle connection is recycled |

!!! warning "Sizing the pool"
    At thousands of requests per minute, SQLAlchemy's default pool (5) is exhausted and
    requests queue up. Rule of thumb: `DB_POOL_SIZE >= uvicorn workers x 4`. Watch
    PostgreSQL's `max_connections`: `(DB_POOL_SIZE + DB_MAX_OVERFLOW) x n_processes` must
    fit inside it.

---

## Tokens

| Variable | Default | Description |
| --- | --- | --- |
| `JWT_SECRET` | *(required)* | Signing key. Changing it invalidates every session |
| `JWT_ALGORITHM` | `HS256` | Symmetric, sufficient for a single deployment |
| `JWT_EXPIRE_MINUTES` | `60` | Lifetime of the **portal** token |
| `SESSION_EXPIRE_MINUTES` | `15` | Lifetime of the **user session** token |

The session token is deliberately short: it identifies a person, not an operator, and gives
no access to `/api/*`.

---

## Face threshold

| Variable | Default | Description |
| --- | --- | --- |
| `FACE_THRESHOLD` | `0.363` | Minimum cosine similarity against the best template |
| `FACE_DUPLICATE_THRESHOLD` | `0.85` | Threshold for detecting the same face on another account of the same system |
| `FACE_REJECT_DUPLICATES` | `true` | Reject (409) enrollment of a face already registered in the same system |
| `FACE_MAX_TEMPLATES_PER_USER` | `12` | Maximum face templates per user |

Useful range 0..1. Raising it increases security and false rejections.

The duplicate guard only compares within the **same API client** (each system has its
own accounts); the same face is allowed across different systems.

Measured against 5 real, distinct people (`scripts/imagenes_test/famosos/`), the current
**0.363 threshold does not cross anyone different** (0 false accepts out of 88, separation
+0.423 in real mode). Reproduce with `python scripts/calibrate_face.py scripts/imagenes_test/famosos 0.363`.
See [Security](operacion/seguridad.en.md#measurement-with-real-impostors-face).

---

## Voice thresholds

### Primary path: speaker embedding

| Variable | Default | Description |
| --- | --- | --- |
| `VOICE_EMBEDDING_THRESHOLD` | `0.35` | Minimum cosine similarity between embeddings |
| `VOICE_DUPLICATE_THRESHOLD` | `0.35` | Threshold for detecting the same voice on two accounts |
| `VOICE_REJECT_DUPLICATES` | `true` | `true` rejects enrolling an already-registered voice with 409 |

The ResNet34 model carries its background population internally: it does not build a
per-user UBM, does not depend on how many people are in the database, and does not cost
O(N).

!!! warning "Why the duplicate check exists"
    Enrolling the same voice on two accounts means a single recording opens both, and it
    looks like the system accepts anyone when it is in fact getting it right. In this
    database, two accounts holding the same voice scored **0.916** against each other; a
    foreign voice stayed at 0.05-0.23. The duplicate threshold matches the verification
    threshold on purpose.

### Fallback path: MFCC + GMM

Used only when the user has no enrolled embedding or the model is not downloaded.

| Variable | Default | Description |
| --- | --- | --- |
| `VOICE_LLR_THRESHOLD` | `1.2` | Speaker log-likelihood minus background (`ubm-map`) |
| `VOICE_Z_THRESHOLD` | `-2.5` | Z-score, `gmm-z` mode, no background population |
| `VOICE_RATIO_THRESHOLD` | `-3.0` | Minimum advantage over the cohort in fallback mode |

!!! danger "`gmm-z` mode does not verify meaningfully"
    Measured with real data, an impostor scored `z = -2.444` against the `-2.5` threshold:
    it missed by 0.056. Under MAP adaptation the z-score yields **50.4% EER**, a coin flip.
    If the response carries `scoring: "gmm-z"`, you are not verifying anything solid. See
    [Known limitations](../operacion/limitaciones.md).

---

## Digit challenge

| Variable | Default | Description |
| --- | --- | --- |
| `VOICE_CHALLENGE_DIGITS` | `4` | Digits the server asks for in each challenge |
| `VOICE_CHALLENGE_TTL_SECONDS` | `60` | Challenge lifetime in seconds |
| `VOICE_CHALLENGE_MAX_ERRORS` | `0` | Tolerated digit errors |
| `VOICE_CHALLENGE_MIN_MARGIN` | `0.0` | Minimum advantage of the winning digit over the runner-up |

With 4 digits out of 10 enrolled there are **5040 ordered combinations**: an earlier
recording cannot answer a challenge chosen after it was made.

!!! note "Raising `MAX_ERRORS` is expensive"
    Going from 0 to 1 tolerated error over 4 digits multiplies the odds of guessing by
    roughly 37. Measure first with `scripts/test_digits.py`.

Challenges are stored in the `voice_challenges` PostgreSQL table, so they survive restarts
and multiple uvicorn workers. Each one is single use: consuming it deletes it, whether it
succeeds or fails.

---

## Liveness detection

| Variable | Default | Description |
| --- | --- | --- |
| `LIVENESS_MIN_FACES` | `6` | Frames with a detected face needed to evaluate the blink |
| `LIVENESS_MAX_GAP_RATIO` | `0.4` | Maximum tolerated fraction of frames without a face |

The portal captures roughly 28 frames in 2.6 seconds. Exceeding `MAX_GAP_RATIO` rejects the
capture: that is the typical signature of a photo being waved in front of the camera.

---

## Anti-replay and rate limiting

| Variable | Default | Description |
| --- | --- | --- |
| `REPLAY_WINDOW_SECONDS` | `300` | Seconds a capture hash is remembered |
| `AUTH_RATE_LIMIT` | `10` | Attempts allowed per window, per IP and user |
| `AUTH_RATE_WINDOW_SECONDS` | `60` | Window length |

!!! warning "Anti-replay only catches literal resubmission"
    Resending exactly the same burst or audio returns 409. It does **not** catch a
    recording played back through a loudspeaker. The digit challenge exists for that:
    passive channel analysis was measured and does not separate a live voice from the same
    voice through a speaker.

---

## CORS

| Variable | Default | Description |
| --- | --- | --- |
| `CORS_ORIGINS` | *(empty)* | Allowed origins, comma separated |

Empty means the middleware is **not added**, and only same-origin works. That is the
correct setting if you serve the portal from this same service.

```ini
CORS_ORIGINS=https://portal.mydomain.com,http://localhost:5173
```

Allowed headers: `Authorization`, `Content-Type`, `X-API-Key`.
Methods: `GET`, `POST`, `DELETE`, `OPTIONS`.

---

## API keys

| Variable | Default | Description |
| --- | --- | --- |
| `API_KEY_PEPPER` | *(empty)* | Pepper for hashing secrets. Empty = falls back to `JWT_SECRET` |
| `API_KEY_DEFAULT_DAYS` | `365` | Default validity when creating an API key |

!!! warning "Separate the pepper in production"
    If `API_KEY_PEPPER` is empty, rotating `JWT_SECRET` also invalidates **every API key**
    at once. Give it its own distinct value.

Changing `API_KEY_PEPPER` invalidates all existing API keys.

---

## Portal and documentation credentials

| Variable | Default | Description |
| --- | --- | --- |
| `PORTAL_USER` | *(required)* | Initial operator if `portal_users` is empty |
| `PORTAL_PASSWORD` | *(required)* | That operator's password |
| `DOCS_USER` | *(empty)* | Basic Auth for `/docs`. Empty = inherits from portal |
| `DOCS_PASSWORD` | *(empty)* | Same |

`PORTAL_USER` and `PORTAL_PASSWORD` act only as cold-start bootstrap: if `portal_users`
already has rows, they are ignored. From then on operators are managed from the
corresponding portal tab.
