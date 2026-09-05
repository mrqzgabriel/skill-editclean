#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - lipsync_check.py  (v3.4, 04/09/2026)

Mede SINCRONIA LABIAL: correlaciona a abertura da boca (contraste da ROI da boca --
cavidade escura + dentes) com o envelope RMS do audio, e devolve o atraso.
Atraso positivo = audio atrasado em relacao a boca.

  python3 lipsync_check.py partes/parte4.mp4 --win 3.5
  python3 lipsync_check.py partes/parte4.mp4 --audio veo/p4_veo.wav    # A/B de audio

Por que existe (04/09, "no 00:27 o audio nao ta sincronizado"): o Veo erra a sincronia
labial em ALGUNS takes, e nenhuma checagem anterior via isso -- `check` compara texto,
`pron`/`vowel_check` comparam fonema, e o `validate_output` so olha o comprimento dos
streams. So sobra medir a boca contra o audio.

COMO LER (o numero sozinho engana):
  - Rode com `--win 3.5` e olhe as janelas. **Confie na janela de maior correlacao.**
    Correlacao < 0,25 = sinal fraco, o atraso daquela janela nao vale nada.
  - Desvio REAL = as duas metades concordam em sinal e ordem de grandeza.
    Medido no video do Fable: parte 4 deu -0,46 / -0,38 (real); parte 10 deu +0,58
    (corr 0,29) e -0,04 (corr 0,73) -- a segunda manda, a parte esta boa.
  - Referencia de parte boa: |atraso| <= 0,10 s com correlacao >= 0,40.

O QUE NAO RESOLVE: trocar a voz do ElevenLabs pela do Veo. Medido em A/B com a MESMA
imagem, os dois audios dao o mesmo atraso e a mesma correlacao (parte 4: -0,08/0,195
com ElevenLabs, -0,25/0,219 com Veo) -- o Speech-to-Speech preserva a duracao e fica
colado no original (desvio de inicio de palavra <= 0,08 s). Quando a boca nao bate, ela
nao bate com a voz do PROPRIO Veo: o erro nasce na geracao do video.
CORRECAO: regenerar a parte e medir de novo (varia por take), guardando o take bom --
cada tentativa sobrescreve o final.mp4 no MinIO.
"""

import argparse, array, math, os, subprocess, sys
import cv2, numpy as np
FF = os.path.expanduser("~/.local/tools/ffmpeg")

MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "assets", "models", "face_detection_yunet_2023mar.onnx")


def mouth_energy(path, t0, t1):
    """Abertura da boca por quadro, com a ROI ANCORADA NOS CANTOS DA BOCA (YuNet).

    v3.4b: ROI fixa não serve -- quando a cabeça mexe (parte 4 do vídeo do Fable), o
    movimento entra no sinal como ruído, a correlação cai para ~0,2 e o atraso medido
    vira loteria. YuNet devolve 5 marcos; os pontos 3 e 4 são os cantos da boca.
    """
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    cap.set(cv2.CAP_PROP_POS_MSEC, t0 * 1000.0)
    W_ = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H_ = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    esc = 320.0 / W_
    det = cv2.FaceDetectorYN_create(MODEL, "", (320, int(H_ * esc)), 0.6, 0.3, 5000)
    out, ultimo = [], None
    n = int((t1 - t0) * fps)
    for _ in range(max(0, n)):
        ok, fr = cap.read()
        if not ok: break
        small = cv2.resize(fr, (320, int(H_ * esc)))
        det.setInputSize((small.shape[1], small.shape[0]))
        _, faces = det.detect(small)
        cx = cy = d = None
        if faces is not None and len(faces):
            f = max(faces, key=lambda f: f[2] * f[3]) / esc
            x3, y3, x4, y4 = f[10], f[11], f[12], f[13]      # cantos da boca
            cx, cy = (x3 + x4) / 2.0, (y3 + y4) / 2.0
            d = max(18.0, ((x4 - x3) ** 2 + (y4 - y3) ** 2) ** 0.5)
            ultimo = (cx, cy, d)
        elif ultimo:
            cx, cy, d = ultimo
        if cx is None:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        w2, h2 = int(d * 0.80), int(d * 0.62)
        x0, y0 = int(cx - w2), int(cy - h2)
        roi = g[max(0, y0):y0 + 2 * h2, max(0, x0):x0 + 2 * w2].astype(np.float32)
        if roi.size < 40:
            continue
        out.append(float(roi.std()))
    cap.release()
    return np.array(out), fps


def audio_env(path, t0, t1, fps, wav=None):
    raw = "_ls.raw"
    src = wav or path
    subprocess.run([FF, "-v", "error", "-y", "-ss", str(t0), "-t", str(t1 - t0), "-i", src,
                    "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", raw], check=True)
    a = array.array("h"); a.frombytes(open(raw, "rb").read()); os.remove(raw)
    a = np.array(a, dtype=np.float32) / 32768.0
    step = 16000.0 / fps
    out = []
    for i in range(int(len(a) / step)):
        seg = a[int(i * step):int((i + 1) * step)]
        out.append(float(np.sqrt((seg ** 2).mean())) if len(seg) else 0.0)
    return np.array(out)

def lag(m, e, fps, maxlag_s=0.6):
    n = min(len(m), len(e))
    if n < 20: return None, 0.0
    m, e = m[:n], e[:n]
    m = (m - m.mean()) / (m.std() + 1e-9)
    e = (e - e.mean()) / (e.std() + 1e-9)
    L = int(maxlag_s * fps)
    best, bl = -9e9, 0
    for k in range(-L, L + 1):
        if k >= 0: v = float((m[k:] * e[:n - k]).mean())
        else:      v = float((m[:n + k] * e[-k:]).mean())
        if v > best: best, bl = v, k
    return bl / fps, best

ap = argparse.ArgumentParser()
ap.add_argument("video"); ap.add_argument("--audio", default=None)
ap.add_argument("--from", dest="t0", type=float, default=0.0)
ap.add_argument("--to", dest="t1", type=float, default=1e9)
ap.add_argument("--win", type=float, default=0.0)
a = ap.parse_args()
import json
dur = float(subprocess.run([os.path.expanduser("~/.local/tools/ffprobe"), "-v", "error",
      "-show_entries", "format=duration", "-of", "json", a.video],
      capture_output=True).stdout.decode().split('"duration": "')[1].split('"')[0])
t1 = min(a.t1, dur)
janelas = []
if a.win > 0:
    t = a.t0
    while t + a.win <= t1:
        janelas.append((t, t + a.win)); t += a.win
else:
    janelas = [(a.t0, t1)]
    # v3.5 (04/09/2026): medir SO o clipe inteiro esconde erro local. No vídeo do GPT-6 Astra a
    # parte 5 deu -0.04 s no total e +0.21 s nos 3 primeiros segundos, que foi o que o Gabriel
    # ouviu ("no segundo 27 em diante ficou ruim"). Sem --win/--from, mede tambem as metades.
    meio = (a.t0 + t1) / 2.0
    if t1 - a.t0 >= 3.0:
        janelas += [(a.t0, meio + 0.2), (meio - 0.2, t1)]
for (x, y) in janelas:
    m, fps = mouth_energy(a.video, x, y)
    e = audio_env(a.video, x, y, fps, wav=a.audio)
    l, c = lag(m, e, fps)
    if l is None:
        print("  %6.1f-%6.1fs  sem rosto/amostras" % (x, y)); continue
    print("  %6.1f-%6.1fs  atraso do audio %+5.2f s   correlacao %.3f%s" %
          (x, y, l, c, "   <<< FORA" if abs(l) > 0.08 else ""))
