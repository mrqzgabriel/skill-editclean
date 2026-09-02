#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - shot_page.py  (v3.0)

Print REAL de pagina oficial para as insercoes (quando o Apify estoura o plano ou quando a
melhor imagem e a propria fonte: anuncio da empresa, tabela de precos, grafico de benchmark).
Usa o Playwright de um projeto local com o Chrome do sistema (channel 'chrome'), sem baixar
navegador. Modos:

  figures   (padrao) screenshot POR ELEMENTO de cada <figure>/<table>/<svg>/[role=img] da pagina,
            depois de rolar tudo (graficos que so aparecem no scroll). Imprime indice, tamanho e
            texto de cada um para voce escolher olhando.
  full      pagina inteira (fullPage) depois de rolar.
  element   --selector "table" (primeiro que casar)

Dicas medidas (01/09/2026):
  - anuncio da Anthropic: figuras SVG so renderizam apos scroll; recorte do fullPage desloca em
    pagina longa -> usar 'figures'.
  - tabela de docs (Mintlify): --width 760 --dpr 3 (layout mobile, sem sidebar) deixa o texto
    ~35% maior na caixa do push-down. CSS zoom extrapola a viewport e sai cortado.
  - cortar cookie banner / rodape da figura depois, com PIL.

Onde esta o Playwright: --playwright-dir, ou "playwright_dir" no .credentials.json, ou
$PLAYWRIGHT_DIR, ou busca em ~/Desktop/*/*/node_modules/playwright.

Uso:
  python3 shot_page.py "https://www.anthropic.com/..." --outdir "$WORK/shots" --stem anuncio
  python3 shot_page.py "https://docs.claude.com/..." --mode element --selector table --width 760 --dpr 3
"""

import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
CRED = os.path.join(SKILL_ROOT, ".credentials.json")
NODE_SCRIPT = os.path.join(HERE, "shot_page.cjs")


def log(msg):
    sys.stderr.write("[shot] %s\n" % msg)


def find_playwright(explicit=None):
    cands = [explicit, os.environ.get("PLAYWRIGHT_DIR")]
    try:
        cands.append((json.load(open(CRED, encoding="utf-8")) or {}).get("playwright_dir"))
    except Exception:
        pass
    for c in cands:
        if c and os.path.isdir(os.path.join(c, "node_modules", "playwright")):
            return c
    for c in sorted(glob.glob(os.path.expanduser("~/Desktop/*/*/node_modules/playwright"))):
        return os.path.dirname(os.path.dirname(c))
    return None


def main():
    ap = argparse.ArgumentParser(description="EditClean: print real de pagina via Playwright")
    ap.add_argument("url")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--stem", default="page")
    ap.add_argument("--mode", default="figures", choices=["figures", "full", "element"])
    ap.add_argument("--selector", default=None)
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--dpr", type=float, default=2.0)
    ap.add_argument("--no-scroll", action="store_true")
    ap.add_argument("--no-cookies", action="store_true", help="nao tentar aceitar cookies")
    ap.add_argument("--min-width", type=int, default=300)
    ap.add_argument("--min-height", type=int, default=120)
    ap.add_argument("--playwright-dir", default=None)
    args = ap.parse_args()

    pw = find_playwright(args.playwright_dir)
    if not pw:
        raise SystemExit("Playwright nao encontrado: passe --playwright-dir <projeto com node_modules/playwright> "
                         "ou grave \"playwright_dir\" no .credentials.json")
    node = "node"
    cfg = {"url": args.url, "outdir": os.path.abspath(args.outdir), "stem": args.stem, "mode": args.mode,
           "selector": args.selector, "width": args.width, "height": args.height, "dpr": args.dpr,
           "scroll": not args.no_scroll, "accept_cookies": not args.no_cookies,
           "min_width": args.min_width, "min_height": args.min_height, "playwright_dir": pw}
    log("playwright em %s | %s %s" % (pw, args.mode, args.url))
    p = subprocess.run([node, NODE_SCRIPT, json.dumps(cfg)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        sys.stderr.write(p.stderr.decode("utf-8", "replace")[-2000:])
        raise SystemExit("playwright falhou")
    out = json.loads(p.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    for f in out["files"]:
        log("%s  %s  %s" % (os.path.basename(f["file"]), "%sx%s" % (f.get("width", ""), f.get("height", "")) if f.get("width") else "", f.get("text", "")[:100]))
    json.dump(out, open(os.path.join(args.outdir, "%s_shots.json" % args.stem), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
