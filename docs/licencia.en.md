# License

This project is released under the **MIT License**.

```
Copyright (c) 2026 Ilesandres
```

The binding text is the [`LICENSE`](https://github.com/AIWaveSystems/biometric-service-py/blob/main/LICENSE)
file at the repository root, in English. There is an
[informative Spanish translation](https://github.com/AIWaveSystems/biometric-service-py/blob/main/LICENSE.es.md)
that carries **no legal weight**: it is there to be understood, not to be
interpreted.

---

## What you may do

<div class="grid cards" markdown>

- :material-cash: **Free commercial use**

    No payment, no permission needed, no cap on users or instances.

- :material-pencil: **Modify**

    Adapt it to whatever you need. No obligation to publish your changes.

- :material-share: **Redistribute**

    With or without changes, sublicensed or sold.

- :material-lock: **Embed it in closed software**

    MIT is not copyleft: your product can stay proprietary.

</div>

---

## What you must do: attribution

!!! info "Attribution is required, not optional"
    The MIT License has **one condition**: keep the copyright notice and the
    license text in copies or substantial portions of the software. That *is* the
    attribution, and it is enforceable.

Anyone who redistributes this software, uses it commercially, or embeds it in a
closed product must keep the notice accessible:

```
Copyright (c) 2026 Ilesandres
```

Where it goes depends on the product format:

| Product type | Where the notice goes |
| --- | --- |
| Application with a UI | "About" or "Third-party licenses" screen |
| Library or package | Bundled `LICENSE` or `NOTICE` file |
| Web service | Credits page, or `/licenses` |
| Container image | A licenses file inside the image |
| Documentation | Credits section |

### Suggested citation

If you also want to cite it explicitly, this is enough:

```
Built on Login Biométrico Service
https://github.com/AIWaveSystems/biometric-service-py
Copyright (c) 2026 Ilesandres — MIT License
```

---

## What you do NOT get

!!! danger "No warranty and no liability"
    The software is provided **as is**. There is no guarantee that it works, that
    it is secure, or that it fits your case. The author is **not liable** for any
    damage arising from its use.

    Those two capitalised paragraphs in `LICENSE` are not boilerplate: they are the
    operative part of the license.

In a biometric authentication project this weighs more than usual:

- The thresholds are **not calibrated** against a real impostor population. They
  are verified, which is not the same thing.
- There are unfixed [known limitations](operacion/limitaciones.md) that affect
  security directly, starting with face login behaviour in **low light**.
- No component has been audited by a third party.

**Whoever deploys it takes on the responsibility** of validating it for their
case, recalibrating thresholds against their own population, and answering to
their own users.

!!! warning "Required reading before production"
    [Known limitations](operacion/limitaciones.md) documents every measured
    defect, with its numbers. It is not a wish list: it is what is known to fail
    and by how much.

---

## Data protection

The MIT License governs the **software**, not the **data**. They are different
things, and the first does not exempt you from the second.

If you process biometric data from real people, the applicable regulation is
yours to comply with regardless of this license. In Colombia, **Law 1581 of
2012** classifies biometric data as sensitive data: it requires prior, express
and informed consent from the data subject.

This service does **not** include a consent record. That is a
[known limitation](operacion/limitaciones.md#no-consent-record) and must be
resolved before processing real data.

See [Security and thresholds](operacion/seguridad.md#data-protection).

---

## Third-party components

The project uses models and libraries with their own licenses, which you must
respect **in addition** to MIT. They are detailed in
[`NOTICE`](https://github.com/AIWaveSystems/biometric-service-py/blob/main/NOTICE).

| Component | Use | License |
| --- | --- | --- |
| YuNet | Face detection | MIT |
| SFace | Face embedding | Apache 2.0 |
| OpenSeeFace `lm_model3_opt` | Landmarks for blink detection | BSD 2-Clause |
| WeSpeaker ResNet34-LM | Speaker embedding | Apache 2.0 |
| FastAPI, Pydantic, PyJWT, ONNX Runtime | Core | MIT |
| NumPy, Starlette, Uvicorn | Core | BSD 3-Clause |
| OpenCV, bcrypt | Core | Apache 2.0 |
| psycopg2 | PostgreSQL | LGPL 3.0 |

!!! note "The models do not ship with the repository"
    They are downloaded with `python scripts/fetch_models.py` and are in
    `.gitignore`. The repository does not redistribute them. **If you build a
    container image that bundles them, you are redistributing them** and their
    license terms apply to you: Apache 2.0 in particular requires preserving the
    notices.

!!! warning "psycopg2 is LGPL"
    Linking against it from proprietary software is allowed. Only if you **modify**
    and redistribute it must you release those changes under LGPL. Ordinary use as
    a dependency imposes nothing on your own code.

---

## Contributions

Contributions are accepted under the same MIT License. By opening a pull request
you agree that your contribution is published under those terms.

The process is described in the
[pull request template](https://github.com/AIWaveSystems/biometric-service-py/blob/main/.github/PULL_REQUEST_TEMPLATE.md).

!!! tip "If you touch a threshold, bring the measurement"
    The template asks for it explicitly. A threshold is not changed because it
    *feels better*: it is changed with measured FAR and FRR, stating which
    population they were measured on.
