#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - burned_text_check.py (v3.1, 03/09)

O Veo as vezes QUEIMA legenda/lixo de texto no rodape do clipe (aleatorio por take).
Heuristica: pixels quase brancos (luma >= 225) numa faixa do rodape (60%-95% da altura),
amostrados a cada 0,4 s. Texto branco sobre roupa/fundo escuro dispara; pele e mao nao
(luma ~150-190). Uso:
  python3 burned_text_check.py partes/parte*.mp4 [--thresh 0.004]
Imprime a fracao maxima por arquivo e marca SUSPEITO acima do limiar (sai com codigo 2).
"""
import argparse, os, shutil, subprocess, sys, tempfile
from PIL import Image
import numpy as np

def ffmpeg():
    for c in (shutil.which("ffmpeg"), os.path.expanduser("~/.local/tools/ffmpeg"), "/opt/homebrew/bin/ffmpeg"):
        if c and os.path.isfile(c):
            return c
    raise SystemExit("ffmpeg nao encontrado")

def check(path, step, y0, y1, luma):
    tmp = tempfile.mkdtemp(prefix="editclean-burn-")
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", path,
                    "-vf", "fps=1/%g,scale=540:-2" % step, os.path.join(tmp, "%03d.png")], check=True)
    worst, worst_t = 0.0, 0.0
    for k, f in enumerate(sorted(os.listdir(tmp))):
        im = np.asarray(Image.open(os.path.join(tmp, f)).convert("L")).astype(np.float32)
        h = im.shape[0]
        band = im[int(h * y0):int(h * y1), :]
        frac = float((band >= luma).mean())
        if frac > worst:
            worst, worst_t = frac, k * step
    shutil.rmtree(tmp, ignore_errors=True)
    return worst, worst_t

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--thresh", type=float, default=0.004)
    ap.add_argument("--step", type=float, default=0.4)
    ap.add_argument("--band", default="0.60,0.95")
    ap.add_argument("--luma", type=int, default=225)
    a = ap.parse_args()
    y0, y1 = [float(x) for x in a.band.split(",")]
    bad = 0
    for f in a.files:
        worst, t = check(f, a.step, y0, y1, a.luma)
        flag = "SUSPEITO (texto queimado?)" if worst >= a.thresh else "ok"
        if worst >= a.thresh:
            bad += 1
        print("%-28s brancos no rodape max %.4f @%.1fs  %s" % (os.path.basename(f), worst, t, flag))
    sys.exit(2 if bad else 0)

if __name__ == "__main__":
    main()
