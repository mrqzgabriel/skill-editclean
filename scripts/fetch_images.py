#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - fetch_images.py

Busca e baixa imagens PERTINENTES ao que esta sendo falado no video, para
serem inseridas como overlays na edicao final.

Fontes (nenhuma exige chave de API):
  1. Openverse  (api.openverse.org)  - agregador de imagens Creative Commons
  2. Wikimedia Commons               - fallback

Filtro de qualidade: apenas imagens com resolucao media/boa (por padrao,
lado maior >= 900 px e area >= 480.000 px), descartando thumbnails.

O script NAO decide relevancia semantica sozinho: ele recebe termos de busca
(derivados da transcricao pelo Claude), baixa candidatos e devolve um JSON
com metadados + caminhos. A escolha final de quais imagens usar, e em que
momento, e do Claude, que deve inspecionar visualmente cada candidata.

Cada imagem baixada carrega licenca e atribuicao no manifesto. Imagens sem
licenca identificavel sao descartadas.

Uso:
    python3 fetch_images.py --outdir DIR --query "termo" [--query "outro"] \
        [--per-query 4] [--min-width 900] [--timeout 25]
    python3 fetch_images.py --outdir DIR --queries-json termos.json
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "EditClean/1.0 (local video editing skill; contact: local user)"

OPENVERSE = "https://api.openverse.org/v1/images/"
COMMONS = "https://commons.wikimedia.org/w/api.php"

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def _get_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _download(url, dest, timeout=30, max_bytes=12 * 1024 * 1024, retries=3):
    """
    Baixa com backoff. Servidores publicos (notadamente upload.wikimedia.org)
    respondem 429 a rajadas de acesso anonimo; esperar e repetir resolve.
    """
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if not ctype.startswith("image/"):
                    raise ValueError("nao e imagem: %s" % ctype)
                data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("imagem grande demais (> %d bytes)" % max_bytes)
            if len(data) < 8000:
                raise ValueError("imagem pequena demais (provavel thumbnail)")
            with open(dest, "wb") as fh:
                fh.write(data)
            return len(data)
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as exc:
            last = exc
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise
    if last:
        raise last
    raise RuntimeError("download falhou")


def _probe_image(path):
    """Le dimensoes reais de JPEG/PNG/WebP sem dependencias externas."""
    with open(path, "rb") as fh:
        head = fh.read(32)
        # PNG
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            fh.seek(16)
            import struct
            w, h = struct.unpack(">II", fh.read(8))
            return int(w), int(h)
        # WebP
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            fh.seek(12)
            chunk = fh.read(4)
            import struct
            if chunk == b"VP8X":
                fh.seek(24)
                b = fh.read(6)
                w = 1 + int.from_bytes(b[0:3], "little")
                h = 1 + int.from_bytes(b[3:6], "little")
                return w, h
            if chunk == b"VP8 ":
                fh.seek(26)
                b = fh.read(4)
                w = int.from_bytes(b[0:2], "little") & 0x3FFF
                h = int.from_bytes(b[2:4], "little") & 0x3FFF
                return w, h
            if chunk == b"VP8L":
                fh.seek(21)
                b = fh.read(4)
                bits = int.from_bytes(b, "little")
                w = (bits & 0x3FFF) + 1
                h = ((bits >> 14) & 0x3FFF) + 1
                return w, h
            return 0, 0
        # JPEG
        fh.seek(0)
        if fh.read(2) != b"\xff\xd8":
            return 0, 0
        while True:
            b = fh.read(1)
            if not b:
                return 0, 0
            if b != b"\xff":
                continue
            marker = fh.read(1)
            while marker == b"\xff":
                marker = fh.read(1)
            if not marker:
                return 0, 0
            m = marker[0]
            if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                continue
            seg = fh.read(2)
            if len(seg) < 2:
                return 0, 0
            seglen = int.from_bytes(seg, "big")
            if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                     0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                data = fh.read(7)
                if len(data) < 5:
                    return 0, 0
                h = int.from_bytes(data[1:3], "big")
                w = int.from_bytes(data[3:5], "big")
                return w, h
            fh.seek(max(0, seglen - 2), 1)


def search_openverse(query, count, min_width, timeout):
    params = {
        "q": query,
        "page_size": max(count * 3, 8),
        "license_type": "commercial,modification",
        "size": "large",
        "mature": "false",
    }
    url = OPENVERSE + "?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url, timeout)
    except Exception as exc:
        return [], "openverse indisponivel: %s" % exc
    out = []
    for r in data.get("results", []):
        w, h = r.get("width") or 0, r.get("height") or 0
        if max(w, h) < min_width:
            continue
        u = r.get("url")
        if not u:
            continue
        lic = r.get("license") or ""
        if not lic:
            continue
        out.append({
            "source": "openverse",
            "title": (r.get("title") or "")[:160],
            "url": u,
            "width": w,
            "height": h,
            "license": "%s %s" % (lic.upper(), r.get("license_version") or ""),
            "license_url": r.get("license_url") or "",
            "creator": (r.get("creator") or "")[:120],
            "foreign_landing_url": r.get("foreign_landing_url") or "",
        })
    return out, None


