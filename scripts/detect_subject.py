#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
detect_subject.py - descobre ONDE ESTA O SUJEITO no quadro, para que a legenda
e as insercoes graficas nunca cubram o rosto.

Por que existe: as alturas de legenda (0,62) e da faixa de insercao (0,205) eram
valores medidos A MAO num video especifico. Em outro enquadramento -- pessoa mais
perto, mais longe, em pe, descentralizada -- esses numeros erram. Aqui o proprio
video responde.

Detector: YuNet (opencv_zoo, MIT), rodando em N frames amostrados. E um DNN
pequeno (232 KB) e preciso; o CascadeClassifier saiu no OpenCV 5 e a deteccao por
tom de pele nao serve (fundo de madeira/parede quente cai na mesma faixa de cor).

Grava <outdir>/subject.json com o que foi MEDIDO e o que foi DERIVADO:

  face_top_pct / chin_pct / face_height_pct / face_center_*   -> medidos
  head_top_pct          -> topo do cabelo (testa menos folga de volume)
  caption_anchor_pct    -> onde a legenda pode comecar sem tocar o queixo
  overlay_bottom_limit  -> ate onde uma insercao no topo pode descer

Uso:
    python3 detect_subject.py --video V.mp4 --outdir DIR [--samples 40]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
MODEL = os.path.join(SKILL_ROOT, "assets", "models", "face_detection_yunet_2023mar.onnx")

# quanto o topo da cabeca (cabelo) fica acima da testa, em fracao da altura da face.
# 0,12 reproduz o cabelo liso do video de referencia; 0,30 cobre cabelo com volume.
HAIR_ABOVE_BROW = 0.30
# folga entre o queixo e o topo da legenda, em fracao da altura da face
CHIN_CLEARANCE = 0.20
CHIN_CLEARANCE_MIN = 0.035
# faixa em que a ancora da legenda pode cair, aconteca o que acontecer
ANCHOR_MIN, ANCHOR_MAX = 0.42, 0.72


def _find_bin(name):
    for p in (shutil.which(name),
              os.path.expanduser("~/.local/tools/%s" % name),
              "/opt/homebrew/bin/%s" % name, "/usr/local/bin/%s" % name):
        if p and os.path.exists(p):
            return p
    return None


def probe(video):
    ffprobe = _find_bin("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe nao encontrado")
    out = subprocess.check_output([
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-show_entries", "format=duration",
        "-of", "json", video]).decode("utf-8")
    d = json.loads(out)
    st = d["streams"][0]
    return int(st["width"]), int(st["height"]), float(d["format"]["duration"])


