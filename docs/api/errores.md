# Errores

Todos los errores devuelven JSON con un unico campo:

```json
{"detail": "Mensaje explicativo"}
```

Los mensajes estan redactados en espanol y pensados para mostrarse al usuario final tal
cual, sin traducir ni reescribir.

---

## Codigos por categoria

| Codigo | Significado | Que debe hacer el cliente |
| --- | --- | --- |
| `400` | La peticion o la captura no sirven | Corregir y **repetir** |
| `401` | Credencial ausente, invalida o caducada | Renovar credencial |
| `403` | La API key existe pero le falta el permiso | Cambiar de clave |
| `404` | El recurso no existe | No reintentar |
| `409` | Conflicto de estado | Depende del caso, ver abajo |
| `429` | Demasiados intentos | Esperar y reintentar |
| `503` | Falta un modelo o la base no responde | Avisar a operaciones |

---

## 400 — Peticion o captura invalida

### Rostro

| Mensaje | Causa | Solucion para el usuario |
| --- | --- | --- |
| *No se detecto ninguna cara en la imagen* | YuNet no encontro rostro | Mas luz, cara centrada |
| *No se pudo leer la imagen (formato no soportado...)* | El archivo no es JPG ni PNG (HEIC de iPhone, AVIF, WEBP...) | Si, convertir a JPG o PNG |
| *El usuario ya alcanzo el maximo de N plantillas faciales...* | Tope `FACE_MAX_TEMPLATES_PER_USER` | Si, borrar alguna o re-matriplicar |
| *No se detecto la cara en suficientes frames...* | Rafaga con demasiados huecos | Mirar de frente, no girar |
| *Ningun frame tiene calidad suficiente para verificar* | Todos borrosos o cara muy pequena | Acercarse, sujetar la camara |
| *Se requiere al menos un frame* | Lista `frames` vacia | Error del cliente |
| *La captura envio muy pocos frames (N)...* | Menos de `LIVENESS_MIN_FACES` | Alargar la captura |
| *No se envio ninguna imagen* | Ni `image` ni `images` | Error del cliente |

!!! tip "Estos 400 no son negativas de acceso"
    Son problemas de captura. El frontend debe pedir que repita con una indicacion
    concreta, no mostrar *acceso denegado*.

### Voz

| Mensaje | Causa |
| --- | --- |
| *Lista de digitos invalida (usa 0..9)* | Caracteres fuera de rango |
| *La lista de digitos tiene repetidos* | Un digito aparece dos veces |
| *Se esperaban N digitos y se detectaron M...* | La segmentacion no cuadra |
| *Digitos demasiado breves: X, Y* | Pronunciados muy rapido |

Ademas, el cargador de audio devuelve 400 cuando el WAV no se puede leer, es demasiado
corto para calcular el embedding, o esta por debajo del suelo de silencio de **-55 dBFS**.

### Usuarios

| Mensaje | Causa |
| --- | --- |
| *Se requiere al menos una biometria o una contrasena* | Registro vacio |
| *Todas las fotos son casi identicas a las que ya tiene el usuario* | Todas redundantes |
| *La contrasena debe tener 6 caracteres o mas* | Contrasena corta |
| *El nombre nuevo es el mismo* | Renombrado sin cambio |

---

## 401 — No autorizado

| Mensaje | Causa |
| --- | --- |
| *API key invalida* | Formato incorrecto, inexistente, revocada o caducada |
| *Acceso no autorizado* | Sin `Authorization: Bearer`, o token invalido, caducado o de scope equivocado |
| *Credenciales invalidas* | Login de usuario final fallido |
| *Credenciales de acceso invalidas* | Login de operador fallido |
| *La contrasena actual no es correcta* | Cambio de contrasena del portal |
| *Autenticacion requerida* | Basic Auth de `/docs` |

El login de usuario final (`POST /api/auth/login`) siempre responde **401 `Credenciales
invalidas`** cuando el usuario no existe, no tiene contrasena o la contrasena es incorrecta.
No devuelve `404 Usuario no encontrado` en ese caso: ese 404 es solo de rutas de consulta
(identify, get de usuario, etc.). El mensaje y el tiempo de respuesta son identicos en los
tres casos para no revelar si la cuenta existe.

!!! warning "Un token de sesion da 401 en `/api/*`"
    Es la confusion mas comun al integrar. El JWT que devuelve un login tiene
    `scope: "user"` y el middleware solo acepta `scope: "portal"`. Los sistemas cliente
    usan **API key**.

---

## 403 — Sin permiso

```json
{"detail": "La API key no tiene el permiso 'admin'"}
```

