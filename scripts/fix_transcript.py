#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - fix_transcript.py  (v3.0)

Transforma words_raw.json (faster-whisper) em words.json corrigindo SO o que o modelo errou ao
ouvir e os tempos que o alinhador estica. Por TEXTO, nao por indice -- pode ser reaplicado
depois de regenerar partes.

O que faz, nesta ordem:
  1. juncoes: "5" + ".1" -> "5.1"; "50" + "%" -> "50%"; "4" + ",53" -> "4,53"
     (dinheiro em digitos, "US$ 4,53", e feito no build_plan.normalize_tokens)
  2. pares e grafias do references/transcript-fixes.json ("Antropi que" -> Anthropic,
     "cash" -> cache, "mito" -> Mythos, "toque em" -> token)
  3. COPIAS como verdade (--copies project_meta.json do influencIA, ou --copies-txt um por
     linha): palavra da transcricao fora do vocabulario das copias e parecida (>= 0.80) com uma
     palavra das copias vira a grafia da copia ("Antropt" -> Anthropic); "para" vira "pra" se as
     copias so usam "pra"; primeira palavra de cada parte fecha a frase anterior com ponto e
     comeca em maiuscula ("marketing, valeu" -> "marketing. Valeu")
  4. tempos: palavra esticada para dentro de um silencio medido encolhe; inicios com < 0,10 s
     entre si sao reespacados (o sanitize_times do build_plan atrasa a proxima palavra)

Nunca inventa palavra que nao esta no audio nem muda o sentido. Tudo o que mudou vai para
words.json["corrections"] e para o relatorio.

Uso:
  python3 fix_transcript.py words_raw.json manifest.json words.json [--copies project_meta.json]