def detect(video, samples=40, quiet=False):
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {"detected": False, "reason": "opencv-python nao instalado "
                                             "(pip3 install --user opencv-python-headless)"}
    if not os.path.exists(MODEL):
        return {"detected": False, "reason": "modelo YuNet ausente: %s" % MODEL}
    if not hasattr(cv2, "FaceDetectorYN_create"):
        return {"detected": False, "reason": "opencv sem FaceDetectorYN"}

    ffmpeg = _find_bin("ffmpeg")
    if not ffmpeg:
        return {"detected": False, "reason": "ffmpeg nao encontrado"}

    W, H, dur = probe(video)
    tmp = tempfile.mkdtemp(prefix="subject.")
    det, rows = None, []
    try:
        n = max(6, int(samples))
        for k in range(n):
            t = dur * (k + 0.5) / n
            p = os.path.join(tmp, "s%03d.jpg" % k)
            subprocess.run([ffmpeg, "-v", "error", "-ss", "%.3f" % t, "-i", video,
                            "-frames:v", "1", "-y", p],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not os.path.exists(p):
                continue
            im = cv2.imread(p)
            os.unlink(p)
            if im is None:
                continue
            h0, w0 = im.shape[:2]
            sc = 640.0 / w0
            small = cv2.resize(im, (640, int(h0 * sc)))
            if det is None:
                det = cv2.FaceDetectorYN_create(MODEL, "", (small.shape[1], small.shape[0]),
                                                0.6, 0.3, 5000)
            det.setInputSize((small.shape[1], small.shape[0]))
            _, faces = det.detect(small)
            if faces is None or len(faces) == 0:
                continue
            f = max(faces, key=lambda f: f[2] * f[3])
            x, y, w, h = (f[:4] / sc)
            rows.append({"t": round(t, 2), "top": y / h0, "bot": (y + h) / h0,
                         "cx": (x + w / 2.0) / w0, "cy": (y + h / 2.0) / h0,
                         "fh": h / float(h0)})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not rows:
        return {"detected": False, "reason": "nenhum rosto detectado em %d amostras" % samples,
                "n_samples": samples}

    import numpy as np
    tops = np.array([r["top"] for r in rows])
    bots = np.array([r["bot"] for r in rows])
    fhs = np.array([r["fh"] for r in rows])
    face_h = float(np.median(fhs))
    # p98 em vez do maximo: um frame com deteccao esticada nao decide o layout
    chin = float(np.percentile(bots, 98))
    brow = float(np.percentile(tops, 2))

    head_top = max(0.0, brow - HAIR_ABOVE_BROW * face_h)
    clearance = max(CHIN_CLEARANCE_MIN, CHIN_CLEARANCE * face_h)
    anchor = min(ANCHOR_MAX, max(ANCHOR_MIN, chin + clearance))

    return {
        "detected": True,
        "detector": "yunet_2023mar",
        "n_samples": samples, "n_detected": len(rows),
        "detection_rate": round(len(rows) / float(samples), 3),
        "measured": {
            "face_top_pct": {"p02": round(brow, 4), "median": round(float(np.median(tops)), 4)},
            "chin_pct": {"p98": round(chin, 4), "max": round(float(bots.max()), 4),
                         "median": round(float(np.median(bots)), 4)},
            "face_height_pct": round(face_h, 4),
            "face_center_x_pct": round(float(np.median([r["cx"] for r in rows])), 4),
            "face_center_y_pct": round(float(np.median([r["cy"] for r in rows])), 4),
        },
        "derived": {
            "head_top_pct": round(head_top, 4),
            "caption_anchor_pct": round(anchor, 4),
            "overlay_bottom_limit_pct": round(max(0.06, head_top - 0.012), 4),
            "chin_clearance_pct": round(clearance, 4),
        },
        "rule": ("ancora = chin_p98 + max(%.3f, %.2f x altura_da_face), presa em [%.2f, %.2f]; "
                 "topo do cabelo = testa_p02 - %.2f x altura_da_face"
                 % (CHIN_CLEARANCE_MIN, CHIN_CLEARANCE, ANCHOR_MIN, ANCHOR_MAX, HAIR_ABOVE_BROW)),
    }


def main():
    ap = argparse.ArgumentParser(description="Mede a posicao do sujeito no quadro")
    ap.add_argument("--video", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--samples", type=int, default=40)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    res = detect(args.video, args.samples, args.quiet)
    os.makedirs(args.outdir, exist_ok=True)
    out = os.path.join(args.outdir, "subject.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1, ensure_ascii=False)

    if not args.quiet:
        if res.get("detected"):
            m, dv = res["measured"], res["derived"]
            print("[subject] rosto em %d/%d amostras (%.0f%%)"
                  % (res["n_detected"], res["n_samples"], 100 * res["detection_rate"]))
            print("[subject] testa %.3f | queixo %.3f | altura da face %.3f | centro y %.3f"
                  % (m["face_top_pct"]["p02"], m["chin_pct"]["p98"],
                     m["face_height_pct"], m["face_center_y_pct"]))
            print("[subject] -> legenda em %.3f | cabeca comeca em %.3f | insercao ate %.3f"
                  % (dv["caption_anchor_pct"], dv["head_top_pct"],
                     dv["overlay_bottom_limit_pct"]))
        else:
            print("[subject] nao detectado: %s" % res.get("reason"))
            print("[subject] o plano vai usar os valores do style-profile.json")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
