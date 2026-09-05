#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - brand_logos.py  (v3.1)

Animacao de logo de marca "estilo motion design" quando a fala cita uma empresa
(Claude/Anthropic, OpenAI, Google, Meta, Microsoft, DeepSeek...). Aprovado pelo
Gabriel em 01/09 no video do Fable 5.1:

  - o logotipo OFICIAL (registro em references/brand-logos.json, asset real baixado
    da fonte oficial e guardado em assets/logos/) aparece NO PEITO da pessoa;
  - entra SUBINDO de baixo com ease-out e leve overshoot (0,66 s), acende com
    bloom + halo + nucleo quente na cor da marca, segura ~1 s com o brilho
    respirando, e SAI para cima acelerando enquanto apaga (0,54 s);
  - fica logo abaixo da faixa de legenda (nunca cruza o texto) e acima da
    reserva de UI do Reels; e composto DEPOIS do render, em espaco de tela.

Subcomandos:
  plan    le words.json + edit-plan.json, acha as mencoes, mapeia para a timeline
          de saida, foge de janelas de push-down/cartao e grava brand-logos.json
  render  gera a sequencia RGBA e compoe sobre o render (.partial.mp4 -> .partial.mp4)
  fetch   baixa/rasteriza o logo de uma marca para assets/logos/ (util para testar)

Uso tipico (depois do render_edit.py):
  python3 brand_logos.py plan   --work "$WORK" --plan "$WORK/edit-plan.json"
  python3 brand_logos.py render --events "$WORK/brand-logos.json" \
          --in "<render>.partial.mp4" --out "<destino>.partial.mp4"
