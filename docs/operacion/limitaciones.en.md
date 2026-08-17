# Known limitations

This page records every measured defect, with its numbers. It is not a wish list: it is what
is known to fail and by how much.

!!! danger "Required reading before production"
    Several of these limitations affect security directly. Knowing them is a precondition
    for deciding whether this service can protect what you want protected.

---

## How the measurements were made

With **one real person** and a handful of synthetic audio files and public images. That has
a consequence running through this whole page:

!!! warning "Every FAR figure on this page is inflated in our favour"
    The voice test accounts were **text-to-speech synthesisers**, not people. Telling TTS
    apart from human speech is easy for any speaker model, so a 0% false acceptance rate
    against that population means nothing about human impostors.

    The same applies to faces: the tested impostors look very different from the account
    holder.

---

## Low light in face login

**Severity: high. Not fixed.**

Under low illumination the system fails in two contradictory ways: it either rejects
everyone, or accepts the wrong person.

### Outright rejection

Below a certain light level, YuNet detects no face:

| Gain | Frames with a face (out of 28) |
| --- | --- |
| 1.0 | 28 |
| 0.3 | 9 |
| 0.2 | **0** |

With 0 frames, the response is 400 *No se detecto la cara en suficientes frames*.

### Wrongful acceptance

Two causes that multiply each other.

**Cause 1 — noise compresses the embedding space.** Impostor similarity rises without the
impostor looking any more alike: SFace loses information and all vectors drift towards a
common point.

| Condition | `impostor_a` | `messi` |
| --- | --- | --- |
| Normal light | 0.179 | 0.224 |
| Medium light + noise | 0.197 | 0.234 |
| Low light + noise | 0.230 | 0.293 |
| Very low light + noise | — | **0.326** |

With a threshold of 0.363, the margin drops from 0.14 to **0.037**: 74% is consumed.

Other degradations push in the same direction:

| Degradation | `impostor_a` |
| --- | --- |
| Baseline | 0.179 |
| Blur | 0.254 |
| Small or distant face | 0.231 |

**Cause 2 — login takes the maximum over the burst.**

```python
best = max((_best_similarity(f, templates) for f in feature_list), default=0.0)
```

`_best_similarity` already takes the maximum over templates. With 28 frames and 13
templates that is up to **364 comparisons**, and only **one** needs to cross the threshold.

For an impostor in low light (mean 0.241, standard deviation 0.036), the expected maximum
grows with the number of frames:

| Frames | Expected maximum |
| --- | --- |
| 1 | 0.244 |
| 5 | 0.281 |
| 14 | 0.298 |
| 28 | 0.307 |
| 120 | 0.320 |

This is a multiple-comparisons problem. And noise **increases the standard deviation**, so
the tail grows exactly when the margin has narrowed.

### Why the quality gate does not stop it

`quality.check` measures **sharpness and size**, and both fire correctly. But there is **no
brightness or signal-to-noise check at all**. A dark, noisy image with a well-sized face and
defined edges passes the gate as valid.

!!! note "What remains unmeasured"
    In these tests no impostor actually crossed 0.363: the maximum was 0.326. The mechanism
    is reproduced and quantified, but **the specific reported case is not**, because the
    real burst was not available. A visually close impostor starts higher and with 0.037 of
    margin would cross effortlessly.

**Possible mitigations**, none applied yet:

1. Add a brightness and SNR check to `quality.check`
2. Replace `max()` with a **median** or a high percentile over the frames
3. Raise the threshold when the burst's mean brightness is low
4. Reject the capture below a minimum brightness, asking for more light

---

## `gmm-z` mode does not verify

**Severity: high. Mitigated, not eliminated.**

When there is no embedding and not enough background speakers, verification falls back to
the GMM z-score.

| Measurement | Result |
| --- | --- |
| Real impostor | `z = -2.444` against a `-2.5` threshold |
| Margin | **0.056** |
| EER under MAP adaptation | **50.4%** |

50.4% EER is exactly a coin flip.

