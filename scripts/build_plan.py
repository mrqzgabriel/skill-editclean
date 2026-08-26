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

def solve_zoom(segs, prof, face_y=0.22, toks=None, avoid_punch_ids=None):
    """Escolhe escala de repouso por segmento garantindo salto visivel no corte,
    e por cima aplica os PADROES dinamicos (v2.3): punch-in cut com volta e
    push lento no respiro. Ver zooms.patterns no perfil (com a pesquisa)."""
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

    settle = z.get("settle") or {}
    st_off = float(settle.get("start_offset_s", 0.12))
    st_dur = float(settle.get("duration_s", 0.60))
    st_ease = settle.get("easing", "ease_in_out")
    for i, s in enumerate(segs):
        b = best[i] if best[i] else 1.0
        f = frm(i, b)
        off = 0.0 if i == 0 else min(st_off, s["duration"] * 0.25)
        s["zoom"] = {
            "preset_id": "zoom_%s_%02d" % (dirs[i], i + 1),
            "scale_from": f, "scale_to": b,
            "easing": st_ease,
            "anchor_x_pct": 0.5,
            "anchor_y_pct": 0.5 if dirs[i] == "out" else face_y,
            "start_offset": round(off, 3),
            "duration": round(max(0.2, min(st_dur, s["duration"] * 0.8 - off)), 3),
            "confidence": 64, "origin": "inferred",
        }

    # ------------------------------------------------------------------
    # padroes dinamicos por cima da base (v2.3)
    # ------------------------------------------------------------------
    pat = z.get("patterns") or {}
    if not pat or len(segs) < 4:
        return segs
    avoid = set(avoid_punch_ids or [])
    total_dur = sum(s["duration"] for s in segs)

    def _renorm_jump(next_idx, prev_to):
        """A fronteira depois de um padrao volta para a faixa de salto normal.

        Desloca o settle INTEIRO (from e to juntos): mover so o from esticava o
        settle para ~5% e ele virava uma varredura rapida (pico ~6 px/frame,
        medido) - justamente o tranco que estamos tirando."""
        if next_idx >= len(segs):
            return
        fz = segs[next_idx]["zoom"]
        if fz["preset_id"].startswith(("punch", "creep")):
            return
        j = abs(fz["scale_from"] - prev_to)
        if j < jmp["min_delta_gap_cut"] or j > 0.06:
            sgn = 1.0 if fz["scale_from"] >= prev_to else -1.0
            delta_settle = fz["scale_to"] - fz["scale_from"]
            new_from = round(prev_to + sgn * 0.028, 4)
            new_to = round(new_from + delta_settle, 4)
            if not (lo_s <= new_from <= hi_s and lo_s <= new_to <= hi_s):
                new_from = round(prev_to - sgn * 0.028, 4)
                new_to = round(new_from + delta_settle, 4)
            fz["scale_from"] = round(min(hi_s, max(lo_s, new_from)), 4)
            fz["scale_to"] = round(min(hi_s, max(lo_s, new_to)), 4)

    # ---- punch-in cut: corte para mais perto no momento de enfase
    pu = pat.get("punch") or {}
    if pu:
        d_lo, d_hi = pu.get("scale_delta_range", [0.10, 0.14])
        s_lo, s_hi = pu.get("seg_duration_s", [1.0, 4.2])
        rel_lo, rel_hi = pu.get("release_duration_s", [1.4, 2.6])
        max_p = max(1, int(total_dur / 60.0 * pu.get("per_minute_max", 3.0)))
        min_gap = pu.get("min_gap_s", 6.0)

        def seg_score(sg):
            ts = [t for t in (toks or [])
                  if sg["src_start"] - 1e-6 <= t["start"] < sg["src_end"]]
            sc = 0.0
            for t in ts:
                w = t["text"]
                if re.search(r"\d", w):
                    sc += 3.0                       # numero = pico de conteudo
                if len(_strip_accents(w)) >= 8:
                    sc += 1.0
                if w[:1].isupper():
                    sc += 0.5
            return sc

        cands = sorted(((seg_score(segs[i]), i) for i in range(1, len(segs) - 1)
                        if segs[i]["id"] not in avoid
                        and segs[i - 1]["id"] not in avoid
                        and segs[i + 1]["id"] not in avoid
                        and s_lo <= segs[i]["duration"] <= s_hi), reverse=True)
        chosen = []
        for sc, i in cands:
            if len(chosen) >= max_p or sc <= 0:
                break
            if any(abs(segs[i]["src_start"] - segs[j]["src_start"]) < min_gap
                   or abs(i - j) <= 1 for j in chosen):
                continue
            chosen.append(i)
        chosen.sort()

        kinds = ("release", "hold", "release")       # ~60/40, comecando suave
        for k, i in enumerate(chosen):
            sg = segs[i]
            prev_to = segs[i - 1]["zoom"]["scale_to"]
            delta = d_lo + (d_hi - d_lo) * (((k * 3) % 4) / 3.0)
            P = round(min(1.16, prev_to + delta), 4)
            if kinds[k % 3] == "release":
                # ASSENTA fechado (offset) e o zoom volta suave, comecando parado
                r_off = min(float(pu.get("release_start_offset_s", 0.35)),
                            sg["duration"] * 0.25)
                to = round(min(1.03, sg["zoom"]["scale_to"]), 4)
                dur = round(min(rel_hi, max(rel_lo, sg["duration"] * 0.7),
                                sg["duration"] * 0.85 - r_off), 3)
                sg["zoom"] = {"preset_id": "punch_release_%02d" % (k + 1),
                              "scale_from": P, "scale_to": to,
                              "easing": pu.get("release_easing", "ease_in_out"),
                              "anchor_x_pct": 0.5, "anchor_y_pct": face_y,
                              "start_offset": round(r_off, 3), "duration": dur,
                              "confidence": 70, "origin": "inferred"}
                _renorm_jump(i + 1, to)
            else:
                # segura fechado, ESTATICO (zero movimento = zero quantizacao);
                # o CORTE seguinte devolve o plano aberto
                sg["zoom"] = {"preset_id": "punch_hold_%02d" % (k + 1),
                              "scale_from": P, "scale_to": P,
                              "easing": "ease_out",
                              "anchor_x_pct": 0.5, "anchor_y_pct": face_y,
                              "start_offset": 0.0, "duration": 0.1,
                              "confidence": 70, "origin": "inferred"}
                nz = segs[i + 1]["zoom"]
                if not nz["preset_id"].startswith(("punch", "creep")):
                    dset = nz["scale_from"] - nz["scale_to"]
                    new_to = round(min(nz["scale_to"], max(lo_s, P - 0.10)), 4)
                    new_from = round(max(lo_s, min(hi_s, new_to + dset)), 4)
                    nz["scale_from"], nz["scale_to"] = new_from, new_to
                    _renorm_jump(i + 2, new_to)

    # ---- push lento no plano-respiro (o segmento mais longo)
    cr = pat.get("creep") or {}
    if cr:
        pool = [(segs[i]["duration"], i) for i in range(len(segs))
                if segs[i]["duration"] >= cr.get("min_seg_s", 4.5)
                and not segs[i]["zoom"]["preset_id"].startswith("punch")
                and segs[i]["id"] not in avoid]
        if pool:
            _, ci = max(pool)
            sg = segs[ci]
            cum = sum(x["duration"] for x in segs[:ci])
            frac = (cum + sg["duration"] / 2.0) / max(1e-6, total_dur)
            direction = "in" if frac < 2.0 / 3.0 else "out"
            d_in, d_out = cr.get("delta_in", 0.06), cr.get("delta_out", 0.05)
            prev_to = segs[ci - 1]["zoom"]["scale_to"] if ci else None
            # o ponto de partida cede espaco para o percurso completo do creep
            if direction == "in":
                base_from = round(min(sg["zoom"]["scale_from"], hi_s - d_in), 4)
            else:
                base_from = round(max(sg["zoom"]["scale_from"], lo_s + d_out), 4)
            # e a fronteira de entrada volta para a faixa de salto normal
            if prev_to is not None:
                j = abs(base_from - prev_to)
                if j < jmp["min_delta_gap_cut"] or j > 0.06:
                    room_up = (hi_s - d_in - prev_to) if direction == "in" else (hi_s - prev_to)
                    sgn = 1.0 if room_up >= 0.028 else -1.0
                    base_from = round(min(hi_s - (d_in if direction == "in" else 0.0),
                                          max(lo_s + (d_out if direction == "out" else 0.0),
                                              prev_to + sgn * 0.028)), 4)
            if direction == "in":
                target = round(base_from + d_in, 4)
                anchor = face_y
            else:
                target = round(base_from - d_out, 4)
                anchor = 0.5
            if abs(target - base_from) >= 0.02:
                c_off = min(float(cr.get("start_offset_s", 0.25)), sg["duration"] * 0.1)
                sg["zoom"]["scale_from"] = base_from
                sg["zoom"] = {"preset_id": "creep_%s" % direction,
                              "scale_from": base_from, "scale_to": target,
                              "easing": cr.get("easing", "ease_in_out"),
                              "anchor_x_pct": 0.5, "anchor_y_pct": anchor,
                              "start_offset": round(c_off, 3),
                              "duration": round(min(sg["duration"] * 0.92 - c_off,
                                                    cr.get("max_duration_s", 7.0)), 3),
                              "confidence": 68, "origin": "inferred"}
                _renorm_jump(ci + 1, target)

    # ---- passada final (v2.6): nenhum settle abaixo de 1,0. Quando a busca de
    # escalas falha (salto minimo alto aperta as restricoes), o fallback por
    # grade podia deixar scale_from < 1,0 -- o video abria alem do quadro.
    # O scale_to (repouso) e PRESERVADO quando possivel: e ele que garante o
    # salto no corte seguinte; so o percurso encurta. O teto e o dos PUNCHES
    # (1,16), nunca hi_s: um clamp em hi_s esmagaria o punch-in.
    for s in segs:
        z = s["zoom"]
        if z["scale_to"] < lo_s:          # settle inteiro abaixo: desloca junto
            d = round(lo_s - min(z["scale_from"], z["scale_to"]), 4)
            z["scale_from"] = round(z["scale_from"] + d, 4)
            z["scale_to"] = round(z["scale_to"] + d, 4)
        for k in ("scale_from", "scale_to"):
            z[k] = round(min(1.16, max(lo_s, z[k])), 4)
    return segs


