import sys

sys.path.insert(0, ".")

import numpy as np

from backend.biometrics.voice import pipeline
from scripts.synth import make_speaker, synthesize_utterance

SR=16000
rng=np.random.default_rng(7)
spk=[make_speaker(i,rng) for i in range(4)]

def playback(x, seed=0, reverb=0.25, band=(120.,6500.), dist=0.08, noise=0.02):
    r=np.random.default_rng(seed)
    n=len(x)
    # respuesta de sala: ecos decrecientes
    ir=np.zeros(int(0.12*SR)); ir[0]=1.0
    for k in range(1,14):
        d=int(r.uniform(0.004,0.11)*SR)
        if d<len(ir): ir[d]+=reverb*np.exp(-3.0*d/len(ir))*r.choice([-1,1])
    y=np.convolve(x,ir)[:n]
    # limitacion de banda del altavoz+micro
    f=np.fft.rfftfreq(n,1/SR); Y=np.fft.rfft(y)
    Y*= (1/(1+(band[0]/np.maximum(f,1e-6))**4)) * (1/(1+(f/band[1])**4))
    y=np.fft.irfft(Y,n)
    # distorsion no lineal del altavoz
    y=np.tanh(y/ (np.std(y)+1e-9) * (1+dist))*np.std(y)
    y=y+noise*np.std(y)*r.standard_normal(n)
    return y/ (np.max(np.abs(y))+1e-9)

feats={}
for i,s in enumerate(spk):
    feats[i]=[pipeline.extract_features(synthesize_utterance(s,seed=1000*i+t,duration=4.))[0] for t in range(2)]

tgt=0
bg=[feats[o][0] for o in feats if o!=tgt]
ubm=pipeline.fit_ubm(bg)
model=ubm.map_adapt(feats[tgt][0],relevance=pipeline.MAP_RELEVANCE)
UMBRAL=0.4

def score(sig):
    f,_=pipeline.extract_features(sig)
    return pipeline.voice_service.verify_ubm(model,ubm,f)

genuino=synthesize_utterance(spk[tgt],seed=7,duration=4.)
impostor=synthesize_utterance(spk[1],seed=9,duration=4.)
casos=[("GENUINO en vivo",genuino,True),
       ("REPLAY del genuino (altavoz)",playback(genuino,1),False),
       ("REPLAY reverb alta",playback(genuino,2,reverb=0.45),False),
       ("REPLAY movil malo",playback(genuino,3,band=(300.,3800.),dist=0.25,noise=0.05),False),
       ("IMPOSTOR en vivo",impostor,True)]
print("Simula un ataque de reproduccion: la voz genuina sale por un altavoz")
print("y vuelve a entrar por el microfono (reverberacion, banda limitada, distorsion).\n")
print(f"{'caso':<32}{'LLR':>9}{'decision':>12}{'esperado':>12}")
for n,s,_ in casos:
    v=score(s)
    dec="ACEPTA" if v>=UMBRAL else "RECHAZA"
    exp="ACEPTA" if n.startswith("GENUINO") else "RECHAZA"
    flag="" if dec==exp else "   <-- FALLO"
    print(f"{n:<32}{v:9.2f}{dec:>12}{exp:>12}{flag}")

print("\nUn LLR alto en las filas REPLAY confirma que el sistema NO distingue")
print("una voz en vivo de una grabacion reproducida. Ver 'Limitaciones' en el README.")
