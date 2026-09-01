#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - deliver.py  (v2.14)

Entrega final SEMPRE numa pasta no Desktop (pedido do Gabriel 01/09: "entrega o video + legenda
+ thumb dentro de uma pasta no desktop sempre"):

  ~/Desktop/<Nome>/
    <Nome>.mp4              video final aprovado
    <Nome>_CAPA.png         capa (make_cover.py)
    <Nome>_LEGENDA.txt      legenda do post (make_caption.py)
    <Nome>_CAPA_alternativa.png, <Nome>_CAPA_sem_texto.png   (se existirem)
    projeto/                plano, transcricao, overrides, eventos de logo, .capa.json, .legenda.json

Nada e movido: os originais ficam onde estavam; a pasta recebe COPIAS. Nunca sobrescreve uma
pasta existente sem --overwrite (senao cria <Nome> (2), (3)...).

Uso:
  python3 deliver.py --name "Claude Fable 5.1" --video final.mp4 --cover capa.png --caption legenda.txt \
          [--extra arquivo ...] [--project-dir "$WORK"] [--desktop ~/Desktop]
"""

import argparse
import glob
import os
import re
import shutil
import sys
import unicodedata


def log(msg):
    sys.stderr.write("[entrega] %s\n" % msg)


def slug(name):
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s or "video"


def main():
    ap = argparse.ArgumentParser(description="Entrega em pasta no Desktop")
    ap.add_argument("--name", required=True, help="nome do video (vira o nome da pasta e dos arquivos)")
    ap.add_argument("--video", required=True)
    ap.add_argument("--cover", default=None)
    ap.add_argument("--caption", default=None)
    ap.add_argument("--extra", action="append", default=[], help="arquivos extras (capa alternativa, sem texto...)")
    ap.add_argument("--project-dir", default=None, help="WORK da edicao: copia plano/transcricao/overrides para projeto/")
    ap.add_argument("--desktop", default=os.path.expanduser("~/Desktop"))
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.video):
        raise SystemExit("video nao encontrado: %s" % args.video)
    base = slug(args.name)
    folder = os.path.join(args.desktop, base)
    if os.path.exists(folder) and not args.overwrite:
        k = 2
        while os.path.exists("%s (%d)" % (folder, k)):
            k += 1
        folder = "%s (%d)" % (folder, k)
    os.makedirs(folder, exist_ok=True)

    def put(src, dest_name):
        if not src or not os.path.isfile(src):
            return None
        dest = os.path.join(folder, dest_name)
        shutil.copyfile(src, dest)
        return dest

    out = {"video": put(args.video, base + ".mp4")}
    out["cover"] = put(args.cover, base + "_CAPA.png") if args.cover else None
    out["caption"] = put(args.caption, base + "_LEGENDA.txt") if args.caption else None
    for x in args.extra:
        if os.path.isfile(x):
            bn = os.path.basename(x)
            # extras ganham o nome da entrega: "..._CAPA_alternativa.png" -> "<Nome>_CAPA_alternativa.png"
            tag = next((t for t in ("_CAPA", "_LEGENDA") if t in bn), None)
            put(x, base + bn[bn.index(tag):] if tag else (bn if bn.startswith(base) else base + "_" + bn))
    if args.project_dir and os.path.isdir(args.project_dir):
        pdir = os.path.join(folder, "projeto")
        os.makedirs(pdir, exist_ok=True)
        for pat in ("edit-plan.json", "words.json", "acc.json", "ov.json", "subject.json", "val.json",
                    "brand-logos.json", "partes_report.json", "partes_overrides.json", "*.capa.json", "*.legenda.json"):
            for f in glob.glob(os.path.join(args.project_dir, pat)):
                shutil.copyfile(f, os.path.join(pdir, os.path.basename(f)))
    for k in ("cover", "caption"):
        if not out.get(k):
            log("AVISO: sem %s na entrega" % ("capa" if k == "cover" else "legenda"))
    log("pasta: %s" % folder)
    for f in sorted(os.listdir(folder)):
        log("   " + f)
    print(folder)


if __name__ == "__main__":
    main()
