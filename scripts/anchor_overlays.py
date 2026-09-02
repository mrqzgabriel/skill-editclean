#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - anchor_overlays.py  (v3.0)

Gera ov.json (insercoes) e acc.json (enfases) a partir de FRASES-ANCORA no words.json, em vez
de segundos fixos. Quando uma parte e regenerada e os tempos mudam, basta rodar de novo.

job.json (trecho):
{
  "overlays": [
    {"id": "OV1", "path": "/abs/cost_chart.png", "from": "menos", "to": "preço",
     "why": "grafico oficial de custo enquanto fala 'menos gasto'"},
    {"id": "OV2", "path": "/abs/tabela.png", "from": "A sacada", "to": "guardadas", "from_occurrence": 1}
  ],
  "accent_words": ["5.1", "50%", "gasto", "US$ 4,53", "Mythos", "..."],
  "accent_max": 28
}
"from"/"to" sao a primeira e a ultima palavra (ou sequencia) da janela, comparadas sem acento,
caixa nem pontuacao; "from_occurrence"/"to_occurrence" escolhem a N-esima ocorrencia.
"accent_words" e comparado contra os tokens NORMALIZADOS do build_plan (dinheiro ja em "US$ N").

Uso:
  python3 anchor_overlays.py --job job.json --words words.json --manifest manifest.json \
          --ov ov.json --acc acc.json
"""

import argparse
import json
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_plan as bp  # noqa: E402


def log(msg):
    sys.stderr.write("[anchors] %s\n" % msg)


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip(".,;:!?\"'")


def find(words, phrase, occurrence=1):
    toks = [norm(t) for t in str(phrase).split()]
    n = 0
    for i in range(len(words) - len(toks) + 1):
        if all(norm(words[i + j]["text"]) == toks[j] for j in range(len(toks))):
            n += 1
            if n == occurrence:
                return i, i + len(toks) - 1
    return None


def main():
    ap = argparse.ArgumentParser(description="EditClean: insercoes e enfases por frases-ancora")
    ap.add_argument("--job", required=True)
    ap.add_argument("--words", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--ov", required=True)
    ap.add_argument("--acc", required=True)
    args = ap.parse_args()

    job = json.load(open(args.job, encoding="utf-8"))
    words = json.load(open(args.words, encoding="utf-8"))["words"]
    spans = (json.load(open(args.manifest, encoding="utf-8")).get("analysis") or {}).get("speech_spans") or []
    base = os.path.dirname(os.path.abspath(args.job))

    ov = []
    for o in job.get("overlays", []):
        a = find(words, o["from"], int(o.get("from_occurrence", 1)))
        b = find(words, o["to"], int(o.get("to_occurrence", 1)))
        if not a or not b:
            log("!! ancora nao achada em %s: from=%r (%s) to=%r (%s) -- insercao pulada"
                % (o.get("id"), o["from"], "ok" if a else "?", o["to"], "ok" if b else "?"))
            continue
        s, e = words[a[0]]["start"], words[b[1]]["end"] + float(o.get("pad_end", 0.0))
        if e <= s:
            log("!! %s: fim antes do inicio (%s > %s)" % (o.get("id"), s, e)); continue
        path = o["path"] if os.path.isabs(o["path"]) else os.path.join(base, o["path"])
        if not os.path.isfile(path):
            log("!! %s: imagem nao existe: %s -- pulada" % (o.get("id"), path)); continue
        ov.append({"id": o.get("id", "OV%d" % (len(ov) + 1)), "path": path, "src_start": round(s, 2), "src_end": round(e, 2),
                   "why": o.get("why", "")})
        log("%s %.2f-%.2f  %s" % (ov[-1]["id"], s, e, os.path.basename(path)))
    json.dump(ov, open(args.ov, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    toks = bp.sanitize_times(bp.normalize_tokens(words), spans)
    picks = job.get("accent_words") or []
    limit = int(job.get("accent_max", max(1, round(len(toks) * 0.18))))
    idx, used, missing = [], set(), []
    for p in picks:
        occ = 1
        if isinstance(p, dict):
            occ = int(p.get("occurrence", 1)); p = p["word"]
        cands = [i for i, t in enumerate(toks) if norm(t["text"]) == norm(p) and i not in used]
        if len(cands) < occ:
            missing.append(p); continue
        i = cands[occ - 1]; used.add(i); idx.append(i)
        if len(idx) >= limit:
            break
    if missing:
        log("enfases nao achadas: %s" % missing)
    json.dump({"accent": sorted(idx), "strong": job.get("strong", [])}, open(args.acc, "w", encoding="utf-8"))
    log("enfase %d/%d (%.0f%%): %s" % (len(idx), len(toks), 100.0 * len(idx) / max(1, len(toks)), [toks[i]["text"] for i in sorted(idx)]))
    print(json.dumps({"overlays": len(ov), "accent": len(idx), "tokens": len(toks), "missing_accents": missing}, ensure_ascii=False))


if __name__ == "__main__":
    main()
