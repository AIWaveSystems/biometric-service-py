# Licencia

Este proyecto se publica bajo la **Licencia MIT**.

```
Copyright (c) 2026 Ilesandres
```

El texto vinculante es el del archivo [`LICENSE`](https://github.com/AIWaveSystems/biometric-service-py/blob/main/LICENSE)
en la raíz del repositorio, en inglés. Hay una
[traducción informativa al español](https://github.com/AIWaveSystems/biometric-service-py/blob/main/LICENSE.es.md)
que **no tiene valor legal**: sirve para entenderla, no para interpretarla.

---

## Qué puedes hacer

<div class="grid cards" markdown>

- :material-cash: **Uso comercial libre**

    Sin pagar nada, sin pedir permiso, sin límite de usuarios ni de instancias.

- :material-pencil: **Modificar**

    Adáptalo a lo que necesites. No hay obligación de publicar tus cambios.

- :material-share: **Redistribuir**

    Con o sin cambios, sublicenciado o vendido.

- :material-lock: **Integrarlo en software cerrado**

    La MIT no es copyleft: tu producto puede seguir siendo propietario.

</div>

---

## Qué debes hacer: la mención

!!! info "La atribución es obligatoria, no opcional"
    La licencia MIT tiene **una sola condición**: conservar el aviso de copyright
    y el texto de la licencia en las copias o partes sustanciales del software.
    Eso ya es la mención al autor, y es exigible.

Quien redistribuya este software, lo use comercialmente o lo integre en un
producto cerrado debe mantener accesible el aviso:

```
Copyright (c) 2026 Ilesandres
```

Dónde ponerlo depende del formato del producto:

| Tipo de producto | Dónde va la mención |
| --- | --- |
| Aplicación con interfaz | Pantalla de "Acerca de" o "Licencias de terceros" |
| Biblioteca o paquete | Archivo `LICENSE` o `NOTICE` incluido |
| Servicio web | Página de créditos, o `/licenses` |
| Imagen de contenedor | Archivo de licencias dentro de la imagen |
| Documentación | Sección de créditos |

### Forma de cita sugerida

Si además quieres citarlo de forma explícita, con esto basta:

```
Construido sobre Login Biométrico Service
https://github.com/AIWaveSystems/biometric-service-py
Copyright (c) 2026 Ilesandres — Licencia MIT
```

---

## Qué NO obtienes

!!! danger "Sin garantía y sin responsabilidad"
    El software se entrega **tal cual**. No hay garantía de que funcione, de que
    sea seguro, ni de que sirva para tu caso. El autor **no responde** por ningún
    daño derivado de su uso.

    Esos dos párrafos en mayúsculas del `LICENSE` no son formulismo: son la parte
    operativa de la licencia.

En un proyecto de autenticación biométrica esto pesa más de lo habitual:

- Los umbrales **no están calibrados** contra una población real de impostores.
  Están comprobados, que no es lo mismo.
- Hay [limitaciones conocidas](operacion/limitaciones.md) sin corregir que
  afectan directamente a la seguridad, empezando por el comportamiento con
  **poca luz** en el login facial.
- Ningún componente ha sido auditado por un tercero.

**Quien lo despliegue asume la responsabilidad** de validarlo para su caso,
recalibrar los umbrales con su propia población, y responder ante sus usuarios.

!!! warning "Lectura obligatoria antes de producción"
    [Limitaciones conocidas](operacion/limitaciones.md) documenta cada defecto
    medido, con sus números. No es una lista de deseos: es lo que se sabe que
    falla y con qué magnitud.

---

## Protección de datos

La licencia MIT regula el **software**, no los **datos**. Son cosas distintas y
la primera no te exime de la segunda.

Si tratas datos biométricos de personas reales, la normativa aplicable es tuya y
te obliga con independencia de esta licencia. En Colombia, la **Ley 1581 de
2012** clasifica los datos biométricos como dato sensible: exigen autorización
previa, expresa e informada del titular.

Este servicio **no incluye** un registro de consentimiento. Es una
[limitación conocida](operacion/limitaciones.md#sin-registro-de-consentimiento)
y hay que resolverla antes de tratar datos reales.

Ver [Seguridad y umbrales](operacion/seguridad.md#proteccion-de-datos).

---

## Componentes de terceros

El proyecto usa modelos y bibliotecas con sus propias licencias, que debes
respetar **además** de la MIT. Están detalladas en
[`NOTICE`](https://github.com/AIWaveSystems/biometric-service-py/blob/main/NOTICE).

| Componente | Uso | Licencia |
| --- | --- | --- |
| YuNet | Detección de rostro | MIT |
| SFace | Embedding facial | Apache 2.0 |
| OpenSeeFace `lm_model3_opt` | Landmarks para el parpadeo | BSD 2-Clause |
| WeSpeaker ResNet34-LM | Embedding de locutor | Apache 2.0 |
| FastAPI, Pydantic, PyJWT, ONNX Runtime | Base | MIT |
| NumPy, Starlette, Uvicorn | Base | BSD 3-Clause |
| OpenCV, bcrypt | Base | Apache 2.0 |
| psycopg2 | PostgreSQL | LGPL 3.0 |

!!! note "Los modelos no viajan en el repositorio"
    Se descargan con `python scripts/fetch_models.py` y están en `.gitignore`. El
    repositorio no los redistribuye. **Si construyes una imagen de contenedor que
    los incluya, sí los estás redistribuyendo** y las condiciones de sus licencias
    te aplican: en particular, Apache 2.0 exige conservar los avisos.

!!! warning "psycopg2 es LGPL"
    Enlazar contra ella desde software propietario está permitido. Solo si la
    **modificas** y redistribuyes debes publicar esos cambios bajo LGPL. El uso
    normal como dependencia no impone nada sobre tu código.

---

## Contribuciones

Las contribuciones se aceptan bajo la misma licencia MIT. Al abrir un pull
request aceptas que tu aportación se publique bajo esos términos.

El proceso está en la
[plantilla de pull request](https://github.com/AIWaveSystems/biometric-service-py/blob/main/.github/PULL_REQUEST_TEMPLATE.md).

!!! tip "Si tocas un umbral, trae la medición"
    La plantilla lo pide de forma explícita. Un umbral no se cambia porque *vaya
    mejor*: se cambia con FAR y FRR medidos, diciendo sobre qué población se
    midieron.