def search_commons(query, count, min_width, timeout):
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": "filetype:bitmap %s" % query,
        "gsrlimit": max(count * 2, 6),
        "gsrnamespace": "6",
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": "1600",
        "format": "json",
    }
    url = COMMONS + "?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url, timeout)
    except Exception as exc:
        return [], "commons indisponivel: %s" % exc
    pages = (data.get("query") or {}).get("pages", {}) or {}
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        w, h = ii.get("width") or 0, ii.get("height") or 0
        if max(w, h) < min_width:
            continue
        u = ii.get("thumburl") or ii.get("url")
        if not u:
            continue
        meta = ii.get("extmetadata") or {}
        lic = (meta.get("LicenseShortName") or {}).get("value", "")
        if not lic:
            continue
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", ""))[:120]
        out.append({
            "source": "wikimedia_commons",
            "title": (p.get("title") or "")[:160],
            "url": u,
            "width": ii.get("thumbwidth") or w,
            "height": ii.get("thumbheight") or h,
            "license": lic,
            "license_url": (meta.get("LicenseUrl") or {}).get("value", ""),
            "creator": artist,
            "foreign_landing_url": ii.get("descriptionurl") or "",
        })
    return out, None


def _safe_name(query, idx, url):
    base = re.sub(r"[^a-zA-Z0-9]+", "-", query.lower()).strip("-")[:40] or "img"
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ext not in ALLOWED_EXT:
        ext = ".jpg"
    return "%s_%02d%s" % (base, idx, ext)


def fetch_for_query(query, outdir, per_query, min_width, min_area, timeout, notes):
    candidates, err = search_openverse(query, per_query, min_width, timeout)
    if err:
        notes.append(err)
    if len(candidates) < per_query:
        more, err2 = search_commons(query, per_query - len(candidates), min_width, timeout)
        if err2:
            notes.append(err2)
        candidates += more

    got = []
    for i, c in enumerate(candidates):
        if len(got) >= per_query:
            break
        dest = os.path.join(outdir, _safe_name(query, len(got), c["url"]))
        try:
            size = _download(c["url"], dest, timeout)
        except Exception as exc:
            notes.append("download falhou (%s): %s" % (c["url"][:70], exc))
            continue
        rw, rh = _probe_image(dest)
        if rw and rh:
            if max(rw, rh) < min_width or (rw * rh) < min_area:
                notes.append("descartada por qualidade baixa: %s (%dx%d)" % (dest, rw, rh))
                os.remove(dest)
                continue
            c["width"], c["height"] = rw, rh
        c["path"] = dest
        c["bytes"] = size
        c["query"] = query
        c["quality"] = "boa" if max(c["width"], c["height"]) >= 1400 else "media"
        got.append(c)
    return got


def main():
    ap = argparse.ArgumentParser(
        description="EditClean - busca e baixa imagens pertinentes para overlays")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--query", action="append", default=[])
    ap.add_argument("--queries-json",
                    help="JSON com lista de termos, ou lista de {term, at, note}")
    ap.add_argument("--per-query", type=int, default=3)
    ap.add_argument("--min-width", type=int, default=900)
    ap.add_argument("--min-area", type=int, default=480000)
    ap.add_argument("--timeout", type=int, default=25)
    args = ap.parse_args()

    queries = list(args.query)
    extra_meta = {}
    if args.queries_json:
        with open(args.queries_json, encoding="utf-8") as fh:
            raw = json.load(fh)
        for item in raw:
            if isinstance(item, str):
                queries.append(item)
            elif isinstance(item, dict) and item.get("term"):
                queries.append(item["term"])
                extra_meta[item["term"]] = {k: v for k, v in item.items() if k != "term"}

    if not queries:
        sys.stderr.write("ERRO: informe ao menos um --query ou --queries-json\n")
        sys.exit(2)

    outdir = os.path.abspath(os.path.expanduser(args.outdir))
    os.makedirs(outdir, exist_ok=True)

    notes = []
    all_images = []
    for q in queries:
        sys.stderr.write("[fetch] buscando: %s\n" % q)
        imgs = fetch_for_query(q, outdir, args.per_query, args.min_width,
                               args.min_area, args.timeout, notes)
        for im in imgs:
            if q in extra_meta:
                im["hint"] = extra_meta[q]
        all_images += imgs
        sys.stderr.write("[fetch]   %d imagem(ns) aprovada(s)\n" % len(imgs))

    manifest = {
        "manifest_version": "1.0.0",
        "generated_by": "editclean/fetch_images.py",
        "outdir": outdir,
        "queries": queries,
        "min_width": args.min_width,
        "min_area": args.min_area,
        "n_images": len(all_images),
        "images": all_images,
        "notes": notes,
        "attribution_required": True,
        "attribution_note": (
            "Todas as imagens sao Creative Commons ou equivalente. O campo "
            "'license' e 'creator' de cada imagem devem ser preservados se o "
            "video for publicado; varias licencas CC exigem credito."
        ),
    }
    path = os.path.join(outdir, "images.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    sys.stderr.write("[fetch] total: %d imagem(ns) -> %s\n" % (len(all_images), path))
    print(path)


if __name__ == "__main__":
    main()
