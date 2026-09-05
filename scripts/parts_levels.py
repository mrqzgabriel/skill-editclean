#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - parts_levels.py (v3.1, 04/09)

Nivel de cada parte (LUFS integrado + true peak). A troca de voz do ElevenLabs sai com nivel
diferente por take: no video Apple a parte 4 veio 5,7 dB mais alta que as outras e com pico
+4,2 dBFS ("estourada" no segundo 23 do final). Uso:

  python3 parts_levels.py partes/parte*.mp4            # so mede e marca outliers
  python3 parts_levels.py partes/parte*.mp4 --fix      # iguala ao LUFS mediano e limita em -1,9 dBTP
                                                       # (guarda o original como parteN_v1_nivel.mp4)

Outlier: |LUFS - mediana| > 2,5 dB ou true peak > -1,0 dBFS. Video: stream copy; audio: aac 192k.
"""
import argparse, os, re, shutil, statistics, subprocess, sys


def ffmpeg():
    for c in (shutil.which("ffmpeg"), os.path.expanduser("~/.local/tools/ffmpeg"), "/opt/homebrew/bin/ffmpeg"):
        if c and os.path.isfile(c):
            return c
    raise SystemExit("ffmpeg nao encontrado")


def measure(path):
    r = subprocess.run([ffmpeg(), "-v", "info", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       stderr=subprocess.PIPE).stderr.decode("utf-8", "replace")
    I = re.findall(r"I:\s+(-?[\d.]+) LUFS", r); tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r)
    return (float(I[-1]) if I else None, float(tp[-1]) if tp else None)


def clip_runs(path, thresh=0.98, run=3):
    """Trechos de >= `run` amostras consecutivas coladas no teto = clipping "assado" na geracao
    (a ElevenLabs devolve mp3 acima de 0 dBFS). Abaixar o volume NAO conserta: e regenerar a voz."""
    import numpy as np
    pcm = subprocess.run([ffmpeg(), "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
                         stdout=subprocess.PIPE).stdout
    x = np.abs(np.frombuffer(pcm, np.float32)) >= thresh
    runs, cur = 0, 0
    for v in x:
        cur = cur + 1 if v else 0
        if cur == run:
            runs += 1
    return runs


def backup_name(path):
    d, b = os.path.split(path); stem = b[:-4]
    k = 1
    while True:
        cand = os.path.join(d, "%s_v%d_nivel.mp4" % (stem, k))
        if not os.path.exists(cand):
            return cand
        k += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--tol", type=float, default=2.5, help="desvio maximo do LUFS mediano (dB)")
    ap.add_argument("--tp-max", type=float, default=-1.0)
    ap.add_argument("--ceiling", type=float, default=0.8, help="alimiter limit (0.8 = -1.9 dBTP)")
    a = ap.parse_args()
    m = {f: measure(f) for f in a.files}
    vals = [v[0] for v in m.values() if v[0] is not None]
    if not vals:
        raise SystemExit("nada medido")
    med = statistics.median(vals)
    bad = []
    clipped = []
    for f in a.files:
        I, tp = m[f]
        flag = []
        if I is not None and abs(I - med) > a.tol:
            flag.append("%+.1f dB da mediana" % (I - med))
        if tp is not None and tp > a.tp_max:
            flag.append("pico %.1f dBFS" % tp)
            cr = clip_runs(f)
            if cr:
                flag.append("CLIPPING %d trecho(s) no teto -> REGENERAR A VOZ (nivelar nao conserta)" % cr)
                clipped.append(f)
        print("%-24s I %6.1f LUFS  TP %5.1f dBFS  %s" % (os.path.basename(f), I, tp, ("<-- " + ", ".join(flag)) if flag else "ok"))
        if flag:
            bad.append(f)
    print("mediana %.1f LUFS; %d parte(s) fora; %d com clipping" % (med, len(bad), len(clipped)))
    if not a.fix or not bad:
        sys.exit(2 if bad else 0)
    for f in [b for b in bad if b not in clipped]:
        I, tp = m[f]
        gain = med - I
        bak = backup_name(f)
        shutil.move(f, bak)
        subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", bak, "-c:v", "copy",
                        "-af", "volume=%.2fdB,alimiter=limit=%.3f:attack=5:release=60:level=false" % (gain, a.ceiling),
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", f], check=True)
        I2, tp2 = measure(f)
        print("corrigida %s: ganho %+.1f dB -> I %.1f LUFS  TP %.1f dBFS (original em %s)" % (os.path.basename(f), gain, I2, tp2, os.path.basename(bak)))
    sys.exit(0)


if __name__ == "__main__":
    main()