!!! danger "Check `scoring` in every response"
    If it reads `"gmm-z"`, you are not verifying. Check
    [`GET /api/voice/system`](../api/voz.md#voice-system-status): `scoring_active`
    must be `"embedding"`.

---

## Voice threshold measured with very little data

**Severity: medium. Unresolved.**

| ResNet34 measurement | Value |
| --- | --- |
| Same speaker, worst case | 0.411 |
| Foreign human voice, best case | 0.270 |
| **Margin** | **+0.141** |
| Human impostors used | **1** |

A margin of 0.141 measured with a single impostor supports no claim about the real error
rate.

### The CAM++ mistake, and why it matters

The previous model (CAM++) was **broken in integration** and went undetected for a long
time, because all validation used synthetic audio: what was being measured was
real-versus-synthetic, an easy task, and the result looked excellent (+0.472 margin).

Two downloaded recordings of different people exposed it:

| Measurement | Value |
| --- | --- |
| Waveform correlation between the two recordings | 0.0008 |
| Cosine of their CAM++ embeddings | **0.9006** |
| F0 of the two voices | 186 Hz and 154 Hz |
| F0 of the account holder | 122 Hz |
| `holder ↔ downloaded_1` | **0.95** |
| `holder ↔ holder` | 0.93 |

The impostor scored **higher than the account holder himself**. The fix was switching to
ResNet34 (`hbredin/wespeaker-voxceleb-resnet34-LM`), adjusting `HIGH_FREQ` from 7600 to
8000 Hz, and lowering the thresholds from 0.40 to 0.35.

!!! danger "The lesson, not the bug"
    An easy validation set makes a broken component look excellent. No accuracy figure in
    this service means anything until it is re-measured with **different real people**.

---

## In-memory state

**Severity: medium. Unresolved.**

Three mechanisms live in process memory:

| Mechanism | Consequence with several workers |
| --- | --- |
| Rate limiter | The real limit is multiplied by the number of workers |
| Replay guard | A resent burst can land on another worker and pass |
| API key cache | A revoked key stays valid for up to **60 s** in the other workers |

Digit challenges **do** live in PostgreSQL and do not suffer from this.

**Fix:** move all three to Redis. Pending.

!!! warning "Affects any deployment with `--workers > 1`"
    With 4 workers and `AUTH_RATE_LIMIT=10`, the effective limit is 40 attempts per minute.

---

## Unencrypted templates

**Severity: medium. Unresolved.**

They are stored as plain `BYTEA`. Anyone who can read the database obtains everyone's
biometric vectors.

They do not allow reconstructing the face or voice, but they **identify uniquely and
permanently**. A face cannot be changed after a leak.

**Fix:** column-level encryption with a key held outside the database. Pending. In the
meantime, volume encryption at rest and strict access control.

---

## No consent record

**Severity: high, legally. Unresolved.**

Law 1581 of 2012 requires prior, express and informed consent for processing sensitive data.
There is no table recording who consented, when, for what purpose and for how long.

**Fix:** a consent table with a timestamp, privacy notice version and purpose, linked to the
user. Pending.

---

## `identify` does not scale

**Severity: low. Unresolved.**

`POST /api/face/identify` walks **every** template in a Python loop, comparing one by one.
It degrades linearly with thousands of users.

**Fix:** a vector index (`pgvector` with an HNSW or IVFFlat index). Pending.

`POST /api/voice/identify` has the same pattern, but there are usually fewer voice
templates.

---

## Imperfect face detection

**Severity: low.**

In the test set, **1 photo out of every 14** produced no face detection with YuNet, despite
containing a clearly visible face.

This is mitigated by sending several photos at enrolment and a burst at login: one working
frame is enough. But it explains why a particular photo can be rejected for no apparent
reason.

---

## CMVN subset bias in the digits

**Severity: high. Fixed.**

Cepstral normalisation was computed over the whole recording. Enrolment had 10 digits; the
challenge had 4. The resulting figures were not comparable.

| Measurement | Result |
| --- | --- |
| Challenges failing with identical audio | **7 out of 20** |

A first fix attempt (using voiced frames only) proved insufficient. The definitive fix was
to **store the enrolment CMVN** in `voice_digit_templates.cmvn` and impose it at
verification time.

!!! warning "Old enrolments must be repeated"
    An enrolment predating this change has no stored CMVN. It is detected as
    `cmvn_ok: false` in `GET /api/voice/digits/{username}`, and the service refuses to issue
    challenges for that account.

---

## Duplicate voice on two accounts

**Severity: high. Fixed.**

Two accounts had the same voice enrolled, and scored **0.916** against each other. A single
recording opened both, which looked like *the system accepts anyone* when in fact the system
was right: it was the same person.

**Fixed** by the duplicate check at enrolment (`VOICE_REJECT_DUPLICATES=true`).
`POST /api/voice/identify` remains the tool for detecting the case: if it returns
`ambiguous: true`, voices are shared.

---

## LLR threshold set too low

**Severity: high. Fixed.**

`VOICE_LLR_THRESHOLD` was `0.4`.

| Measurement | Result |
| --- | --- |
| Impostor attempts accepted | **6 out of 40** |
| FAR | **15%** |

The account holder was **always** the best match, so the failure was in the threshold, not
in the algorithm. It was raised to `1.2`.

!!! warning "1.2 is a floor, not a calibrated value"
    It is better than 0.4, which was measured as bad. The margin is still only 0.22 (worst
    genuine 1.35 against best impostor 1.13) over a genuine range of ~1.0, and it was
    measured against TTS voices.

---

## Near-silent audio accepted

**Severity: medium. Fixed.**

Audio at -70 dBFS produced around 490 frames classified as "voice" and was processed as if it
were speech.

**Fixed** with an absolute floor of `MIN_RMS_DBFS = -55.0` in `extract_features`.

---

## Browser audio processing

**Severity: medium. Fixed in the portal.**

Chrome applies echo cancellation, noise suppression and automatic gain control by default.
All three alter timbre enough to degrade the embedding and cause rejections of legitimate
users.

**Fixed** in the portal by capturing with `echoCancellation: false, noiseSuppression: false,
autoGainControl: false, channelCount: 1`.

!!! danger "Your frontend must do the same"
    This cannot be fixed on the server. Any custom client has to disable it. See
    [From a frontend](../integracion/frontend.md).

---

## Summary

| Limitation | Severity | Status |
| --- | --- | --- |
| Low light in face login | High | **Not fixed** |
| No consent record | High (legal) | **Unresolved** |
| `gmm-z` mode does not verify | High | Mitigated |
| Voice threshold with 1 impostor | Medium | **Unresolved** |
| In-memory state with several workers | Medium | **Unresolved** |
| Unencrypted templates | Medium | **Unresolved** |
| `identify` does not scale | Low | **Unresolved** |
| Imperfect face detection | Low | Mitigated |
| CMVN subset bias in digits | High | Fixed |
| Duplicate voice | High | Fixed |
| Low LLR threshold | High | Fixed |
| Near-silent audio accepted | Medium | Fixed |
| Browser audio processing | Medium | Fixed |