"""

import argparse
import colorsys
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
REGISTRY = os.path.join(SKILL_ROOT, "references", "brand-logos.json")
LOGO_DIR = os.path.join(SKILL_ROOT, "assets", "logos")
RASTER_PX = 2048
UA = "Mozilla/5.0 (Macintosh) EditCleanSkill/2.7"

# --- animacao (valores aprovados 01/09, video do Fable 5.1) --------------------
LEAD_AFTER_WORD = 0.32     # entra 0,32 s depois de a palavra acender
RISE_S = 0.66              # subida
HOLD_S = 1.00              # sustentacao
EXIT_S = 0.54              # saida
RISE_PX_AT_1920 = 250      # de quanto abaixo ele sobe
EXIT_PX_AT_1920 = 150      # quanto sobe ao sair
SIZE_W_FRAC = 0.23         # largura maxima do mark quadrado (248 px em 1080; v3.1: era 0.267/288 px, "diminua os logos")
CAPTION_GAP_PCT = 0.030    # folga entre o fim da faixa da legenda e o topo do logo (58 px em 1920; v3.1: era 0.004, "logo muito perto do texto")
WIDE_W_FRAC = 0.60         # largura maxima para logotipo largo (wordmark)
UI_RESERVE_PCT = 0.115     # reserva de UI do Reels (mesma do push-down)
CAPTION_HALO_PCT = 0.012   # halo difuso abaixo da ultima linha
MIN_GAP_S = 9.5            # espaco minimo entre duas animacoes (v3.1: era 10,0; o 2o par OpenAI+Cursor perdia por 0,04 s)

# --- flutuacao (v2.8, pedido 01/09: "como se tivesse flutuando, margem curta") -----
FLOAT_Y_PCT = 0.0045       # amplitude vertical, fracao da altura (8,6 px em 1920)
FLOAT_Y_PERIOD_S = 2.2
FLOAT_X_PCT = 0.0020       # deriva horizontal, fracao da largura (2 px em 1080)
FLOAT_X_PERIOD_S = 3.1

# --- glow (v2.8: 15% mais fraco que a v2.7 e alcance ~20% maior) ---------------------
GLOW = {"bloom_sigma": 74, "bloom_alpha": 0.49,     # v3.1 (03/09, "diminua um pouco o glow"): eram 0.61
        "halo_sigma": 22, "halo_alpha": 0.58,       # / 0.72
        "hot_alpha": 0.55}                          # / 0.68. Por marca: "glow" no registro (openai 0.7)

# --- par de logos (v3.1, pedido 03/09: "OpenAI ... Cursor" um do lado do outro) ---------
PAIR_WINDOW_S = 2.6        # 2a marca citada ate 2,6 s depois da 1a vira par (entra quando a palavra dela acende)
PAIR_GAP_FRAC = 0.055      # espaco entre os dois marks, fracao da largura (59 px em 1080)
PAIR_MAX_W_FRAC = 0.90     # o conjunto inteiro (mark + gap + mark) cabe em 90% da largura, centrado


def _find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    for cand in (os.path.expanduser("~/.local/tools/%s" % name),
                 "/opt/homebrew/bin/%s" % name, "/usr/local/bin/%s" % name):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


FFMPEG = _find_bin("ffmpeg")
CHROME_CANDIDATES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                     "/Applications/Chromium.app/Contents/MacOS/Chromium",
                     shutil.which("google-chrome") or "", shutil.which("chromium") or ""]


def log(msg):
    sys.stderr.write("[logo] %s\n" % msg)


def load_registry():
    return json.load(open(REGISTRY, encoding="utf-8"))


# =============================================================================
# 1. asset: baixar + rasterizar o logotipo oficial
# =============================================================================
def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as fh:
        fh.write(r.read())


def _strip_svg_fills(svg_text, fills):
    """Remove elementos cujo fill e o fundo (rect/path de cor chapada)."""
    for f in fills:
        svg_text = re.sub(r"<(path|rect|circle)\b[^>]*fill=[\"']%s[\"'][^>]*/?>(?:</\1>)?" % re.escape(f),
                          "", svg_text, flags=re.I)
    return svg_text


def _svg_size(svg_text):
    m = re.search(r"viewBox=[\"']\s*([\d.\-]+)[ ,]+([\d.\-]+)[ ,]+([\d.\-]+)[ ,]+([\d.\-]+)", svg_text)
    if m:
        w, h = float(m.group(3)), float(m.group(4))
        if w > 0 and h > 0:
            return w, h
    mw = re.search(r"<svg[^>]*\swidth=[\"']([\d.]+)", svg_text)
    mh = re.search(r"<svg[^>]*\sheight=[\"']([\d.]+)", svg_text)
    if mw and mh:
        return float(mw.group(1)), float(mh.group(1))
    return 1.0, 1.0


def _rasterize_svg(svg_text, dest_png):
    w0, h0 = _svg_size(svg_text)
    if w0 >= h0:
        W, H = RASTER_PX, max(8, int(round(RASTER_PX * h0 / w0)))
    else:
        W, H = max(8, int(round(RASTER_PX * w0 / h0))), RASTER_PX
    # rsvg-convert e o mais limpo quando existe; senao Chrome headless (memoria:
    # no Mac e o unico que rasteriza direito; rodar em background e matar depois)
    rsvg = shutil.which("rsvg-convert")
    tmpd = tempfile.mkdtemp(prefix="editclean-svg-")
    svg_path = os.path.join(tmpd, "logo.svg")
    open(svg_path, "w", encoding="utf-8").write(svg_text)
    try:
        if rsvg:
            subprocess.run([rsvg, "-w", str(W), "-h", str(H), "-b", "transparent", "-o", dest_png, svg_path],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return
        chrome = next((c for c in CHROME_CANDIDATES if c and os.path.isfile(c)), None)
        if not chrome:
            raise SystemExit("sem rasterizador de SVG (instale rsvg-convert ou Google Chrome)")
        html = os.path.join(tmpd, "page.html")
        open(html, "w", encoding="utf-8").write(
            "<style>html,body{margin:0;padding:0;background:transparent;width:%dpx;height:%dpx;overflow:hidden}"
            "svg{display:block;width:%dpx;height:%dpx}</style>%s" % (W, H, W, H, svg_text))
        proc = subprocess.Popen([chrome, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                                 "--default-background-color=00000000", "--window-size=%d,%d" % (W, H),
                                 "--screenshot=%s" % dest_png, "file://%s" % html],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            if os.path.isfile(dest_png) and os.path.getsize(dest_png) > 0:
                break
            time.sleep(0.5)
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        if not (os.path.isfile(dest_png) and os.path.getsize(dest_png) > 0):
            raise SystemExit("Chrome nao gerou o PNG do SVG")
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def _finish_alpha(png_path, alpha_from_luma=False):
    """Garante RGBA, recorta a folga e (opcional) tira o alfa da luminancia
    (icone branco sobre fundo escuro chapado)."""
    from PIL import Image
    im = Image.open(png_path).convert("RGBA")
    if alpha_from_luma:
        lum = im.convert("L")
        im.putalpha(lum)
    a = im.split()[3]
    bbox = a.getbbox()
    if bbox:
        im = im.crop(bbox)
    im.save(png_path)
    return im.size


def fetch_logo(brand_key, force=False):
    """Devolve o caminho do PNG 2048px do logotipo oficial (baixa se preciso)."""
    reg = load_registry()["brands"]
    if brand_key not in reg:
        raise SystemExit("marca desconhecida: %s" % brand_key)
    b = reg[brand_key]
    os.makedirs(LOGO_DIR, exist_ok=True)
    dest = os.path.join(LOGO_DIR, "%s.png" % brand_key)
    meta = os.path.join(LOGO_DIR, "%s.json" % brand_key)
    if os.path.isfile(dest) and not force:
        return dest
    if not b.get("sources"):
        return None
    last_err = None
    for src in b["sources"]:
        try:
            tmpd = tempfile.mkdtemp(prefix="editclean-logo-")
            raw = os.path.join(tmpd, "raw")
            _download(src["url"], raw)
            kind = src.get("kind", "png")
            if kind == "svg":
                txt = open(raw, "rb").read().decode("utf-8", "replace")
                if "<svg" not in txt:
                    raise RuntimeError("a resposta nao e SVG (bloqueio do site?)")
                if src.get("remove_fill"):
                    txt = _strip_svg_fills(txt, src["remove_fill"])
                _rasterize_svg(txt, dest)
            else:
                from PIL import Image
                im = Image.open(raw)
                if kind == "ico":
                    im.size  # forca a leitura do maior frame
                    try:
                        im = im.resize(max(im.info.get("sizes", {(im.width, im.height)}), key=lambda s: s[0]) and im.size)
                    except Exception:
                        pass
                im = im.convert("RGBA")
                scale = RASTER_PX / float(max(im.size))
                if scale > 1:
                    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
                im.save(dest)
            size = _finish_alpha(dest, src.get("alpha_from_luma", False))
            json.dump({"brand": brand_key, "source_url": src["url"], "kind": kind,
                       "fetched_at": time.strftime("%Y-%m-%d %H:%M"), "size": size,
                       "note": "logotipo oficial; uso editorial no video, nao e material da skill"},
                      open(meta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            shutil.rmtree(tmpd, ignore_errors=True)
            log("%s: %s -> %s (%dx%d)" % (brand_key, src["url"], dest, size[0], size[1]))
            return dest
        except Exception as exc:
            last_err = exc
            log("%s: fonte falhou (%s): %s" % (brand_key, src.get("url"), exc))
    log("%s: NENHUMA fonte funcionou (%s) -> sem animacao para essa marca" % (brand_key, last_err))
    return None


# =============================================================================
# 2. plan: achar as mencoes e montar os eventos
# =============================================================================
def _norm(t):
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", t)


def find_mentions(words, registry):
    """[(brand_key, idx_primeiro_token, idx_ultimo_token)] em ordem de tempo."""
    toks = [_norm(w["text"]) for w in words]
    found = []
    for key, b in registry["brands"].items():
        for alias in b.get("aliases", []):
            seq = [_norm(a) for a in alias.split()]
            n = len(seq)
            for i in range(len(toks) - n + 1):
                if toks[i:i + n] == seq:
                    found.append((words[i]["start"], key, i, i + n - 1))
    found.sort()
    return [(k, i, j) for _, k, i, j in found]


def src_to_out(plan, t):
    """Mapeia tempo da fonte para a timeline de saida; None se caiu em trecho removido."""
    for s in plan["segments"]:
        if s["src_start"] - 1e-6 <= t <= s["src_end"] + 1e-6:
            return round(s["out_start"] + (t - s["src_start"]), 4)
    return None


def busy_windows(plan):
    """Janelas em que o quadro nao e o plano normal: push-down (video desce),
    cartao central (desfoque) e a abertura."""
    win = []
    pd = plan.get("push_down") or {}
    for w in pd.get("windows", []) if isinstance(pd, dict) else []:
        a = w.get("down_start", w.get("start"))
        b = w.get("up_end", w.get("end"))
        if a is not None and b is not None:
            win.append((float(a), float(b), "push_down"))
    for ov in plan.get("overlays", []) or []:
        prm = ov.get("params") or {}
        if "center_card" in (ov.get("mode"), ov.get("placement"), prm.get("mode"), prm.get("placement")):
            win.append((float(ov["start"]), float(ov["end"]), "center_card"))
    for bl in plan.get("blurs", []) or []:
        win.append((float(bl["start"]), float(bl["end"]), "blur"))
    op = plan.get("opening") or {}
    if op.get("enabled"):
        win.append((0.0, float(op.get("duration", 0.7)) * 0.6, "opening"))
    return win


def caption_band_bottom(plan):
    caps = plan.get("captions") or {}
    H = float(plan["output"]["height"])
    anchor = float((caps.get("anchors") or {}).get("lower_default", 0.552))
    lh = float(caps.get("line_height_ratio", 1.205))
    tallest = 0.0
    for b in caps.get("blocks", []) or []:
        fs = float(b.get("font_size_px") or caps.get("font_size_px") or H * 0.06)
        lines = int(b.get("lines", 1) or 1)
        tallest = max(tallest, lines * fs * lh)
    if tallest == 0:
        tallest = 2 * float(caps.get("font_size_px") or H * 0.06) * lh
    return anchor + tallest / H + CAPTION_HALO_PCT


def _tile_geometry(asset, W, H, band_top, band_bottom):
    """Largura/altura/centro-y de um mark na faixa abaixo da legenda (regra da v2.7)."""
    from PIL import Image
    lw, lh = Image.open(asset).size
    aspect = lw / float(lh)
    band_h = (band_bottom - band_top) * H
    if aspect <= 1.6:                       # mark quadrado/compacto
        width = min(SIZE_W_FRAC * W, band_h * aspect + 8)
        height = width / aspect
        cy = band_top * H + height / 2.0
    else:                                   # wordmark largo
        width = min(WIDE_W_FRAC * W, band_h * aspect)
        height = width / aspect
        cy = band_top * H + band_h / 2.0
    return width, height, cy, aspect


def plan_events(work, plan_path, out_path, min_gap, only_first, brands_filter):
    plan = json.load(open(plan_path, encoding="utf-8"))
    words = json.load(open(os.path.join(work, "words.json"), encoding="utf-8"))["words"]
    registry = load_registry()
    W, H = float(plan["output"]["width"]), float(plan["output"]["height"])
    dur_out = plan["segments"][-1]["out_start"] + plan["segments"][-1]["duration"]
    band_top = caption_band_bottom(plan) + CAPTION_GAP_PCT
    band_bottom = 1.0 - UI_RESERVE_PCT
    windows = busy_windows(plan)

    # candidatos em ordem de tempo (so os que sobreviveram ao corte)
    cands = []
    for key, i, j in find_mentions(words, registry):
        if brands_filter and key not in brands_filter:
            continue
        t_src = float(words[i]["start"])
        t_word = src_to_out(plan, t_src)
        label = "%s (%s @src %.2fs)" % (key, " ".join(x["text"] for x in words[i:j + 1]), t_src)
        if t_word is None:
            log("pula %s: trecho removido" % label)
            continue
        cands.append({"key": key, "i": i, "j": j, "t_src": t_src, "t_word": t_word, "label": label,
                      "mention": " ".join(x["text"] for x in words[i:j + 1])})

    events, skipped, last_end, seen = [], [], -1e9, set()
    n = 0
    while n < len(cands):
        c = cands[n]
        key = c["key"]
        if only_first and key in seen:
            n += 1
            continue
        # par: a proxima mencao e de OUTRA marca e cai ate PAIR_WINDOW_S depois
        mates = [c]
        if n + 1 < len(cands):
            c2 = cands[n + 1]
            if c2["key"] != key and 0.0 <= c2["t_word"] - c["t_word"] <= PAIR_WINDOW_S \
                    and not (only_first and c2["key"] in seen):
                mates.append(c2)
        # v3.2: o par ocupa a tela ~1,1 s a mais que um logo so (a 2a marca sobe depois).
        # Quando o par nao cabe -- fim do video, espacamento, ou janela de insercao --
        # tentar a 1a marca SOZINHA antes de passar a vez. Antes so a 2a era tentada,
        # e a abertura "A Anthropic lancou o Fable 5.1" ficava sem nenhum logo porque o
        # rabo do par entrava 0,85 s dentro do push-down da insercao seguinte.
        attempts = [mates] if len(mates) == 1 else [mates, mates[:1]]
        chosen = None
        for att in attempts:
            a_in = c["t_word"] + LEAD_AFTER_WORD
            a_out = att[-1]["t_word"] + LEAD_AFTER_WORD + RISE_S + HOLD_S
            a_end = a_out + EXIT_S
            a_label = " + ".join(m["label"] for m in att)
            if a_end > dur_out - 0.05:
                why = "sem tempo antes do fim do video"
            elif a_in - last_end < min_gap:
                why = "menos de %.0fs da animacao anterior" % min_gap
            else:
                clash = [k for (a, b, k) in windows if a < a_end and b > a_in]
                why = ("coincide com %s" % ",".join(sorted(set(clash)))) if clash else None
            if why is None:
                chosen = (att, a_in, a_out, a_end, a_label)
                break
            skipped.append({"brand": key, "why": why, "out": a_in})
            log("pula %s: %s" % (a_label, why))
        if chosen is None:
            n += 1                      # a 2a marca do par tenta sozinha
            continue
        mates, t_in, t_out, t_end, label = chosen
        assets = [fetch_logo(m["key"]) for m in mates]
        if not assets[0]:
            skipped.append({"brand": key, "why": "sem logotipo oficial no registro", "out": t_in})
            n += 1
            continue
        if len(mates) == 2 and not assets[1]:
            mates, assets = mates[:1], assets[:1]     # a 2a marca nao tem asset: segue sozinha
            t_out = t_in + RISE_S + HOLD_S
            t_end = t_out + EXIT_S

        geos = [_tile_geometry(a, W, H, band_top, band_bottom) for a in assets]
        if len(mates) == 2:
            gap = PAIR_GAP_FRAC * W
            total = geos[0][0] + gap + geos[1][0]
            s = min(1.0, PAIR_MAX_W_FRAC * W / total)
            ws = [g[0] * s for g in geos]
            hs = [g[1] * s for g in geos]
            total = ws[0] + gap + ws[1]
            x_left = (W - total) / 2.0
            cxs = [(x_left + ws[0] / 2.0) / W, (x_left + ws[0] + gap + ws[1] / 2.0) / W]
            cy = band_top * H + max(hs) / 2.0
        else:
            ws, cxs, cy = [geos[0][0]], [0.5], geos[0][2]

        tiles = []
        for m, a, g, w_px, cx in zip(mates, assets, geos, ws, cxs):
            b = registry["brands"][m["key"]]
            tiles.append({"brand": m["key"], "name": b.get("name", m["key"]), "mention": m["mention"],
                          "token_index": m["i"], "src_time": m["t_src"], "word_out": m["t_word"],
                          "t_in": round(m["t_word"] + LEAD_AFTER_WORD, 3),
                          "t_settle": round(m["t_word"] + LEAD_AFTER_WORD + RISE_S, 3),
                          "asset": a, "color": b.get("color", "#D97757"), "palette": b.get("palette"),
                          "glow": float(b.get("glow", 1.0)),
                          "cx": round(cx, 4), "width_px": int(round(w_px)), "aspect": round(g[3], 3)})
        first = tiles[0]
        ev = {"id": "BL%d" % (len(events) + 1), "brand": first["brand"], "name": first["name"],
              "mention": " + ".join(t["mention"] for t in tiles), "token_index": first["token_index"],
              "src_time": first["src_time"], "word_out": first["word_out"],
              "t_in": first["t_in"], "t_settle": first["t_settle"],
              "t_out": round(t_out, 3), "t_end": round(t_end, 3),
              "asset": first["asset"], "color": first["color"], "palette": first["palette"],
              "glow": first["glow"],
              "cx": first["cx"], "cy": round(cy / H, 4), "width_px": first["width_px"], "aspect": first["aspect"],
              "rise_px": int(round(RISE_PX_AT_1920 * H / 1920.0)),
              "exit_px": int(round(EXIT_PX_AT_1920 * H / 1920.0)),
              "pair": len(tiles) == 2, "tiles": tiles}
        events.append(ev)
        for t in tiles:
            seen.add(t["brand"])
        last_end = t_end
        log("%s -> out %.2f-%.2f  cy %.3f  largura %s%s" % (
            label, t_in, t_end, ev["cy"], "/".join(str(t["width_px"]) for t in tiles) + "px",
            "  [PAR lado a lado, centrado]" if ev["pair"] else ""))
        n += len(mates)

    doc = {"version": "3.1", "canvas": {"w": int(W), "h": int(H), "fps": float(plan["output"]["fps"])},
           "band": {"top": round(band_top, 4), "bottom": round(band_bottom, 4)},
           "events": events, "skipped": skipped}
    json.dump(doc, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("%d evento(s), %d pulado(s) -> %s" % (len(events), len(skipped), out_path))
    print(out_path)
    return doc


# =============================================================================
# 3. render: sequencia RGBA + composicao
# =============================================================================
def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def palette(color_hex):
    """bloom, halo, nucleo, brilho -- derivados da cor-base da marca. Uma marca pode
    trazer 'palette' explicita no registro (o Claude usa os valores aprovados na v1)."""
    r, g, b = [x / 255.0 for x in _hex(color_hex)]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)

    def hsv(hh, ss, vv):
        return tuple(int(round(x * 255)) for x in colorsys.hsv_to_rgb(hh % 1.0, max(0, min(1, ss)), max(0, min(1, vv))))
    if s < 0.12:                                 # marca branca/cinza: neon frio
        return {"bloom": (150, 185, 255), "halo": (205, 222, 255), "core": (236, 240, 250), "hot": (255, 255, 255)}
    return {"bloom": hsv(h, min(1.0, s * 1.25), 1.0),
            "halo": hsv(h, s * 0.85, 1.0),
            "core": hsv(h, s * 0.55, min(1.0, v * 0.55 + 0.45)),
            "hot": hsv(h, s * 0.18, 1.0)}


def ease_out_back(p, s=1.28):
    p -= 1.0
    return p * p * ((s + 1) * p + s) + 1.0


def ease_in_cubic(p):
    return p ** 3


def smoothstep(p):
    return p * p * (3 - 2 * p)


def clamp01(x):
    return max(0.0, min(1.0, x))


def render_logo_tile(logo_alpha, width_px, glow_boost, pal):
    """Monta o logo aceso (bloom + halo + mark + nucleo quente) num tile RGBA."""
    import numpy as np
    from PIL import Image, ImageFilter
    lw, lh = logo_alpha.size
    height_px = max(4, int(round(width_px * lh / float(lw))))
    unit = max(width_px, height_px) / 340.0
    pad = int(max(width_px, height_px) * 0.55)     # folga para o bloom mais aberto da v2.8
    tw, th = width_px + 2 * pad, height_px + 2 * pad
    a = logo_alpha.resize((width_px, height_px), Image.LANCZOS)
    base = Image.new("L", (tw, th), 0)
    base.paste(a, (pad, pad))
    A = np.asarray(base).astype(np.float32) / 255.0

    def blurred(radius):
        return np.asarray(base.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32) / 255.0

    bloom = blurred(GLOW["bloom_sigma"] * unit)
    halo = blurred(GLOW["halo_sigma"] * unit)
    dens = blurred(0.155 * max(width_px, height_px))
    dens = dens / max(1e-6, float(dens.max()))
    out = np.zeros((th, tw, 4), np.float32)

    def over(color, alpha):
        c = np.asarray(color, np.float32) / 255.0
        al = np.clip(alpha, 0.0, 1.0)[..., None]
        out[..., :3] = c * al + out[..., :3] * (1 - al)
        out[..., 3:] = al + out[..., 3:] * (1 - al)

    over(pal["bloom"], np.clip(bloom * 2.6, 0, 1) * GLOW["bloom_alpha"] * glow_boost)
    over(pal["halo"], np.clip(halo * 1.9, 0, 1) * GLOW["halo_alpha"] * glow_boost)
    over(pal["core"], A)
    over(pal["hot"], A * np.clip(dens ** 1.35 * 1.15, 0, 1) * GLOW["hot_alpha"] * glow_boost)
    return Image.fromarray(np.clip(out * 255.0, 0, 255).astype(np.uint8), "RGBA")


def _anim_state(t, t_in, t_settle, t_out, t_end, rise_px, exit_px):
    """(dy, scale, alpha, glow) de um mark no instante t; None fora da janela."""
    if t < t_in or t >= t_end:
        return None
    if t < t_settle:
        p = clamp01((t - t_in) / max(1e-6, t_settle - t_in))
        k = ease_out_back(p)
        return (rise_px * (1.0 - k), 0.80 + 0.20 * k,
                smoothstep(clamp01((t - t_in) / 0.30)), 1.0 + 0.55 * (1.0 - p) ** 2)
    if t < t_out:
        p = (t - t_settle) / max(1e-6, (t_out - t_settle))
        return (0.0, 1.0, 1.0, 1.0 + 0.14 * math.sin(math.pi * p))
    p = clamp01((t - t_out) / max(1e-6, t_end - t_out))
    k = ease_in_cubic(p)
    return (-exit_px * k, 1.0 + 0.07 * k, 1.0 - smoothstep(clamp01((p - 0.08) / 0.92)), 1.0 + 0.30 * k)


def _event_tiles(e):
    """v3.1: evento traz 'tiles' (1 ou 2 marks). Documento antigo (v2.7) vira um tile."""
    if e.get("tiles"):
        return e["tiles"]
    return [{"asset": e["asset"], "color": e["color"], "palette": e.get("palette"), "glow": e.get("glow", 1.0),
             "cx": e["cx"], "width_px": e["width_px"], "t_in": e["t_in"], "t_settle": e["t_settle"]}]


def render_sequence(doc, seq_dir):
    from PIL import Image
    W, H, fps = doc["canvas"]["w"], doc["canvas"]["h"], doc["canvas"]["fps"]
    events = doc["events"]
    if not events:
        return 0
    os.makedirs(seq_dir, exist_ok=True)
    seq_end = max(e["t_end"] for e in events) + 0.05
    n = int(math.ceil(seq_end * fps))
    logos = {}
    for e in events:
        for tl in _event_tiles(e):
            if tl["asset"] not in logos:
                logos[tl["asset"]] = Image.open(tl["asset"]).convert("RGBA").split()[3]
    cache = {}
    for i in range(n):
        t = i / fps
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for e in events:
            if not (e["t_in"] <= t < e["t_end"]):
                continue
            # flutuacao do CONJUNTO: mesma fase para os dois marks de um par
            tf = t - e["t_in"]
            fy = FLOAT_Y_PCT * H * math.sin(2 * math.pi * tf / FLOAT_Y_PERIOD_S)
            fx = FLOAT_X_PCT * W * math.sin(2 * math.pi * tf / FLOAT_X_PERIOD_S + 1.1)
            for tl in _event_tiles(e):
                st = _anim_state(t, tl["t_in"], tl["t_settle"], e["t_out"], e["t_end"], e["rise_px"], e["exit_px"])
                if st is None:
                    continue
                dy, scale, alpha, glow = st
                if alpha <= 0.002:
                    continue
                fgain = smoothstep(clamp01((t - tl["t_in"]) / max(1e-6, tl["t_settle"] - tl["t_in"])))
                dy += fgain * fy
                dx = fgain * fx
                gmul = float(tl.get("glow", 1.0))
                width = max(8, int(round(tl["width_px"] * scale)))
                key = (tl["asset"], width, round(glow * gmul, 2), tl["color"], json.dumps(tl.get("palette")))
                if key not in cache:
                    if len(cache) > 60:
                        cache.clear()
                    pal = ({k: tuple(v) for k, v in tl["palette"].items()} if tl.get("palette") else palette(tl["color"]))
                    cache[key] = render_logo_tile(logos[tl["asset"]], width, glow * gmul, pal)
                tile = cache[key]
                if alpha < 0.999:
                    tile = tile.copy()
                    tile.putalpha(tile.split()[3].point(lambda v, k=alpha: int(v * k)))
                x = int(round(tl["cx"] * W + dx - tile.width / 2.0))
                y = int(round(e["cy"] * H + dy - tile.height / 2.0))
                frame.alpha_composite(tile, (x, y))
        frame.save(os.path.join(seq_dir, "%05d.png" % (i + 1)))
    return n


def compose(video_in, seq_dir, video_out, fps, crf=18, duration=None):
    """Sobrepoe a sequencia (comeca em t=0, transparente fora dos eventos) com
    eof_action=pass; o audio e copiado. -t casa a duracao com o video (o AAC do
    render sai ~67 ms mais longo e isso derruba o validate_output)."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", video_in,
           "-framerate", "%g" % fps, "-start_number", "1", "-i", os.path.join(seq_dir, "%05d.png"),
           "-filter_complex",
           "[0:v]format=rgba[base];[1:v]format=rgba[ov];[base][ov]overlay=0:0:eof_action=pass:format=auto,format=yuv420p[v]",
           "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-crf", str(crf), "-preset", "slow", "-profile:v", "high",
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
           "-c:a", "copy"]
    if duration:
        cmd += ["-t", "%.3f" % duration]
    cmd += ["-movflags", "+faststart", video_out]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise SystemExit("ffmpeg (compose) falhou: %s" % p.stderr.decode("utf-8", "replace")[-500:])