"""

import argparse
import copy
import difflib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
FIXES = os.path.join(SKILL_ROOT, "references", "transcript-fixes.json")
PUNCT = ".,;:!?"


def log(msg):
    sys.stderr.write("[transcript] %s\n" % msg)


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip(PUNCT + "\"'“”")


def split_punct(t):
    core = t.rstrip(PUNCT)
    return core, t[len(core):]


def apply_case(rep, original, keep_case):
    if rep in keep_case:
        return rep
    if original[:1].isupper() and rep[:1].islower():
        return rep[:1].upper() + rep[1:]
    return rep


def main():
    ap = argparse.ArgumentParser(description="EditClean: corrige grafia e tempos da transcricao")
    ap.add_argument("words_raw")
    ap.add_argument("manifest")
    ap.add_argument("out")
    ap.add_argument("--copies", default=None, help="project_meta.json (partes com 'text') ou JSON com lista de textos")
    ap.add_argument("--copies-txt", default=None, help="arquivo texto, uma copia por linha")
    ap.add_argument("--fixes", default=FIXES)
    ap.add_argument("--min-ratio", type=float, default=0.80)
    args = ap.parse_args()

    raw = json.load(open(args.words_raw, encoding="utf-8"))
    w = copy.deepcopy(raw["words"])
    man = json.load(open(args.manifest, encoding="utf-8"))
    sil = (man.get("analysis") or {}).get("silences") or []
    fixes = json.load(open(args.fixes, encoding="utf-8")) if os.path.isfile(args.fixes) else {"single": {}, "pairs": {}, "keep_case": []}
    keep_case = set(fixes.get("keep_case", []))
    changes = []

    def T(i):
        return w[i]["text"].strip()

    # ------------------------------------------------------------ 1. juncoes numericas
    i = 0
    while i < len(w) - 1:
        a, b = T(i), T(i + 1)
        ac = a.rstrip(PUNCT)
        if ac.isdigit() and re.fullmatch(r"[.,]\d+[.,;:!?]*", b):
            w[i]["text"] = ac + b; w[i]["end"] = w[i + 1]["end"]; del w[i + 1]
            changes.append("juncao %s%s" % (ac, b)); continue
        if ac.isdigit() and b.startswith("%"):
            w[i]["text"] = ac + b; w[i]["end"] = w[i + 1]["end"]; del w[i + 1]
            changes.append("juncao %s%s" % (ac, b)); continue
        i += 1

    # ------------------------------------------------------------ 2. pares e grafias do dicionario
    pairs = {k: v for k, v in (fixes.get("pairs") or {}).items()}
    i = 0
    while i < len(w) - 1:
        key = "%s %s" % (norm(T(i)), norm(T(i + 1)))
        if key in pairs:
            core2, p2 = split_punct(T(i + 1))
            w[i]["text"] = apply_case(pairs[key], T(i), keep_case) + p2
            w[i]["end"] = w[i + 1]["end"]; del w[i + 1]
            changes.append("par '%s' -> %s" % (key, pairs[key])); continue
        i += 1
    single = fixes.get("single") or {}
    for k in range(len(w)):
        core, p = split_punct(T(k))
        nk = norm(core)
        if nk in single:
            rep = apply_case(single[nk], core, keep_case)
            if rep != core:
                changes.append("%s -> %s" % (core, rep)); w[k]["text"] = rep + p

    # ------------------------------------------------------------ 3. copias como verdade
    copies = []
    if args.copies and os.path.isfile(args.copies):
        d = json.load(open(args.copies, encoding="utf-8"))
        if isinstance(d, dict) and "parts" in d:
            copies = [p["text"] for p in d["parts"] if p.get("text")]
        elif isinstance(d, list):
            copies = [x if isinstance(x, str) else x.get("text", "") for x in d]
    if args.copies_txt and os.path.isfile(args.copies_txt):
        copies += [l.strip() for l in open(args.copies_txt, encoding="utf-8") if l.strip()]
    if copies:
        vocab = {}
        for c in copies:
            for tok in re.findall(r"[\w$%.,/-]+", c, flags=re.UNICODE):
                core = tok.strip(PUNCT)
                if core:
                    vocab.setdefault(norm(core), core)
        vocab_keys = list(vocab.keys())
        # pra x para
        has_pra = "pra" in vocab; has_para = "para" in vocab
        # primeira palavra de cada parte
        STOP = set("o a os as um uma e de do da em no na pra para se mas que ao aos com por sem".split())
        firsts = set()
        for c in copies:
            m = re.match(r"\W*([\w$-]+)", c)
            if m and norm(m.group(1)) not in STOP and len(norm(m.group(1))) >= 3:
                firsts.add(norm(m.group(1)))
        for k in range(len(w)):
            core, p = split_punct(T(k))
            nk = norm(core)
            if not nk:
                continue
            if nk == "para" and has_pra and not has_para:
                w[k]["text"] = apply_case("pra", core, keep_case) + p; changes.append("para -> pra (copia)"); continue
            if nk in vocab or nk.replace(",", "").replace(".", "").isdigit():
                # mesma palavra: so a CAIXA de nome proprio conhecido (IA, Anthropic...). Nunca
                # acento: "e" x "é", "esta" x "está" sao palavras diferentes que normalizam igual.
                good = vocab.get(nk, core)
                if good != core and good in keep_case and core.lower() == good.lower():
                    w[k]["text"] = good + p; changes.append("%s -> %s (caixa)" % (core, good))
                continue
            if len(nk) < 4:
                continue
            best = difflib.get_close_matches(nk, vocab_keys, n=1, cutoff=args.min_ratio)
            if best and abs(len(best[0]) - len(nk)) <= 3:
                rep = vocab[best[0]]
                w[k]["text"] = apply_case(rep, core, keep_case) + p
                changes.append("%s -> %s (parecido com a copia, %.2f)" % (core, rep, difflib.SequenceMatcher(None, nk, best[0]).ratio()))
        # dois tokens que juntos parecem uma palavra da copia ("Antro" + "pic")
        i = 0
        while i < len(w) - 1:
            a, b = split_punct(T(i))[0], T(i + 1)
            bc, bp_ = split_punct(b)
            joined = norm(a + bc)
            if len(joined) >= 6 and joined not in vocab:
                best = difflib.get_close_matches(joined, vocab_keys, n=1, cutoff=0.85)
                if best and norm(a) not in vocab and norm(bc) not in vocab:
                    rep = vocab[best[0]]
                    w[i]["text"] = apply_case(rep, a, keep_case) + bp_; w[i]["end"] = w[i + 1]["end"]; del w[i + 1]
                    changes.append("'%s %s' -> %s (copia)" % (a, bc, rep)); continue
            i += 1
        # pontuacao de fim de parte: "marketing, valeu" -> "marketing. Valeu"
        for k in range(1, len(w)):
            core, p = split_punct(T(k))
            if norm(core) in firsts and T(k - 1).endswith(",") and core[:1].islower():
                w[k - 1]["text"] = T(k - 1).rstrip(",") + "."
                w[k]["text"] = core[:1].upper() + core[1:] + p
                changes.append("'%s, %s' -> frase nova" % (T(k - 1), core))

    # ------------------------------------------------------------ 4. tempos
    for k in range(len(w)):
        for s in sil:
            a, b = float(s["start"]), float(s["end"])
            if w[k]["start"] < a - 0.05 and w[k]["end"] > a + 0.10:
                changes.append("%s encolhida p/ fora do silencio %.2f-%.2f" % (T(k), a, b)); w[k]["end"] = round(a - 0.02, 3)
            elif a - 0.05 <= w[k]["start"] < b - 0.05 and w[k]["end"] > b:
                changes.append("%s empurrada p/ o fim do silencio %.2f" % (T(k), b)); w[k]["start"] = round(b + 0.01, 3)
    for k in range(1, len(w)):
        gap = w[k]["start"] - w[k - 1]["start"]
        if gap < 0.105:
            need = 0.11 - gap
            prev_prev_end = w[k - 2]["end"] if k >= 2 else 0.0
            room = w[k - 1]["start"] - prev_prev_end - 0.02
            shift = min(need, max(0.0, room))
            w[k - 1]["start"] = round(w[k - 1]["start"] - shift, 3)
            w[k - 1]["end"] = round(min(w[k - 1]["end"], w[k]["start"] - 0.02), 3)
            if w[k]["start"] - w[k - 1]["start"] < 0.105:
                w[k]["start"] = round(w[k - 1]["start"] + 0.11, 3)
                w[k]["end"] = max(w[k]["end"], w[k]["start"] + 0.05)
    for x in w:
        x["start"] = round(float(x["start"]), 3); x["end"] = round(max(float(x["end"]), x["start"] + 0.04), 3)

    out = dict(raw); out["words"] = w; out["corrections"] = changes
    json.dump(out, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("%d palavras, %d correcao(oes)" % (len(w), len(changes)))
    for c in changes:
        log("   " + c)
    print(" ".join(x["text"] for x in w))


if __name__ == "__main__":
    main()
