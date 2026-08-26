#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_plan.py - monta o edit-plan.json a partir do manifesto de analise e da
transcricao, aplicando as regras do style-profile.json v2.

Faz automaticamente o que antes era feito a mao:

  * normaliza os tokens da transcricao (junta "follow"+"-up", numero+"%",
    tira pontuacao de borda);
  * escolhe as fronteiras de corte PRESERVANDO A FALA (folga de 160 ms,
    pausa curta vira corte sem remocao, transicao acontece DENTRO do silencio);
  * escala a contagem de eventos pela duracao e reproduz a curva de ritmo
    por tercos (1 : 0,46 : 0,76);
  * resolve as escalas de zoom garantindo salto visivel em cada corte;
  * monta os blocos de legenda com quebra automatica de linha, corpo por
    bloco e posicao vertical unica;
  * calcula a timeline de saida ja descontando o encurtamento do xfade.

O que continua sendo decisao do Claude (e entra por arquivo/flag):
  * quais palavras recebem enfase serifada  (--accent)
  * quais imagens entram e quando           (--overlays)

Uso tipico:
    python3 build_plan.py --work DIR --source video.mp4 --dest saida.mp4
    python3 build_plan.py --work DIR ... --overlays ov.json --accent acc.json
"""

import argparse
import json
import math
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
PROFILE_PATH = os.path.join(SKILL_ROOT, "references", "style-profile.json")

try:
    from PIL import ImageFont
except ImportError:  # pragma: no cover
    ImageFont = None


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------

# palavras funcionais: nunca recebem enfase serifada isolada
STOPWORDS_PT = set("""
a as o os um uma uns umas de do da dos das em no na nos nas por pra para pelo pela
com sem sob sobre e ou mas que se ao aos à às es meu minha seu sua nosso nossa
eu tu ele ela nos vos eles elas voce voces me te lhe nos vos lhes isso isto aquilo
esse essa este esta aquele aquela ja nao sim mais menos muito pouco tao tanto
ser estar ter haver ir vir fazer so tambem entao porque quando onde como qual
""".split())


def _strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def normalize_tokens(words):
    """Junta 'follow'+'-up' e numero+'%', tira pontuacao de borda, sanea tempos."""
    toks, i = [], 0
    while i < len(words):
        cur = dict(words[i])
        txt = str(cur.get("text", "")).strip()
        if i + 1 < len(words):
            nxt = str(words[i + 1].get("text", "")).strip()
            low = txt.lower().rstrip(".,;:!?")
            if low == "follow" and nxt.lower().lstrip("-").rstrip(".,;:!?") in ("up",):
                toks.append({"text": "follow-up", "start": float(cur["start"]),
                             "end": float(words[i + 1]["end"])})
                i += 2
                continue
            if re.fullmatch(r"\d+([.,]\d+)?", txt) and nxt.startswith("%"):
                toks.append({"text": txt + "%", "start": float(cur["start"]),
                             "end": float(words[i + 1]["end"])})
                i += 2
                continue
        toks.append({"text": txt, "start": float(cur["start"]), "end": float(cur["end"])})
        i += 1

    out = []
    for t in toks:
        txt = t["text"].strip().strip(".,!?;:—-").strip()
        if txt:
            out.append({"text": txt, "start": t["start"], "end": t["end"]})
    return out


def sanitize_times(toks, spans, min_w=0.08):
    """Prende cada token no span de fala e desfaz starts colapsados."""
    if not spans:
        return toks
    for t in toks:
        best = min(spans, key=lambda s: 0.0 if s["start"] <= t["start"] <= s["end"]
                   else min(abs(s["start"] - t["start"]), abs(s["end"] - t["start"])))
        t["_span"] = (best["start"], best["end"])
        t["start"] = max(best["start"], min(t["start"], best["end"] - 0.05))
        t["end"] = max(t["start"] + 0.05, min(t["end"], best["end"]))

    i = 0
    while i < len(toks):
        j = i
        while (j + 1 < len(toks) and toks[j + 1]["_span"] == toks[i]["_span"]
               and toks[j + 1]["start"] - toks[j]["start"] < min_w):
            j += 1
        if j > i:
            lo = toks[i]["start"]
            if j + 1 < len(toks) and toks[j + 1]["_span"] == toks[i]["_span"]:
                hi = toks[j + 1]["start"]
            else:
                hi = toks[i]["_span"][1]
            n = j - i + 1
            step = max(0.10, (hi - lo) / max(1, n))
            for k in range(n):
                toks[i + k]["start"] = round(min(lo + step * k, hi - 0.05), 4)
            i = j + 1
        else:
            i += 1

    for k in range(len(toks) - 1):
        toks[k]["end"] = max(toks[k]["start"] + min_w,
                             min(toks[k]["end"], toks[k + 1]["start"]))
    toks[-1]["end"] = max(toks[-1]["start"] + 0.15, toks[-1]["end"])
    for t in toks:
        t.pop("_span", None)
    return toks


# --------------------------------------------------------------------------
# fronteiras de corte
# --------------------------------------------------------------------------

def pick_boundaries(manifest, toks, prof, fps, head, tail):
    """Escolhe as fronteiras respeitando a fala.

    Devolve lista de dicts {at, resume, kind}:
      gap   -> remove a pausa (com edge_padding em cada borda)
      pausa -> corte seco no meio de uma pausa curta, sem remover
      scale -> corte seco em fronteira de palavra, sem remover
    """
    an = manifest["analysis"]
    sil = an.get("silences", [])
    dur = float(manifest["source"]["duration"])
    saf = prof["cuts"]["speech_safety"]
    pad = saf["edge_padding_ms"] / 1000.0
    min_rem = saf["min_removal_ms"] / 1000.0
    min_sil_remove = prof["audio"]["min_silence_to_remove_ms"] / 1000.0

    def snap(t):
        return round(round(t * fps) / fps, 4)

    cands = []
    for s in sil:
        a, b, d = float(s["start"]), float(s["end"]), float(s["duration"])
        if a < head + 0.05 or b > tail - 0.05:
            continue                                   # cabeca/cauda ja aparadas
        mid = (a + b) / 2.0
        if d >= min_sil_remove and (d - 2 * pad) >= min_rem:
            cands.append({"at": snap(a + pad), "resume": snap(b - pad),
                          "kind": "gap", "sil": (a, b), "score": d})
        elif d >= 0.22:
            cands.append({"at": snap(mid), "resume": snap(mid),
                          "kind": "pausa", "sil": (a, b), "score": d})

    # fronteiras de palavra com folga, para cortes de escala
    word_edges = []
    for k in range(len(toks) - 1):
        gap = toks[k + 1]["start"] - toks[k]["end"]
        at = toks[k]["end"] + max(0.0, min(gap, 0.12)) / 2.0
        if head + 0.35 < at < tail - 0.35:
            word_edges.append({"at": snap(at), "resume": snap(at), "kind": "scale",
                               "sil": None, "score": gap})

    # alvo de eventos: taxa do perfil escalada pela duracao, curva por tercos
    rhythm = prof["rhythm"]
    ratio = rhythm["pacing_curve"]["ratio_between_thirds"]
    keep_dur = (tail - head) - sum(c["resume"] - c["at"] for c in cands if c["kind"] == "gap")
    total_target = max(4, int(round(rhythm["boundary_events_per_minute"] * keep_dur / 60.0)))
    w = [ratio["first"], ratio["middle"], ratio["last"]]
    base = total_target / max(1e-9, sum(w))
    per_third = [max(1, int(round(base * x))) for x in w]

    third = (tail - head) / 3.0
    def bucket(t):
        return min(2, max(0, int((t - head) / third)))

    chosen, used = [], []
    for c in sorted(cands, key=lambda x: -x["score"]):
        b = bucket(c["at"])
        if sum(1 for x in chosen if bucket(x["at"]) == b) >= per_third[b]:
            continue
        if any(abs(c["at"] - x["at"]) < 0.60 for x in chosen):
            continue
        chosen.append(c)

    # completa com cortes de escala onde o terco ainda tem folga
    for c in sorted(word_edges, key=lambda x: -x["score"]):
        b = bucket(c["at"])
        if sum(1 for x in chosen if bucket(x["at"]) == b) >= per_third[b]:
            continue
        if any(abs(c["at"] - x["at"]) < 0.85 for x in chosen):
            continue
        chosen.append(c)

    chosen.sort(key=lambda x: x["at"])
    return chosen, per_third


def place_transitions(bounds, prof, n_trans=3):
    """Marca as fronteiras que viram transicao.

    So entra onde o silencio foi MANTIDO (kind 'pausa'), para o crossfade
    consumir silencio e nunca fala. A duracao e limitada pelo silencio real.
    """
    dur_prof = prof["transitions"]["duration_ms"]
    mix = ["dissolve", "wipe", "whip_pan"]
    params = [{"easing": "ease_out", "direction": "none"},
              {"easing": "ease_out", "direction": "up"},
              {"easing": "ease_out", "direction": "left"}]

    viable = [b for b in bounds if b["kind"] == "pausa" and b["sil"]]
    if not viable:
        return []
    # espalha ao longo do video
    picks, step = [], max(1, len(viable) // max(1, n_trans))
    for i in range(min(n_trans, len(viable))):
        picks.append(viable[min(len(viable) - 1, i * step + step // 2)])

    out = []
    for i, b in enumerate(picks):
        a, e = b["sil"]
        room = max(0.0, (e - a) * 0.85)
        d = min(dur_prof["median"] / 1000.0, room)
        if d < dur_prof["min"] / 1000.0:
            continue
        b["transition"] = {"type": mix[i % len(mix)], "duration": round(d, 3),
                           "params": params[i % len(params)]}
        out.append(b)
    return out


# --------------------------------------------------------------------------
# zoom
# --------------------------------------------------------------------------

def solve_zoom(segs, prof, face_y=0.22):
    """Escolhe escala de repouso por segmento garantindo salto visivel no corte."""
    z = prof["zooms"]
    jmp = z["jump_between_segments"]
    lo_s, hi_s = 1.000, 1.080
    grid = [round(1.000 + 0.005 * k, 3) for k in range(11)]
    dmix = z["direction_mix"]
    n = len(segs)
    n_in = int(round(n * dmix["zoom_in"] / (dmix["zoom_in"] + dmix["zoom_out"])))
    dirs = ["out"] * n
    if n_in:
        for k in range(n_in):
            dirs[int(round(k * n / n_in)) % n] = "in"
    deltas = [round(z["scale_delta_pct_mean"] / 100.0 * (0.85 + 0.30 * ((i * 7) % 5) / 4.0), 4)
              for i in range(n)]
    dur_t = z["duration_ms"]["typical"] / 1000.0

    def frm(i, base):
        return round(base + deltas[i], 4) if dirs[i] == "out" else round(base - deltas[i], 4)

    def ok(kind, j):
        lim = jmp["min_delta_scale_cut"] if kind == "scale" else jmp["min_delta_gap_cut"]
        return lim <= j <= 0.060

    best = [None] * n
    def dfs(i, prev_base):
        if i == n:
            return True
        kind_prev = segs[i - 1].get("kind_after") if i else None
        cands = []
        for b in grid:
            f = frm(i, b)
            if not (lo_s - 1e-9 <= f <= hi_s + 1e-9):
                continue
            if i == 0:
                cands.append((0.0, b))
                continue
            j = abs(f - prev_base)
            if not ok(kind_prev, j):
                continue
            target = 0.040 if kind_prev == "scale" else 0.028
            cands.append((abs(j - target), b))
        cands.sort()
        for _, b in cands:
            best[i] = b
            if dfs(i + 1, b):
                return True
        best[i] = None
        return False

    if not dfs(0, None):
        for i in range(n):
            best[i] = grid[i % len(grid)]

    for i, s in enumerate(segs):
        b = best[i] if best[i] else 1.0
        f = frm(i, b)
        s["zoom"] = {
            "preset_id": "zoom_%s_%02d" % (dirs[i], i + 1),
            "scale_from": f, "scale_to": b,
            "easing": z["easing_default"],
            "anchor_x_pct": 0.5,
            "anchor_y_pct": 0.5 if dirs[i] == "out" else face_y,
            "start_offset": 0.0,
            "duration": round(min(dur_t, s["duration"] * 0.85), 3),
            "confidence": 64, "origin": "inferred",
        }
    return segs


# --------------------------------------------------------------------------
# legendas
# --------------------------------------------------------------------------

class TextMeasure(object):
    def __init__(self, prof, W, H):
        t = prof["captions"]["typography"]
        self.accent_ratio = t["accent_size_ratio"]
        self.track = t["tracking_px_at_reference"] * (W / 720.0)
        self.sans_bold = bool(t.get("sans_always_bold"))
        self.space_scale = float(prof["captions"]["layout"].get("word_space_scale", 1.0))
        self.cache = {}
        self.primary = t["font_primary"].get("path_hint") if isinstance(t.get("font_primary"), dict) else None
        self.primary = self.primary or "/System/Library/Fonts/HelveticaNeue.ttc"
        self.accent = os.path.join(SKILL_ROOT, "assets", "fonts",
                                   "PlayfairDisplay-Italic[wght].ttf")

    def font(self, style, size):
        key = (style, size)
        if key in self.cache:
            return self.cache[key]
        if ImageFont is None:
            self.cache[key] = None
            return None
        try:
            if style == "accent":
                f = ImageFont.truetype(self.accent, size)
            else:
                bold = (style == "strong") or self.sans_bold
                f = ImageFont.truetype(self.primary, size, index=1 if bold else 0)
        except Exception:
            f = None
        self.cache[key] = f
        return f

    def width(self, items, fs):
        """items = [(style, texto)]"""
        if ImageFont is None:
            # estimativa grosseira sem PIL
            n = sum(len(t) for _, t in items) + max(0, len(items) - 1)
            return n * fs * 0.5
        tot, nch = 0.0, 0
        for k, (style, txt) in enumerate(items):
            size = int(round(fs * self.accent_ratio)) if style == "accent" else fs
            f = self.font(style, size)
            tot += f.getlength(txt) if f else len(txt) * size * 0.5
            nch += len(txt)
            if k:
                fb = self.font("normal", fs)
                tot += (fb.getlength(" ") if fb else fs * 0.28) * self.space_scale
        return tot + self.track * nch


def group_blocks(toks, spans, prof):
    """Agrupa tokens em blocos de legenda quebrando nas pausas de fala."""
    b = prof["captions"]["block"]
    lo, hi = b["words_per_block_min"], b["words_per_block_max"]
    typ = b["words_per_block_typical"]

    groups = []
    if spans:
        for sp in spans:
            idx = [i for i, t in enumerate(toks)
                   if t["start"] >= sp["start"] - 1e-6 and t["start"] < sp["end"] + 1e-6]
            if idx:
                groups.append(idx)
        seen = set(i for g in groups for i in g)
        rest = [i for i in range(len(toks)) if i not in seen]
        for i in rest:
            groups.append([i])
        groups.sort(key=lambda g: g[0])
    else:
        groups = [list(range(len(toks)))]

    blocks = []
    for g in groups:
        n = len(g)
        if n <= hi:
            blocks.append(list(g))
            continue
        k = int(math.ceil(n / float(typ)))
        k = max(1, k)
        size = int(math.ceil(n / float(k)))
        size = max(lo, min(hi, size))
        for s in range(0, n, size):
            part = g[s:s + size]
            if len(part) < lo and blocks:
                blocks[-1].extend(part)
            else:
                blocks.append(part)
    return [b for b in blocks if b]


def auto_accent(toks, blocks, prof, forced=None):
    """Escolhe as palavras de enfase serifada (~18%), nunca palavra funcional."""
    share = prof["captions"]["emphasis"]["accent_share_of_words"]
    if forced:
        return set(forced.get("accent", [])), set(forced.get("strong", []))

    scored = []
    for i, t in enumerate(toks):
        w = _strip_accents(t["text"].lower())
        if w in STOPWORDS_PT or len(w) <= 2:
            continue
        s = len(w)
        if re.search(r"\d", t["text"]):
            s += 6                                   # numeros e percentuais
        if t["text"][:1].isupper() and i > 0:
            s += 3                                   # nome proprio
        if "-" in t["text"]:
            s += 2
        scored.append((s, i))
    scored.sort(reverse=True)
    n_acc = max(1, int(round(len(toks) * share)))
    accent = set(i for _, i in scored[:n_acc])

    strong = set()
    for blk in blocks:
        cand = [i for i in blk if i not in accent
                and _strip_accents(toks[i]["text"].lower()) not in STOPWORDS_PT
                and len(toks[i]["text"]) > 3]
        if cand:
            strong.add(max(cand, key=lambda i: len(toks[i]["text"])))
    return accent, strong


def layout_block(items, meas, usable, fs, max_lines=2):
    if meas.width(items, fs) <= usable:
        return [items]
    if max_lines < 2:
        return None
    best = None
    for c in range(1, len(items)):
        a, b = items[:c], items[c:]
        wa, wb = meas.width(a, fs), meas.width(b, fs)
        if wa <= usable and wb <= usable:
            sc = abs(wa - wb)
            if best is None or sc < best[0]:
                best = (sc, [a, b])
    if best:
        return best[1]
    if max_lines < 3:
        return None
    for c1 in range(1, len(items) - 1):
        for c2 in range(c1 + 1, len(items)):
            p = [items[:c1], items[c1:c2], items[c2:]]
            if all(meas.width(x, fs) <= usable for x in p):
                return p
    return None


def greedy_lines(items, meas, usable, fs):
    """Quebra gulosa: enche a linha ate a largura. Nunca devolve linha estourada
    por preguica -- so quando uma palavra sozinha ja e maior que a largura."""
    lines, cur = [], []
    for it in items:
        trial = cur + [it]
        if cur and meas.width(trial, fs) > usable:
            lines.append(cur)
            cur = [it]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def build_captions(toks, spans, segs, total, prof, W, H, src2out, seg_of,
                   forced_styles=None, anchor_pct=None):
    cap = prof["captions"]
    t = cap["typography"]
    lay = cap["layout"]
    fs_base = int(round(H * t["font_size_pct_of_canvas_height"]))
    fs_min = int(round(H * t["font_size_pct_range"][0]))
    fs_max = int(round(H * t["font_size_pct_range"][1]))
    usable = W * lay["max_width_pct_of_canvas"]
    anchor = lay["anchor_policy"] == "single_fixed" and "lower_default" or "lower_default"
    meas = TextMeasure(prof, W, H)

    groups = group_blocks(toks, spans, prof)
    accent, strong = auto_accent(toks, groups, prof, forced_styles)

    # um bloco que nao cabe em 2 linhas nem no corpo minimo deve ser DIVIDIDO,
    # nunca espremido numa linha estourada
    def items_of(g):
        return [("accent" if i in accent else ("strong" if i in strong else "normal"),
                 toks[i]["text"]) for i in g]

    split_done, guard = True, 0
    while split_done and guard < 12:
        split_done, guard, out = False, guard + 1, []
        for g in groups:
            if len(g) > 1 and layout_block(items_of(g), meas, usable, fs_min, 2) is None:
                h = len(g) // 2
                out.append(g[:h]); out.append(g[h:]); split_done = True
            else:
                out.append(g)
        groups = out

    blocks = []
    for bi, g in enumerate(groups):
        items = [("accent" if i in accent else ("strong" if i in strong else "normal"),
                  toks[i]["text"]) for i in g]
        chosen = None
        for fs in range(fs_max, fs_min - 1, -2):
            lay_ = layout_block(items, meas, usable, fs, 2)
            if lay_:
                chosen = (fs, lay_)
                break
        if not chosen:
            for fs in range(fs_max, fs_min - 1, -2):
                lay_ = layout_block(items, meas, usable, fs, 3)
                if lay_:
                    chosen = (fs, lay_)
                    break
        if not chosen:
            chosen = (fs_min, greedy_lines(items, meas, usable, fs_min))
        fs, lines = chosen

        words, k = [], 0
        for ln, part in enumerate(lines):
            for style, txt in part:
                words.append({"text": txt, "style": style, "line": ln, "_i": g[k]})
                k += 1

        first, last = toks[g[0]], toks[g[-1]]
        sl = seg_of(last["start"])
        b_start = src2out(max(first["start"], seg_of(first["start"])["src_start"]))
        b_end = src2out(min(last["end"] + 0.30, sl["src_end"]))
        blocks.append({
            "id": "L%02d" % (bi + 1), "start": b_start, "end": b_end,
            "anchor": anchor, "alignment": "center", "lines": len(lines),
            "font_size_px": int(fs), "confidence": 82, "origin": "measured",
            "words": [{"text": w["text"],
                       "start": max(b_start, src2out(toks[w["_i"]]["start"])),
                       "end": min(b_end, src2out(toks[w["_i"]]["end"])),
                       "style": w["style"], "line": w["line"]} for w in words],
        })

    # nao invadir o proximo bloco; pausa curta so quando ha folga real
    for i in range(len(blocks) - 1):
        nxt = blocks[i + 1]["start"]
        if blocks[i]["end"] > nxt:
            blocks[i]["end"] = round(nxt, 4)
        elif blocks[i]["end"] > nxt - 0.12:
            c = round(nxt - 0.12, 4)
            blocks[i]["end"] = c if c > blocks[i]["words"][-1]["start"] + 0.18 else round(nxt, 4)
    blocks[-1]["end"] = min(blocks[-1]["end"], total)

    # clamp: nenhuma palavra com end < start nem fora do bloco
    for blk in blocks:
        lo_t, hi_t = blk["start"], blk["end"]
        prev = lo_t
        for w in blk["words"]:
            w["start"] = max(lo_t, min(w["start"], hi_t - 0.02), prev)
            w["end"] = max(w["start"] + 0.02, min(w["end"], hi_t))
            prev = w["start"]
        if blk["end"] <= blk["start"]:
            blk["end"] = round(blk["start"] + 0.30, 4)
            for w in blk["words"]:
                w["end"] = min(max(w["end"], w["start"] + 0.02), blk["end"])
    return blocks, fs_base


# --------------------------------------------------------------------------
# montagem
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Monta o edit-plan.json (EditClean v2)")
    ap.add_argument("--work", required=True, help="diretorio com manifest.json e words.json")
    ap.add_argument("--source", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--out", default=None, help="caminho do edit-plan.json")
    ap.add_argument("--aspect", default="keep")
    ap.add_argument("--quality", default="high", choices=["draft", "high"])
    ap.add_argument("--overlays", default=None, help="JSON com as insercoes escolhidas")
    ap.add_argument("--accent", default=None, help="JSON {accent:[idx], strong:[idx]}")
    ap.add_argument("--head", type=float, default=None)
    ap.add_argument("--tail", type=float, default=None)
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--no-subject", action="store_true",
                    help="nao detectar o sujeito; usa as alturas fixas do perfil")
    ap.add_argument("--subject-samples", type=int, default=40)
    args = ap.parse_args()

    prof = json.load(open(PROFILE_PATH, encoding="utf-8"))
    man = json.load(open(os.path.join(args.work, "manifest.json"), encoding="utf-8"))

    # onde esta o sujeito: a legenda e as insercoes se posicionam a partir DISSO,
    # nao de um numero fixo medido noutro video
    subj = None
    sp = os.path.join(args.work, "subject.json")
    if os.path.exists(sp):
        try:
            subj = json.load(open(sp, encoding="utf-8"))
        except Exception:
            subj = None
    if subj is None and not args.no_subject:
        try:
            sys.path.insert(0, HERE)
            from detect_subject import detect as _detect
            subj = _detect(args.source, samples=args.subject_samples, quiet=True)
            with open(sp, "w", encoding="utf-8") as fh:
                json.dump(subj, fh, indent=1, ensure_ascii=False)
        except Exception as exc:
            subj = {"detected": False, "reason": "falha ao detectar: %s" % exc}
    if not (subj or {}).get("detected"):
        print("[subject] nao detectado (%s) -> usando os valores do perfil"
              % (subj or {}).get("reason", "desativado"))
    src = man["source"]
    fps = float(src["video"]["fps"]) or 30.0
    dur = float(src["duration"])
    W, H = int(src["video"]["width"]), int(src["video"]["height"])
    an = man["analysis"]
    spans = an.get("speech_spans", [])

    wpath = os.path.join(args.work, "words.json")
    toks = []
    if os.path.exists(wpath) and not args.no_captions:
        raw = json.load(open(wpath, encoding="utf-8"))
        toks = sanitize_times(normalize_tokens(raw.get("words", [])), spans)

    def snap(t):
        return round(round(t * fps) / fps, 4)

    # cabeca / cauda
    if args.head is not None:
        head = snap(args.head)
    else:
        first = spans[0]["start"] if spans else (toks[0]["start"] if toks else 0.0)
        head = snap(max(0.0, first - 0.20))
    if args.tail is not None:
        tail = snap(args.tail)
    else:
        last = spans[-1]["end"] if spans else (toks[-1]["end"] if toks else dur)
        tail = snap(min(dur, last + 0.26))

    bounds, per_third = pick_boundaries(man, toks, prof, fps, head, tail)
    trans_bounds = place_transitions(bounds, prof, n_trans=3)

    # segmentos
    segs, removed, cur = [], [], head
    for b in bounds:
        a, r = b["at"], b["resume"]
        segs.append({"src_start": cur, "src_end": a,
                     "kind_after": "scale" if b["kind"] == "scale" else "gap"})
        if r > a:
            removed.append({"id": "R%03d" % (len(removed) + 1), "src_start": a, "src_end": r,
                            "duration": round(r - a, 4),
                            "reason": "pausa removida (folga de %d ms em cada borda)"
                                      % prof["cuts"]["speech_safety"]["edge_padding_ms"],
                            "confidence": 90, "origin": "measured"})
        cur = r
    segs.append({"src_start": cur, "src_end": tail, "kind_after": None})
    removed.insert(0, {"id": "R000", "src_start": 0.0, "src_end": head, "duration": round(head, 4),
                       "reason": "cabeca muda antes da primeira palavra",
                       "confidence": 90, "origin": "measured"})
    if dur - tail > 0.01:
        removed.append({"id": "R999", "src_start": tail, "src_end": round(dur, 4),
                        "duration": round(dur - tail, 4),
                        "reason": "cauda muda apos a ultima palavra",
                        "confidence": 90, "origin": "measured"})
    segs = [s for s in segs if s["src_end"] - s["src_start"] > 0.12]
    for i, s in enumerate(segs):
        s["id"] = "S%03d" % (i + 1)
        s["duration"] = round(s["src_end"] - s["src_start"], 4)

    face_y = 0.22
    if (subj or {}).get("detected"):
        face_y = subj["measured"]["face_center_y_pct"]
    solve_zoom(segs, prof, face_y)

    # transicoes -> ids reais
    transitions = []
    for b in trans_bounds:
        nxt = next((s for s in segs if abs(s["src_start"] - b["resume"]) < 1e-6), None)
        idx = segs.index(nxt) if nxt else None
        if not idx:
            continue
        spec = b["transition"]
        transitions.append({
            "id": "TR%d" % (len(transitions) + 1), "type": spec["type"],
            "duration": spec["duration"], "params": spec["params"],
            "between": [segs[idx - 1]["id"], segs[idx]["id"]],
            "start": 0.0, "end": 0.0, "confidence": 80, "origin": "inferred",
            "evidence": "mudanca de bloco; crossfade dentro do silencio mantido",
        })

    # timeline de saida (xfade encurta)
    tr_next = {t["between"][1]: t["duration"] for t in transitions}
    acc = 0.0
    for i, s in enumerate(segs):
        if i:
            acc -= tr_next.get(s["id"], 0.0)
        s["out_start"] = round(acc, 4)
        acc += s["duration"]
    total = round(acc, 4)
    for t in transitions:
        s = next(x for x in segs if x["id"] == t["between"][1])
        t["start"] = s["out_start"]
        t["end"] = round(s["out_start"] + t["duration"], 4)

    def seg_of(x):
        for s in segs:
            if s["src_start"] - 1e-6 <= x <= s["src_end"] + 1e-6:
                return s
        for s in segs:
            if x < s["src_start"]:
                return s
        return segs[-1]

    def src2out(x):
        for s in segs:
            if s["src_start"] - 1e-6 <= x <= s["src_end"] + 1e-6:
                return round(s["out_start"] + (x - s["src_start"]), 4)
        for s in segs:
            if x < s["src_start"]:
                return s["out_start"]
        return total

    forced = json.load(open(args.accent, encoding="utf-8")) if args.accent else None
    anchor_pct = prof["captions"]["layout"]["anchor_fixed_top_pct"]
    if (subj or {}).get("detected"):
        anchor_pct = subj["derived"]["caption_anchor_pct"]

    blocks, fs_base = ([], int(round(H * 0.0574)))
    if toks and not args.no_captions:
        blocks, fs_base = build_captions(toks, spans, segs, total, prof, W, H,
                                         src2out, seg_of, forced, anchor_pct)

    overlays = []
    if args.overlays:
        ov_in = json.load(open(args.overlays, encoding="utf-8"))
        sm = prof["graphics_overlays"]["safe_margins"]
        for k, o in enumerate(ov_in if isinstance(ov_in, list) else ov_in.get("overlays", [])):
            path = os.path.expanduser(o["path"])
            iw = ih = None
            try:
                from PIL import Image
                iw, ih = Image.open(path).size
            except Exception:
                pass
            bottom_limit = sm["bottom_limit_pct"]
            if (subj or {}).get("detected"):
                bottom_limit = subj["derived"]["overlay_bottom_limit_pct"]
            max_h = (o.get("bottom_limit_pct", bottom_limit) - sm["top_pct"]) * H
            if iw and ih:
                w_px = min(W * sm["max_width_pct"], max_h * iw / float(ih))
            else:
                w_px = W * 0.6
            w_pct = round(w_px / W, 4)
            a, b = src2out(float(o["src_start"])), src2out(float(o["src_end"]))
            overlays.append({
                "id": o.get("id", "OV%d" % (k + 1)), "type": "image",
                "start": a, "end": b, "duration": round(b - a, 4),
                "params": {"path": path,
                           "pos": {"x_pct": round((1 - w_pct) / 2, 4),
                                   "y_pct": sm["top_pct"], "w_pct": w_pct},
                           "opacity": 1.0, "entry": "fade", "exit": "fade",
                           "entry_ms": 350, "exit_ms": 300,
                           "mask": "rounded_rect", "corner_radius_pct": 0.03},
                "evidence": o.get("why", ""), "confidence": 74, "origin": "inferred",
            })

    # legenda nunca sob uma insercao no topo
    for blk in blocks:
        if blk["anchor"] != "upper":
            continue
        if any(blk["start"] < o["end"] and o["start"] < blk["end"] for o in overlays):
            blk["anchor"] = "lower_default"

    cuts, n = [], 0
    tr_pairs = {(t["between"][0], t["between"][1]) for t in transitions}
    for i in range(1, len(segs)):
        pair = (segs[i - 1]["id"], segs[i]["id"])
        if pair in tr_pairs:
            continue
        n += 1
        kind = segs[i - 1].get("kind_after")
        cuts.append({"id": "C%03d" % n, "type": "jump_cut",
                     "start": segs[i]["out_start"], "end": segs[i]["out_start"], "duration": 0.0,
                     "between": list(pair),
                     "evidence": ("pausa entre falas removida" if kind == "gap"
                                  else "corte no mesmo enquadramento, com salto de escala"),
                     "confidence": 88 if kind == "gap" else 74,
                     "origin": "measured" if kind == "gap" else "inferred"})
    for s in segs:
        s.pop("kind_after", None)

    cap = prof["captions"]
    q = prof["export"]["quality"][args.quality]
    plan = {
        "plan_version": "2.0",
        "generated_by": "editclean build_plan.py",
        "profile_version": prof["profile_version"],
        "notes": [
            "Fronteiras escolhidas preservando a fala: folga de %d ms, pausa curta vira corte sem remocao, transicao dentro do silencio mantido."
            % prof["cuts"]["speech_safety"]["edge_padding_ms"],
            ("Legendas em posicao vertical unica (%.3f) e sempre centralizadas; altura %s."
             % (anchor_pct, "MEDIDA neste video (queixo em %.3f)"
                % subj["measured"]["chin_pct"]["p98"] if (subj or {}).get("detected")
                else "do perfil (rosto nao detectado)")),
            "Serifado composto %.2fx maior que o sem-serifa." % cap["typography"]["accent_size_ratio"],
        ],
        "limitations": [],
        "source": {"path": os.path.abspath(args.source), "duration": dur,
                   "width": W, "height": H, "fps": fps,
                   "has_audio": bool(man["source"].get("audio")),
                   "video_codec": src["video"].get("codec"),
                   "audio_codec": (man["source"].get("audio") or {}).get("codec"),
                   "sample_rate": (man["source"].get("audio") or {}).get("sample_rate"),
                   "aspect": src["video"].get("aspect")},
        "output": {"path": os.path.abspath(args.dest), "width": W, "height": H, "fps": fps,
                   "aspect": args.aspect, "quality": args.quality, "container": "mp4",
                   "video_codec": prof["export"]["video_codec"],
                   "audio_codec": prof["export"]["audio_codec"],
                   "crf": q["crf"], "preset": q["preset"],
                   "pixel_format": prof["export"]["pixel_format"],
                   "audio_bitrate": prof["export"]["audio_bitrate"],
                   "audio_sample_rate": prof["export"]["audio_sample_rate"],
                   "movflags": prof["export"]["movflags"]},
        "reframe": {"mode": "none", "confidence": 98, "origin": "measured"},
        "segments": segs, "removed_segments": removed,
        "cuts": cuts, "transitions": transitions, "moves": [], "blurs": [],
        "captions": {
            "enabled": bool(blocks), "source": "faster_whisper", "language": "pt",
            "font_primary": "Helvetica Neue", "font_accent": "Playfair Display",
            "font_size_px": fs_base,
            "accent_size_ratio": cap["typography"]["accent_size_ratio"],
            "line_height_ratio": cap["typography"]["line_height_ratio"],
            "side_margin_pct": cap["layout"]["side_margin_pct"],
            "tracking_px": cap["typography"]["tracking_px_at_reference"] * (W / 720.0),
            "anchors": {"lower_default": anchor_pct,
                        "footer": cap["layout"]["anchors"]["footer"]["bbox_top_pct"],
                        "upper": cap["layout"]["anchors"]["upper"]["bbox_top_pct"]},
            "max_width_pct": cap["layout"]["max_width_pct_of_canvas"],
            "shadow": {"present": bool(cap["color"]["shadow"].get("present", False)),
                       "offset_px": cap["color"]["shadow"]["offset_px"],
                       "blur_px": cap["color"]["shadow"]["blur_px"],
                       "alpha": cap["color"]["shadow"]["alpha"]},
            "soft_glow": {k: v for k, v in (cap["color"].get("soft_glow") or {}).items()
                          if k != "note"},
            "accent_glow": {k: v for k, v in (cap["color"].get("accent_glow") or {}).items()
                            if k != "note"},
            "word_space_scale": cap["layout"].get("word_space_scale", 1.0),
            "sans_bold_always": bool(cap["typography"].get("sans_always_bold")),
            "outline": {"present": False, "width_px": 0},
            "primary_hex": cap["color"]["primary_hex"],
            "accent_hex": cap["color"]["accent_hex"],
            "entry_fade_ms": cap["entry_fade_ms"],
            "blocks": blocks,
        },
        "overlays": overlays,
        "opening": {"enabled": True, "type": "blur_zoom_out",
                    "duration": prof["opening"]["duration_ms"] / 1000.0,
                    "blur_sigma_start": prof["opening"]["blur_sigma_start"],
                    "scale_start": prof["opening"]["scale_start"],
                    "easing": prof["opening"]["easing"],
                    "confidence": 92, "origin": "inferred"},
        "closing": {"enabled": True, "type": "hard_cut", "duration": 0.0,
                    "confidence": 95, "origin": "measured"},
        "color": {"enabled": True, "eq": prof["color_grading"]["eq"],
                  "colorbalance": prof["color_grading"]["colorbalance"],
                  "sharpen": prof["color_grading"]["sharpening"]["amount"],
                  "confidence": 86, "origin": "inferred"},
        "audio": {"enabled": True, "normalize": True,
                  "target_lufs": prof["audio"]["normalize"]["target_lufs"],
                  "true_peak_db": prof["audio"]["normalize"]["true_peak_db"],
                  "crossfade_on_transition": True, "music_path": None,
                  "confidence": 50, "origin": "inferred"},
    }

    out = args.out or os.path.join(args.work, "edit-plan.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=1, ensure_ascii=False)

    mins = total / 60.0 if total else 1.0
    nb = len(cuts) + len(transitions)
    rem = sum(r["duration"] for r in removed)
    print("duracao de saida : %.2f s (origem %.2f, removido %.2f = %.1f%%)"
          % (total, dur, rem, 100 * rem / dur))
    print("fronteiras       : %d = %.1f/min  [perfil %.0f]"
          % (nb, nb / mins, prof["rhythm"]["boundary_events_per_minute"]))
    print("cortes/transicoes: %d / %d (%.0f%% transicao; teto %.0f%%)"
          % (len(cuts), len(transitions), 100 * len(transitions) / max(1, nb),
             100 * prof["transitions"]["max_share_of_boundaries"]))
    print("eventos/terco    : %s  [alvo %s]"
          % ([sum(1 for c in cuts + transitions if int(c["start"] / (total / 3.0)) == k)
              for k in range(3)], per_third))
    if blocks:
        fss = [b["font_size_px"] for b in blocks]
        na = sum(1 for b in blocks for w in b["words"] if w["style"] == "accent")
        nw = sum(len(b["words"]) for b in blocks)
        print("legendas         : %d blocos, corpo %d-%d px, accent %.1f%% (perfil %.0f%%)"
              % (len(blocks), min(fss), max(fss), 100.0 * na / nw,
                 100 * cap["emphasis"]["accent_share_of_words"]))
        print("                   posicao unica %.3f, todas centralizadas%s"
              % (anchor_pct, " (medida no video)" if (subj or {}).get("detected") else " (perfil)"))
    if (subj or {}).get("detected"):
        m, dv = subj["measured"], subj["derived"]
        print("sujeito          : rosto em %.0f%% das amostras | queixo %.3f | cabeca %.3f | insercao ate %.3f"
              % (100 * subj["detection_rate"], m["chin_pct"]["p98"],
                 dv["head_top_pct"], dv["overlay_bottom_limit_pct"]))
    print("insercoes        : %d (%.1f/min)" % (len(overlays), len(overlays) / mins))
    print("plano            : %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