La clave es valida pero le falta el permiso que exige la ruta. La [tabla de
permisos](index.md#que-permiso-pide-cada-ruta) dice cual necesita cada una.

Se arregla creando una clave nueva con los permisos correctos: los de una clave existente
no se pueden editar.

---

## 404 — No encontrado

| Mensaje | Causa |
| --- | --- |
| *Usuario no encontrado* | El `username` o el UUID no existe |
| *Cliente no encontrado* | UUID de cliente inexistente |
| *Plantilla no encontrada* | Id de plantilla inexistente |
| *Usuario de portal no encontrado* | UUID de operador inexistente |
| *El usuario no tiene plantilla facial vigente...* | Existe, pero sin plantillas faciales |
| *El usuario no tiene plantilla de voz* | Existe, pero sin voz matriculada |
| *No hay usuarios registrados* | `identify` sobre una base vacia |

Los tres ultimos son un 404 sobre el **recurso biometrico**, no sobre el usuario: la cuenta
existe, le falta la matricula.

---

## 409 — Conflicto

| Mensaje | Causa | Se puede reintentar? |
| --- | --- | --- |
| *El usuario ya existe* | Nombre ocupado | No, elegir otro |
| *Ese nombre de usuario existe en varios sistemas cliente...* | Mismo nombre en varias webs, peticion desde el portal | Si, enviando `user_uuid` |
| *Ya existe un usuario con ese nombre* | Renombrado a uno ocupado | No |
| *Ya existe un cliente con ese nombre* | Nombre de cliente ocupado | No |
| *Ya existe un usuario de portal con ese nombre* | Operador duplicado | No |
| *Esta voz ya esta matriculada en otra cuenta...* | Voz duplicada | No, revisar la otra cuenta |
| *Esa cara ya esta matriculada en otra cuenta del mismo sistema...* | La misma persona ya existe en otra cuenta de ESA web (`FACE_REJECT_DUPLICATES=true`) | No, revisar la otra cuenta |
| *Captura repetida detectada...* | Misma rafaga reenviada | Si, **volver a capturar** |
| *Grabacion repetida detectada...* | Mismo audio reenviado | Si, volver a grabar |
| *Desafio invalido, caducado o ya usado* | Desafio consumido o vencido | Si, **pedir uno nuevo** |
| *El usuario tiene N digitos matriculados y hacen falta...* | Matricula incompleta | No, matricular digitos |
| *La matricula de digitos es antigua o incompleta* | Sin CMVN guardada | No, rematricular |
| *No puedes desactivar el ultimo usuario de portal activo* | Proteccion | No |

!!! danger "El 409 del desafio exige uno nuevo"
    Reintentar con el mismo `challenge_id` vuelve a dar 409 siempre: consumirlo lo borra.
    El frontend debe llamar de nuevo a `POST /api/voice/challenge`.

---

## 429 — Demasiados intentos

```json
{"detail": "Demasiados intentos, espera un momento"}
```

Se han superado `AUTH_RATE_LIMIT` intentos en `AUTH_RATE_WINDOW_SECONDS` para esa
combinacion de IP y usuario. Por defecto, 10 por minuto.

La respuesta **no** incluye `Retry-After`. Espera a que pase la ventana completa.

---

## 503 — Servicio degradado

| Origen | Mensaje |
| --- | --- |
| `POST /api/voice/identify` | *El modelo de locutor no esta descargado* |
| `GET /health` | Objeto de estado con `status: "degraded"` |

`/health` responde 503 cuando la base no contesta o faltan los modelos faciales:

```json
{
  "status": "degraded",
  "database": false,
  "face_models": true,
  "version": "0.4.0"
}
```

Es el endpoint que debe vigilar tu balanceador o tu orquestador.

---

## Manejo recomendado en el cliente

```python
import httpx

REINTENTABLES = {
    "Captura repetida detectada",
    "Grabacion repetida detectada",
}


def manejar(respuesta: httpx.Response) -> dict:
    if respuesta.is_success:
        return respuesta.json()

    detalle = respuesta.json().get("detail", "Error desconocido")

    if respuesta.status_code == 400:
        raise RepetirCaptura(detalle)
    if respuesta.status_code == 429:
        raise EsperarYReintentar(detalle)
    if respuesta.status_code == 409:
        if any(t in detalle for t in REINTENTABLES):
            raise RepetirCaptura(detalle)
        if "Desafio" in detalle:
            raise PedirDesafioNuevo(detalle)
        raise ConflictoDeEstado(detalle)
    if respuesta.status_code in (401, 403):
        raise ProblemaDeCredencial(detalle)

    raise ErrorDelServicio(detalle)
```

La distincion importante es entre **repetir la captura** (culpa del entorno, se reintenta
solo) y **conflicto de estado** (hay que cambiar algo antes).