def out_span_to_src(segs, t0, t1):
    """Mapeia um intervalo da TIMELINE DE SAIDA para os trechos de fonte
    correspondentes (a saida pula as pausas removidas)."""
    spans = []
    for s in segs:
        o0 = s["out_start"]
        o1 = o0 + s["duration"]
        lo, hi = max(t0, o0), min(t1, o1)
        if hi - lo > 0.05:
            spans.append((s["src_start"] + (lo - o0), s["src_start"] + (hi - o0)))
    return spans


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
    ap.add_argument("--no-push", action="store_true",
                    help="desliga o push-down (video descendo para a insercao aparecer maior)")
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

    # o primeiro segmento precisa comportar a abertura (~0,7 s + folga);
    # se o primeiro corte cair cedo demais, funde com o segundo segmento
    trans_resumes = {b["resume"] for b in trans_bounds}
    while (len(segs) > 1
           and segs[0]["src_end"] - segs[0]["src_start"] < 0.95
           and segs[1]["src_start"] not in trans_resumes):
        segs[0]["src_end"] = segs[1]["src_end"]
        segs[0]["kind_after"] = segs[1]["kind_after"]
        del segs[1]

    for i, s in enumerate(segs):
        s["id"] = "S%03d" % (i + 1)
        s["duration"] = round(s["src_end"] - s["src_start"], 4)

    # transicoes -> ids reais (antes do zoom: punch nunca cola em transicao)
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

    face_y = 0.22
    if (subj or {}).get("detected"):
        face_y = subj["measured"]["face_center_y_pct"]
    avoid_ids = {sid for t in transitions for sid in t["between"]}
    solve_zoom(segs, prof, face_y, toks, avoid_ids)

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

    # abertura: vira o zoom do PRIMEIRO segmento (herda o supersampling) e o
    # desfoque vira eventos blurs[] com sigma decrescente (continuo, sem pulsar)
    op = prof.get("opening") or {}
    blurs = []
    if op.get("integrated_into_first_segment") and segs:
        odur = min(op.get("duration_ms", 700) / 1000.0, segs[0]["duration"] * 0.6)
        s0z = segs[0]["zoom"]
        segs[0]["zoom"] = {"preset_id": "opening_blur_zoom_out",
                           "scale_from": round(float(op.get("scale_start", 1.08)), 4),
                           "scale_to": s0z["scale_to"],
                           "easing": op.get("easing", "ease_out"),
                           "anchor_x_pct": 0.5, "anchor_y_pct": 0.5,
                           "start_offset": 0.0, "duration": round(odur, 3),
                           "confidence": 80, "origin": "inferred"}

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
            # imagem VERTICAL nao cabe na faixa acima da cabeca: vira cartao
            # central (v2.6) -- grande, no centro, com o video desfocado atras
            cc_cfg = (prof.get("graphics_overlays") or {}).get("center_card") or {}
            is_center = bool(cc_cfg.get("enabled_default", True) and iw and ih
                             and (iw / float(ih)) < float(cc_cfg.get("max_aspect", 1.15)))
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
            if is_center:
                overlays[-1]["_center_card"] = True

    # ---- push-down (padrao v2.5): o video desce e abre palco para a insercao.
    # Aplicado no render DEPOIS das legendas -- elas descem junto, sem trocar de
    # ancora. Janelas alinhadas a fronteira de bloco de legenda e fora de
    # transicao; a imagem so entra em fade depois da descida completa.
    push_plan = None
    pd_cfg = (prof.get("graphics_overlays") or {}).get("push_down") or {}
    band_ovs = [o for o in overlays if not o.get("_center_card")]
    if band_ovs and blocks and pd_cfg.get("enabled_default", True) and not args.no_push:
        lh = prof["captions"]["typography"]["line_height_ratio"]
        # fundo real do texto: ancora + linhas + folga p/ descensor do serifado
        text_bottom = max(anchor_pct * H + b["lines"] * b["font_size_px"] * lh
                          + 0.35 * b["font_size_px"] for b in blocks)
        ceiling = H * (1.0 - float(pd_cfg.get("ui_reserve_pct", 0.115)))
        D = int(round(min(H * float(pd_cfg.get("dist_max_pct", 0.16)),
                          ceiling - text_bottom)))
        ramp = float(pd_cfg.get("ramp_s", 0.35))
        if D < int(pd_cfg.get("dist_min_px", 100)):
            print("[plan] push-down desligado: legenda desce ate %.0fpx, folga D=%dpx "
                  "e menor que o minimo" % (text_bottom, D))
        else:
            trs = [(t["start"], t["end"]) for t in transitions]

            def _clear_fwd(t0, t1):
                for ta, tb in trs:
                    if t0 < tb and ta < t1:
                        d = tb + 0.005 - t0
                        t0 += d
                        t1 += d
                return t0, t1

            def _snap_start(t):
                # fronteira de bloco mais proxima (empate prefere a mais tarde);
                # nunca desloca mais que 0.45s
                for b in blocks:
                    if b["start"] - 1e-6 <= t < b["end"]:
                        d1, d2 = t - b["start"], b["end"] - t
                        cand = b["end"] if (d2 < d1 or abs(d1 - d2) < 0.1) else b["start"]
                        return cand if abs(cand - t) <= 0.45 else t
                return t

            def _snap_end(t):
                for b in blocks:
                    if b["start"] - 1e-6 <= t < b["end"]:
                        return b["end"] if (b["end"] - t) <= 0.6 else t
                return t

            sm2 = prof["graphics_overlays"]["safe_margins"]
            bl2 = sm2["bottom_limit_pct"]
            if (subj or {}).get("detected"):
                bl2 = subj["derived"]["overlay_bottom_limit_pct"]
            base_strip = (bl2 - sm2["top_pct"]) * H
            bh = int(base_strip + D) // 2 * 2
            bw_box = int(W * float(pd_cfg.get("box_width_pct", 0.825))) // 2 * 2
            maxcrop = float(pd_cfg.get("max_vertical_crop", 0.25))

            windows, placed = [], []
            for ov in band_ovs:
                a0 = max(0.9, _snap_start(ov["start"]))
                a0, _ = _clear_fwd(a0, a0 + ramp)
                up_end = _snap_end(ov["end"])
                changed = True
                while changed:      # bloco nascendo dentro da subida empurra o fim
                    changed = False
                    for b in blocks:
                        if up_end - ramp - 1e-6 < b["start"] < up_end - 1e-6:
                            up_end, changed = b["end"], True
                up_end = min(up_end, total)
                img_st, img_en = a0 + ramp, up_end - ramp
                if img_en - img_st < 0.7:
                    print("[plan] %s: janela curta demais para push (%.2fs), "
                          "fica no top_band" % (ov["id"], img_en - img_st))
                    continue
                placed.append((ov, a0, up_end, img_st, img_en))

            # ---- folga REAL por janela (v2.6): a testa dela sobe e desce ao
            # longo do video (medido: 0,25 a 0,40 da altura no mesmo video).
            # Medir o topo da face NO TRECHO de cada insercao permite caixa ate
            # ~2x mais alta -- uma 16:9 entra INTEIRA -- em vez do p02 global.
            hw_cfg = (prof.get("graphics_overlays") or {}).get("per_window_headroom") or {}
            fh_min = [None] * len(placed)
            if placed and hw_cfg.get("enabled", True) and not args.no_subject:
                try:
                    sys.path.insert(0, HERE)
                    from detect_subject import forehead_min_in_spans
                    spans, idx_of = [], []
                    for i, (ov, a0, up_end, img_st, img_en) in enumerate(placed):
                        for sp in out_span_to_src(segs, img_st, img_en):
                            spans.append(sp)
                            idx_of.append(i)
                    per_span = forehead_min_in_spans(
                        args.source, spans,
                        step_s=float(hw_cfg.get("sample_step_s", 0.12)))
                    for j, v in enumerate(per_span):
                        if v is None:
                            continue
                        i = idx_of[j]
                        fh_min[i] = v if fh_min[i] is None else min(fh_min[i], v)
                except Exception as exc:
                    print("[plan] folga por janela indisponivel (%s); usando o p02 global" % exc)

            margin = int(round(float(hw_cfg.get("margin_before_forehead_px", 26))
                               * H / 1920.0))
            top_px = int(round(sm2["top_pct"] * H))
            bw_max = int(W * float(sm2.get("max_width_pct", 0.86))) // 2 * 2
            for i, (ov, a0, up_end, img_st, img_en) in enumerate(placed):
                room = bh
                if fh_min[i] is not None:
                    meas = int(fh_min[i] * H) + D - margin - top_px
                    room = max(120, min(meas, int(0.45 * H))) // 2 * 2
                try:
                    from PIL import Image
                    iw2, ih2 = Image.open(ov["params"]["path"]).size
                    a_img = iw2 / float(ih2)
                except Exception:
                    a_img = bw_box / float(room)
                # preferir a imagem INTEIRA: caixa no aspecto da propria imagem,
                # limitada pela folga medida e pela largura maxima. So cai no
                # cover (com corte <= maxcrop) se a inteira ficar estreita demais.
                fit_h = int(bw_max / a_img) // 2 * 2
                if fit_h <= room:
                    bw_i, bh_i = bw_max, fit_h            # inteira, largura maxima
                elif int(room * a_img) >= int(0.31 * W):
                    bh_i = room                            # inteira, altura maxima
                    bw_i = min(bw_max, int(room * a_img)) // 2 * 2
                else:
                    bh_i = room                            # cover com corte
                    bw_i = max(int(0.31 * W),
                               int(room * a_img / (1.0 - maxcrop))) // 2 * 2
                    bw_i = min(bw_i, bw_max) // 2 * 2
                ov["params"]["mode"] = "push_down"
                ov["params"]["box"] = {"w_px": bw_i, "h_px": bh_i}
                ov["params"]["pos"] = {"x_pct": round((1 - bw_i / float(W)) / 2, 4),
                                       "y_pct": sm2["top_pct"],
                                       "w_pct": round(bw_i / float(W), 4)}
                ov["params"]["corner_radius_pct"] = 0.03
                ov["start"], ov["end"] = round(img_st, 4), round(img_en, 4)
                ov["duration"] = round(img_en - img_st, 4)
                windows.append([round(a0, 4), round(up_end, 4)])

            if windows:
                windows.sort()
                merged = [windows[0]]
                for a0, b0 in windows[1:]:   # janelas coladas viram uma so
                    if a0 < merged[-1][1] + 0.4:
                        merged[-1][1] = max(merged[-1][1], b0)
                    else:
                        merged.append([a0, b0])
                push_plan = {"enabled": True, "dist_px": D, "ramp_s": ramp,
                             "origin": "inferred",
                             "windows": [{"down_start": a0, "up_end": b0}
                                         for a0, b0 in merged]}

                # insercoes vizinhas na MESMA janela: troca SECA e sem buraco.
                # Fade cruzado aqui vira dupla exposicao (as duas alfas somam
                # sobre o palco) e o intervalo im_en/im_st deixa a faixa vazia.
                pushed = sorted((p[0] for p in placed), key=lambda o: o["start"])
                def _win_of(o):
                    for k, (wa, wb) in enumerate(merged):
                        if wa - 1e-6 <= o["start"] and o["end"] <= wb + 1e-6:
                            return k
                    return -1
                for a, b in zip(pushed, pushed[1:]):
                    if (_win_of(a) == _win_of(b) >= 0
                            and 0 <= b["start"] - a["end"] < 1.2):
                        a["end"] = b["start"]
                        a["duration"] = round(a["end"] - a["start"], 4)
                        a["params"]["exit_ms"] = 0
                        b["params"]["entry_ms"] = 0

    # ---- cartao central (v2.6): insercao VERTICAL (aspecto < ~1,15) nao cabe
    # na faixa acima da cabeca -- num quadro 9:16 ela renderizaria com ~1/4 da
    # largura, ilegivel. Em vez disso ela vira um CARTAO grande no centro, com
    # o video inteiro DESFOCADO atras (gblur full_frame) e a legenda ancorada
    # logo abaixo da imagem: imagem+legenda formam um componente unico centrado
    # na vertical (aprovado pelo Gabriel em 26/08, video cida-inss). Janelas
    # alinhadas a fronteiras de bloco: desfoque, cartao e reposicionamento da
    # legenda acontecem no MESMO frame. Cartoes vizinhos dividem um desfoque so
    # e trocam por corte seco.
    footer_anchor_pct = None
    cc = (prof.get("graphics_overlays") or {}).get("center_card") or {}
    center_ovs = sorted((o for o in overlays if o.get("_center_card")),
                        key=lambda o: o["start"])
    for o in overlays:
        o.pop("_center_card", None)
    if center_ovs:
        groups = [[center_ovs[0]]]
        for o in center_ovs[1:]:
            if o["start"] - groups[-1][-1]["end"] < 0.6:
                groups[-1].append(o)
            else:
                groups.append([o])

        lh = prof["captions"]["typography"]["line_height_ratio"]
        pwins = (push_plan or {}).get("windows") or []
        sigma = float(cc.get("blur_sigma", 26.0))
        for grp in groups:
            g_end = grp[-1]["end"]
            # fim do grupo: emenda na descida da proxima janela de push, se
            # houver uma logo em seguida; senao, na fronteira do ultimo bloco
            nxt = min((w["down_start"] for w in pwins
                       if g_end - 0.6 <= w["down_start"] <= g_end + 1.5),
                      default=None)
            if nxt is None:
                covered = [b for b in blocks if b["start"] < g_end + 0.05]
                nxt = covered[-1]["end"] if covered else g_end
            guess = grp[0]["start"]
            card_blocks = [b for b in blocks
                           if b["end"] > guess + 0.05 and b["end"] <= nxt + 0.1]
            if card_blocks:
                grp[0]["start"] = card_blocks[0]["start"]
            for a, b in zip(grp, grp[1:]):   # trocas internas em fronteira de bloco
                swap = min((blk["start"] for blk in card_blocks),
                           key=lambda x: abs(x - b["start"]), default=b["start"])
                if abs(swap - b["start"]) <= 0.6:
                    b["start"] = swap
                a["end"] = b["start"]
            grp[-1]["end"] = round(nxt, 4)
            for ta, tb in ((t["start"], t["end"]) for t in transitions):
                if grp[0]["start"] < tb and ta < grp[-1]["end"]:
                    print("[plan] AVISO: transicao %.2f-%.2f dentro do cartao "
                          "central -- confira no rascunho" % (ta, tb))

            # componente imagem+legenda centrado na vertical
            img_h = int(round(float(cc.get("img_height_pct", 0.578)) * H))
            gap = int(round(float(cc.get("gap_px_at_1920", 34)) * H / 1920.0))
            top_min = int(round(float(cc.get("top_min_px_at_1920", 60)) * H / 1920.0))
            cap_h = 0
            if card_blocks:
                fs_max = max(b["font_size_px"] for b in card_blocks)
                cap_h = int(round(2 * fs_max * lh)) + gap
            top = max(top_min, (H - (img_h + cap_h)) // 2)
            if card_blocks:
                footer_anchor_pct = round((top + img_h + gap) / float(H), 4)
                for b in card_blocks:
                    b["anchor"] = "footer"

            for o in grp:
                try:
                    from PIL import Image
                    iw3, ih3 = Image.open(o["params"]["path"]).size
                except Exception:
                    iw3, ih3 = 3, 4
                w_disp = int(round(img_h * iw3 / float(ih3)))
                w_cap = int(prof["graphics_overlays"]["safe_margins"]["max_width_pct"] * W)
                w_disp = min(w_disp, w_cap) // 2 * 2
                o["params"]["mode"] = "center_card"
                o["params"]["pos"] = {"x_pct": round((1 - w_disp / float(W)) / 2, 4),
                                      "y_pct": round(top / float(H), 4),
                                      "w_pct": round(w_disp / float(W), 4)}
                o["params"]["mask"] = "rounded_rect"
                o["params"]["corner_radius_pct"] = float(cc.get("corner_radius_pct", 0.03))
                o["params"]["entry_ms"] = 0     # corte seco, estilo jump cut:
                o["params"]["exit_ms"] = 0      # fade num cartao cheio vira fantasma
                o["duration"] = round(o["end"] - o["start"], 4)

            blurs.append({
                "id": "BLR_CARD%d" % (len(blurs) + 1), "type": "gaussian",
                "start": grp[0]["start"], "end": grp[-1]["end"],
                "duration": round(grp[-1]["end"] - grp[0]["start"], 4),
                "params": {"sigma": sigma, "region": "full_frame"},
                "evidence": "video desfocado atras do cartao central (%s)"
                            % ", ".join(o["id"] for o in grp),
                "confidence": 80, "origin": "inferred"})

    # legenda nunca sob uma insercao no topo
    for blk in blocks:
        if blk["anchor"] != "upper":
            continue
        if any(blk["start"] < o["end"] and o["start"] < blk["end"] for o in overlays
               if (o.get("params") or {}).get("mode") != "push_down"):
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
        "cuts": cuts, "transitions": transitions, "moves": [], "blurs": blurs,
        "captions": {
            "enabled": bool(blocks), "source": "faster_whisper", "language": "pt",
            "font_primary": "Helvetica Neue", "font_accent": "Playfair Display",
            "font_size_px": fs_base,
            "accent_size_ratio": cap["typography"]["accent_size_ratio"],
            "line_height_ratio": cap["typography"]["line_height_ratio"],
            "side_margin_pct": cap["layout"]["side_margin_pct"],
            "tracking_px": cap["typography"]["tracking_px_at_reference"] * (W / 720.0),
            "anchors": {"lower_default": anchor_pct,
                        "footer": (footer_anchor_pct if footer_anchor_pct is not None
                                   else cap["layout"]["anchors"]["footer"]["bbox_top_pct"]),
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
                    "duration": (min(op.get("duration_ms", 700) / 1000.0,
                                     segs[0]["duration"] * 0.6)
                                 if op.get("integrated_into_first_segment")
                                 else prof["opening"]["duration_ms"] / 1000.0),
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

    if push_plan:
        plan["push_down"] = push_plan

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
    pats = [sg for sg in segs if sg["zoom"]["preset_id"].startswith(("punch", "creep"))]
    if pats:
        print("padroes de zoom  : %d" % len(pats))
        for sg in pats:
            zz = sg["zoom"]
            print("   %-6s %-17s %.3f -> %.3f em %.2fs  (seg %.2fs, out %.2f)"
                  % (sg["id"], zz["preset_id"], zz["scale_from"], zz["scale_to"],
                     zz["duration"], sg["duration"], sg["out_start"]))
    print("insercoes        : %d (%.1f/min)" % (len(overlays), len(overlays) / mins))
    for o in overlays:
        pa = o["params"]
        modo = pa.get("mode", "top_band")
        if modo == "center_card":
            geom = "%dpx de largura + legenda em %.3f" % (
                int(round(pa["pos"]["w_pct"] * W)), footer_anchor_pct or 0)
        elif pa.get("box"):
            geom = "caixa %dx%d" % (pa["box"]["w_px"], pa["box"]["h_px"])
        else:
            geom = "%dpx de largura" % int(round(pa["pos"]["w_pct"] * W))
        print("   %-5s %-12s out %6.2f-%6.2f  %s  entry %dms exit %dms"
              % (o["id"], modo, o["start"], o["end"], geom,
                 pa.get("entry_ms", 0), pa.get("exit_ms", 0)))
    for bl in blurs:
        if str(bl.get("id", "")).startswith("BLR_CARD"):
            print("   desfoque de fundo %.2f-%.2f (sigma %.0f)"
                  % (bl["start"], bl["end"], bl["params"]["sigma"]))
    if push_plan:
        print("push-down        : desce %dpx, rampa %.2fs, %d janela(s)"
              % (push_plan["dist_px"], push_plan["ramp_s"], len(push_plan["windows"])))
        for w in push_plan["windows"]:
            print("   video baixo em %.2f -> %.2f s" % (w["down_start"], w["up_end"]))

    print("plano            : %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
