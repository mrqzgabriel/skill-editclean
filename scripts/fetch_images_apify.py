#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_images_apify.py - busca imagens para as insercoes usando o Apify
(actor hooli~google-images-scraper).

Por que existe: os acervos Creative Commons (Openverse, Wikimedia) nao cobrem
nicho comercial. Para "trafego pago", "leads", "follow-up", "corretora" eles so
devolvem foto documental e clipart generico -- e os PNGs marcados como
"transparent background" do Openverse vem com o XADREZ PINTADO na imagem, sem
canal alfa. Este script existe para o caso em que o usuario autoriza busca
aberta.

ATENCAO: o que vem daqui NAO e Creative Commons. Sao imagens de sites
comerciais, com direitos autorais. Sempre:
  * recortar marcas de terceiros (e principalmente de CONCORRENTES do usuario);
  * avisar o usuario no resumo final;
  * preferir substituir por material proprio do usuario quando existir.

Token: variavel de ambiente APIFY_TOKEN, ou --token, ou o campo "apify_token"
em <skill>/.credentials.json.

Uso:
    python3 fetch_images_apify.py --outdir DIR --query "..." --query "..." \
        [--per-query 10] [--min-width 700] [--min-height 420]
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
CRED = os.path.join(SKILL_ROOT, ".credentials.json")
ACTOR = "hooli~google-images-scraper"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# dominios que so devolvem placeholder de hotlink ou marca d'agua
BLOCKED = ("foter.com", "alicdn", "findmycollege", "placeholder", "shutterstock",
           "gettyimages", "istockphoto", "dreamstime", "123rf", "depositphotos",
           "alamy", "stock.adobe")


def get_token(cli_token=None):
    if cli_token:
        return cli_token
    if os.environ.get("APIFY_TOKEN"):
        return os.environ["APIFY_TOKEN"]
    if os.path.exists(CRED):
        try:
            with open(CRED, encoding="utf-8") as fh:
                return json.load(fh).get("apify_token")
        except Exception:
            pass
    return None


def run_actor(token, queries, per_query, timeout=300):
    url = ("https://api.apify.com/v2/acts/%s/run-sync-get-dataset-items?token=%s"
           % (ACTOR, urllib.parse.quote(token)))
    body = json.dumps({"queries": queries, "maxResultsPerQuery": per_query}).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download(url, dest, timeout=25, min_bytes=9000):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < min_bytes:
        raise ValueError("arquivo pequeno demais (%d bytes) - provavel placeholder" % len(data))
    with open(dest, "wb") as fh:
        fh.write(data)
    return len(data)


def main():
    ap = argparse.ArgumentParser(description="Busca imagens via Apify (Google Images)")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--query", action="append", required=True)
    ap.add_argument("--per-query", type=int, default=10)
    ap.add_argument("--min-width", type=int, default=700)
    ap.add_argument("--min-height", type=int, default=420)
    ap.add_argument("--token", default=None)
    ap.add_argument("--max-download", type=int, default=40)
    args = ap.parse_args()

    token = get_token(args.token)
    if not token:
        sys.stderr.write(
            "ERRO: token do Apify nao encontrado.\n"
            "  defina APIFY_TOKEN, passe --token, ou grave \"apify_token\" em\n"
            "  %s (chmod 600)\n" % CRED)
        return 2

    os.makedirs(args.outdir, exist_ok=True)
    print("[apify] %d consulta(s), %d resultados cada..." % (len(args.query), args.per_query))
    try:
        items = run_actor(token, args.query, args.per_query)
    except urllib.error.HTTPError as exc:
        sys.stderr.write("ERRO: Apify respondeu %s: %s\n" % (exc.code, exc.reason))
        return 3
    except Exception as exc:
        sys.stderr.write("ERRO ao chamar o Apify: %s\n" % exc)
        return 3
    print("[apify] %d resultado(s) brutos" % len(items))

    seen, keep = set(), []
    for it in items:
        u = it.get("imageUrl") or ""
        if not u or u in seen:
            continue
        if any(b in u.lower() for b in BLOCKED):
            continue
        w, h = it.get("imageWidth") or 0, it.get("imageHeight") or 0
        if w < args.min_width or h < args.min_height:
            continue
        seen.add(u)
        keep.append(it)
    print("[apify] %d apos filtro de tamanho/dominio" % len(keep))

    saved, notes = [], []
    for i, it in enumerate(keep[:args.max_download]):
        u = it["imageUrl"]
        ext = os.path.splitext(urllib.parse.urlparse(u).path)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        name = "%02d_%s%s" % (i, hashlib.md5(u.encode()).hexdigest()[:6], ext)
        dest = os.path.join(args.outdir, name)
        try:
            size = download(u, dest)
        except Exception as exc:
            notes.append("falhou %s: %s" % (u[:60], exc))
            continue
        saved.append({
            "path": dest, "url": u, "query": it.get("query"),
            "width": it.get("imageWidth"), "height": it.get("imageHeight"),
            "title": it.get("title"), "origin": it.get("origin"),
            "page": it.get("contentUrl"), "bytes": size,
            "rights": "NAO e Creative Commons - imagem de site comercial, "
                      "provavelmente com direitos autorais",
        })

    out = os.path.join(args.outdir, "images.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"provider": "apify/google-images", "images": saved, "notes": notes},
                  fh, indent=1, ensure_ascii=False)
    print("[apify] %d imagem(ns) baixada(s) -> %s" % (len(saved), out))
    print("[apify] LEMBRETE: conferir cada imagem, recortar marcas de terceiros")
    print("[apify]           e avisar o usuario que tem direitos autorais.")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