def _video_frames_duration(path):
    rc = subprocess.run([_find_bin("ffprobe"), "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=nb_frames,r_frame_rate", "-of", "json", path],
                        stdout=subprocess.PIPE)
    d = json.loads(rc.stdout.decode())["streams"][0]
    num, den = d["r_frame_rate"].split("/")
    return int(d["nb_frames"]) / (float(num) / float(den))


def main():
    ap = argparse.ArgumentParser(description="Animacao de logo de marca (EditClean v2.7)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("plan")
    p1.add_argument("--work", required=True)
    p1.add_argument("--plan", required=True)
    p1.add_argument("--out", default=None)
    p1.add_argument("--min-gap", type=float, default=MIN_GAP_S)
    p1.add_argument("--only-first", action="store_true", help="so a primeira mencao de cada marca")
    p1.add_argument("--brands", default=None, help="lista separada por virgula para limitar")
    p2 = sub.add_parser("render")
    p2.add_argument("--events", required=True)
    p2.add_argument("--in", dest="video_in", required=True)
    p2.add_argument("--out", required=True)
    p2.add_argument("--crf", type=int, default=18)
    p2.add_argument("--workdir", default=None)
    p3 = sub.add_parser("fetch")
    p3.add_argument("brand")
    p3.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.cmd == "fetch":
        print(fetch_logo(args.brand, force=args.force))
        return
    if args.cmd == "plan":
        out = args.out or os.path.join(args.work, "brand-logos.json")
        plan_events(args.work, args.plan, out, args.min_gap, args.only_first,
                    set(args.brands.split(",")) if args.brands else None)
        return
    if args.cmd == "render":
        doc = json.load(open(args.events, encoding="utf-8"))
        if not doc["events"]:
            log("nenhum evento; copiando o video sem alteracao")
            shutil.copyfile(args.video_in, args.out)
            return
        seq = args.workdir or tempfile.mkdtemp(prefix="editclean-logoseq-")
        n = render_sequence(doc, seq)
        log("%d frame(s) de sequencia em %s" % (n, seq))
        dur = _video_frames_duration(args.video_in)
        compose(args.video_in, seq, args.out, doc["canvas"]["fps"], args.crf, dur)
        if not args.workdir:
            shutil.rmtree(seq, ignore_errors=True)
        log("composto -> %s" % args.out)
        print(args.out)


if __name__ == "__main__":
    main()
