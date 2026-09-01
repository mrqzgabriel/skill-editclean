#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - render_edit.py

Le um edit-plan.json (validado contra edit-plan.schema.json) e RENDERIZA o
video final com FFmpeg.

Escrita atomica: renderiza para "<destino>.partial.mp4" e so renomeia para o
destino final depois que validate_output.py aprovar (o proprio SKILL.md
encadeia isso; aqui garantimos que nada e escrito direto no destino).

Recursos implementados (todos testados, sem stubs):
  - trim/concat de segmentos
  - cortes secos
  - transicoes: dissolve, fade_in, fade_out, dip_to_black, wipe, whip_pan,
    blur_transition (via xfade + acrossfade no audio, mantendo A/V em sincronia)
  - zoom/punch-in com easing (crop animado + rescale, sem distorcao)
  - reenquadramento: smart_crop, blurred_background, pad
  - desfoque gaussiano por intervalo
  - overlays de imagem com fade/scale-pop e mascara de cantos arredondados
  - legendas ASS queimadas (posicionamento, sombra, destaque por familia)
  - correcao de cor (eq + colorbalance + unsharp)
  - audio: concat, crossfade, loudnorm
  - abertura blur+zoom-out e encerramento

Uso:
    python3 render_edit.py --plan plan.json --out saida.mp4 [--workdir DIR]
    python3 render_edit.py --plan plan.json --validate-only
    python3 render_edit.py --plan plan.json --out x.mp4 --print-cmd
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
SCHEMA_PATH = os.path.join(SKILL_ROOT, "references", "edit-plan.schema.json")
FONTS_DIR = os.path.join(SKILL_ROOT, "assets", "fonts")


# --------------------------------------------------------------------------
# binarios
# --------------------------------------------------------------------------

def _find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    for cand in (
        os.path.expanduser("~/.local/tools/%s" % name),
        "/opt/homebrew/bin/%s" % name,
        "/usr/local/bin/%s" % name,
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


FFMPEG = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")


# --------------------------------------------------------------------------
# validador de JSON Schema (subconjunto, stdlib apenas)
# --------------------------------------------------------------------------

class SchemaError(Exception):
    pass


def _resolve_ref(root, ref):
    if not ref.startswith("#/"):
        raise SchemaError("$ref externo nao suportado: %s" % ref)
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(instance, schema, root=None, path="$"):
    """
    Validador de JSON Schema draft-07 restrito ao que o edit-plan usa:
    type, required, properties, additionalProperties, items, enum, minimum,
    maximum, exclusiveMinimum, minItems, maxItems, minLength, pattern,
    allOf, $ref.
    Devolve lista de mensagens de erro (vazia = valido).
    """
    if root is None:
        root = schema
    errs = []

    if "$ref" in schema:
        return validate(instance, _resolve_ref(root, schema["$ref"]), root, path)

    for sub in schema.get("allOf", []):
        errs += validate(instance, sub, root, path)

    t = schema.get("type")
    if t:
        types = t if isinstance(t, list) else [t]
        ok = False
        for tt in types:
            if tt == "object" and isinstance(instance, dict):
                ok = True
            elif tt == "array" and isinstance(instance, list):
                ok = True
            elif tt == "string" and isinstance(instance, str):
                ok = True
            elif tt == "integer" and isinstance(instance, int) and not isinstance(instance, bool):
                ok = True
            elif tt == "number" and isinstance(instance, (int, float)) and not isinstance(instance, bool):
                ok = True
            elif tt == "boolean" and isinstance(instance, bool):
                ok = True
            elif tt == "null" and instance is None:
                ok = True
        if not ok:
            errs.append("%s: esperado tipo %s, recebido %s" % (path, t, type(instance).__name__))
            return errs

    if "enum" in schema and instance not in schema["enum"]:
        errs.append("%s: valor %r fora do enum %s" % (path, instance, schema["enum"]))

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append("%s: %r < minimo %r" % (path, instance, schema["minimum"]))
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append("%s: %r > maximo %r" % (path, instance, schema["maximum"]))
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errs.append("%s: %r <= minimo exclusivo %r" % (path, instance, schema["exclusiveMinimum"]))

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errs.append("%s: string curta demais" % path)
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errs.append("%s: %r nao casa com o padrao %s" % (path, instance, schema["pattern"]))

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errs.append("%s: precisa de ao menos %d itens" % (path, schema["minItems"]))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errs.append("%s: no maximo %d itens" % (path, schema["maxItems"]))
        if "items" in schema:
            for i, item in enumerate(instance):
                errs += validate(item, schema["items"], root, "%s[%d]" % (path, i))

    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                errs.append("%s: campo obrigatorio ausente: %s" % (path, req))
        props = schema.get("properties", {})
        for key, val in instance.items():
            if key in props:
                errs += validate(val, props[key], root, "%s.%s" % (path, key))
            elif schema.get("additionalProperties") is False:
                errs.append("%s: propriedade nao permitida: %s" % (path, key))

    return errs


def validate_plan(plan):
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        schema = json.load(fh)
    errs = validate(plan, schema)

    # checagens semanticas que o schema sozinho nao cobre
    segs = plan.get("segments", [])
    for i, s in enumerate(segs):
        if s["src_end"] <= s["src_start"]:
            errs.append("segments[%d] (%s): src_end <= src_start" % (i, s.get("id")))
        dur = s["src_end"] - s["src_start"]
        if abs(dur - s["duration"]) > 0.05:
            errs.append("segments[%d] (%s): duration=%.3f nao bate com src_end-src_start=%.3f"
                        % (i, s.get("id"), s["duration"], dur))
        z = s.get("zoom")
        if z and z.get("duration") and z["duration"] > s["duration"] + 0.01:
            errs.append("segments[%d]: zoom.duration maior que o segmento" % i)

    src_dur = plan.get("source", {}).get("duration")
    if src_dur:
        for i, s in enumerate(segs):
            if s["src_end"] > src_dur + 0.1:
                errs.append("segments[%d]: src_end %.3f alem da duracao do fonte %.3f"
                            % (i, s["src_end"], src_dur))

    ids = [s["id"] for s in segs]
    if len(ids) != len(set(ids)):
        errs.append("segments: ids duplicados")

    for tr in plan.get("transitions", []):
        btw = tr.get("between") or []
        for sid in btw:
            if sid not in ids:
                errs.append("transitions[%s]: segmento desconhecido %s" % (tr.get("id"), sid))
        if tr.get("duration", 0) <= 0:
            errs.append("transitions[%s]: duracao deve ser > 0" % tr.get("id"))

    caps = plan.get("captions") or {}
    if caps.get("enabled"):
        for b in caps.get("blocks", []):
            if b["end"] <= b["start"]:
                errs.append("captions.blocks[%s]: end <= start" % b.get("id"))
            for w in b.get("words", []):
                if w["end"] < w["start"]:
                    errs.append("captions.blocks[%s]: palavra com end < start" % b.get("id"))

    for ov in plan.get("overlays", []):
        p = (ov.get("params") or {}).get("path")
        if p and not os.path.isfile(os.path.expanduser(p)):
            errs.append("overlays[%s]: arquivo de imagem nao encontrado: %s" % (ov.get("id"), p))

    return errs


# --------------------------------------------------------------------------
# helpers de expressao / easing
# --------------------------------------------------------------------------

def easing_expr(easing, prog):
    """Devolve expressao ffmpeg que mapeia prog (0..1) -> curva."""
    if easing == "ease_out":
        return "(1-pow(1-(%s)\\,2))" % prog
    if easing == "ease_in":
        return "pow((%s)\\,2)" % prog
    if easing == "ease_in_out":
        return "(if(lt(%s\\,0.5)\\,2*pow(%s\\,2)\\,1-2*pow(1-(%s)\\,2)))" % (prog, prog, prog)
    return "(%s)" % prog


def _esc_path_for_filter(p):
    """Escapa um caminho para uso dentro de filtro ffmpeg (subtitles=...)."""
    p = p.replace("\\", "\\\\")
    p = p.replace(":", "\\:")
    p = p.replace("'", "\\'")
    p = p.replace("[", "\\[").replace("]", "\\]")
    p = p.replace(",", "\\,")
    return p


def even(n):
    n = int(round(n))
    return n if n % 2 == 0 else n + 1


# --------------------------------------------------------------------------
# ASS (legendas)
# --------------------------------------------------------------------------

ASS_ANCHOR_ALIGN = {"center": 8, "left": 7}


def _ass_color(hex_color, alpha=0.0):
    """#RRGGBB -> &HAABBGGRR"""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    a = int(round(max(0.0, min(1.0, alpha)) * 255))
    return "&H%02X%02X%02X%02X" % (a, b, g, r)


def _ass_time(t):
    t = max(0.0, float(t))
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return "%d:%02d:%05.2f" % (h, m, s)


def _ass_escape(text):
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def build_ass(plan, out_path):
    """Gera o .ass com revelacao palavra a palavra e destaque por familia.

    Estilo v2.1 (medido na captura de referencia):
      - toda palavra sem serifa e BOLD (traco/x-height 0.21-0.23 = HN Bold);
      - o serifado e composto maior (accent_size_ratio);
      - a "sombra" e um HALO escuro difuso desenhado numa camada inferior
        (borda + blur alto, alpha moderado), nao uma sombra dura deslocada;
      - espaco entre palavras encolhido via \\fscx no proprio espaco.
    """
    caps = plan["captions"]
    W = plan["output"]["width"]
    H = plan["output"]["height"]

    font_primary = caps.get("font_primary", "Helvetica Neue")
    font_accent = caps.get("font_accent", "Playfair Display")
    base_size = int(caps.get("font_size_px") or max(16, round(H * 0.060)))
    accent_ratio = float(caps.get("accent_size_ratio", 1.0))

    sans_bold_always = bool(caps.get("sans_bold_always", False))
    space_scale = float(caps.get("word_space_scale", 1.0))

    glow = caps.get("soft_glow") or {}
    glow_on = bool(glow.get("enabled"))
    aglow = caps.get("accent_glow") or {}
    aglow_on = bool(aglow.get("enabled"))
    ag_alpha = max(0.0, min(1.0, float(aglow.get("alpha", 0.60))))
    ag_a_hex = "%02X" % int(round((1.0 - ag_alpha) * 255))
    ag_bord = float(aglow.get("bord_px", 2.5)) * (H / 1920.0)
    ag_blur = float(aglow.get("blur_px", 6.0)) * (H / 1920.0)
    ag_col = _ass_color(aglow.get("color", "#FFFFFF"))
    g_alpha = max(0.0, min(1.0, float(glow.get("alpha", 0.45))))
    g_a_hex = "%02X" % int(round((1.0 - g_alpha) * 255))
    g_bord = float(glow.get("bord_px", 5.0)) * (H / 1920.0)
    g_blur = float(glow.get("blur_px", 13.0)) * (H / 1920.0)
    g_dy = float(glow.get("dy_px", 2.0)) * (H / 1920.0)
    g_col = _ass_color(glow.get("color", "#000000"))

    sh = caps.get("shadow") or {}
    legacy_shadow = (not glow_on) and sh.get("present", False)
    shadow_depth = float(sh.get("offset_px", 2)) if legacy_shadow else 0.0
    shadow_alpha = float(sh.get("alpha", 0.62))
    ol = caps.get("outline") or {}
    outline_w = float(ol.get("width_px", 0)) if ol.get("present") else 0.0

    primary = _ass_color(caps.get("primary_hex", "#FBF8F4"))
    accent_col = _ass_color(caps.get("accent_hex", caps.get("primary_hex", "#FBF8F4")))
    back = _ass_color("#000000", 1.0 - shadow_alpha)

    anchors = caps.get("anchors") or {}
    anchor_y = {
        "lower_default": float(anchors.get("lower_default", 0.55)),
        "footer": float(anchors.get("footer", 0.76)),
        "upper": float(anchors.get("upper", 0.15)),
    }
    side_margin = float(caps.get("side_margin_pct", 0.09))

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: %d" % W,
        "PlayResY: %d" % H,
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
         "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
         "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"),
    ]

    margin_lr = int(W * side_margin)
    tracking = float(caps.get("tracking_px", -1))
    normal_bold = 1 if sans_bold_always else 0
    for name, fontname, bold, italic, colour in (
        ("Normal", font_primary, normal_bold, 0, primary),
        ("Strong", font_primary, 1, 0, primary),
        ("Accent", font_accent, 0, 1, accent_col),
    ):
        lines.append(
            "Style: %s,%s,%d,%s,%s,%s,%s,%d,%d,0,0,100,100,%.1f,0,1,%.1f,%.1f,8,%d,%d,0,1"
            % (name, fontname, base_size, colour, colour, _ass_color("#000000"), back,
               bold, italic, tracking, outline_w, shadow_depth, margin_lr, margin_lr)
        )

    lines += [
        "",
        "[Events]",
        ("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"),
    ]

    style_of = {"normal": "Normal", "strong": "Strong", "accent": "Accent"}
    joiner = " " if space_scale >= 0.999 else ("{\\fscx%d} {\\fscx100}" % int(round(space_scale * 100)))

    def render_layer(words_state, n_lines, fs_block, fade, kind):
        """Texto do estado atual do karaoke para uma camada ('glow' ou 'main')."""
        parts_by_line = {}
        last = len(words_state) - 1
        for j, w2 in enumerate(words_state):
            ln = int(w2.get("line", 0))
            st = style_of.get(w2.get("style", "normal"), "Normal")
            parts_by_line.setdefault(ln, []).append((st, _ass_escape(w2["text"]), j == last))
        chunks = []
        for ln in range(n_lines):
            if ln not in parts_by_line:
                continue
            seg = []
            for st, txt, is_new in parts_by_line[ln]:
                size = int(round(fs_block * (accent_ratio if st == "Accent" else 1.0)))
                if kind == "glow":
                    decor = ("\\1c%s\\3c%s\\bord%.1f\\blur%.1f\\shad0\\1a&H%s&\\3a&H%s&"
                             % (g_col, g_col, g_bord, g_blur, g_a_hex, g_a_hex))
                    anim = ("\\1a&HFF&\\3a&HFF&\\t(0,%d,\\1a&H%s&\\3a&H%s&)"
                            % (fade, g_a_hex, g_a_hex)) if (is_new and fade > 0) else ""
                elif kind == "aglow":
                    # glow CLARO e curto, so nas palavras serifadas; as outras
                    # entram invisiveis para o layout da linha nao mudar
                    if st == "Accent":
                        decor = ("\\1c%s\\3c%s\\bord%.1f\\blur%.1f\\shad0\\1a&H%s&\\3a&H%s&"
                                 % (ag_col, ag_col, ag_bord, ag_blur, ag_a_hex, ag_a_hex))
                        anim = ("\\1a&HFF&\\3a&HFF&\\t(0,%d,\\1a&H%s&\\3a&H%s&)"
                                % (fade, ag_a_hex, ag_a_hex)) if (is_new and fade > 0) else ""
                    else:
                        decor = "\\bord0\\shad0\\1a&HFF&\\3a&HFF&\\4a&HFF&"
                        anim = ""
                else:
                    decor = ""
                    anim = ("\\alpha&HFF&\\t(0,%d,\\alpha&H00&)" % fade) if (is_new and fade > 0) else ""
                seg.append("{\\r%s\\fs%d%s%s}%s" % (st, size, decor, anim, txt))
            chunks.append(joiner.join(seg))
        return "\\N".join(chunks)

    for blk in caps.get("blocks", []):
        words = blk.get("words", [])
        if not words:
            continue
        fs_block = int(blk.get("font_size_px") or base_size)
        y_pct = anchor_y.get(blk.get("anchor", "lower_default"), 0.55)
        pos_y = int(H * y_pct)
        align = blk.get("alignment", "center")
        if align == "left":
            an, pos_x = 7, margin_lr
        else:
            an, pos_x = 8, W // 2
        n_lines = max(1, int(blk.get("lines", 1)))
        fade = int(caps.get("entry_fade_ms", 150) or 0)

        for i, w in enumerate(words):
            start = float(w["start"])
            end = float(blk["end"]) if i == len(words) - 1 else float(words[i + 1]["start"])
            if end <= start:
                continue
            state = words[:i + 1]
            if glow_on:
                text_g = render_layer(state, n_lines, fs_block, fade, "glow")
                if text_g:
                    lines.append(
                        "Dialogue: 0,%s,%s,Normal,,0,0,0,,{\\an%d\\pos(%d,%d)}%s"
                        % (_ass_time(start), _ass_time(end), an, pos_x, int(pos_y + g_dy), text_g))
            if aglow_on and any(w.get("style") == "accent" for w in state):
                text_a = render_layer(state, n_lines, fs_block, fade, "aglow")
                if text_a:
                    lines.append(
                        "Dialogue: 1,%s,%s,Normal,,0,0,0,,{\\an%d\\pos(%d,%d)}%s"
                        % (_ass_time(start), _ass_time(end), an, pos_x, pos_y, text_a))
            text_m = render_layer(state, n_lines, fs_block, fade, "main")
            if not text_m:
                continue
            lines.append(
                "Dialogue: 2,%s,%s,Normal,,0,0,0,,{\\an%d\\pos(%d,%d)}%s"
                % (_ass_time(start), _ass_time(end), an, pos_x, pos_y, text_m))

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return out_path


# --------------------------------------------------------------------------
# construcao do filtergraph
# --------------------------------------------------------------------------

XFADE_TRANSITION = {
    "dissolve": "fade",
    "fade_in": "fade",
    "fade_out": "fade",
    "dip_to_black": "fadeblack",
    "blur_transition": "fade",
    "wipe": {"up": "wipeup", "down": "wipedown", "left": "wipeleft", "right": "wiperight",
             "none": "wipeleft"},
    "whip_pan": {"up": "slideup", "down": "slidedown", "left": "slideleft", "right": "slideright",
                 "none": "slideleft"},
}


def _xfade_name(tr):
    t = tr.get("type", "dissolve")
    spec = XFADE_TRANSITION.get(t, "fade")
    if isinstance(spec, dict):
        direction = (tr.get("params") or {}).get("direction", "none")
        return spec.get(direction, spec["none"])
    return spec


def build_reframe_chain(plan, label_in, label_out):
    """
    Adapta o quadro do fonte ao canvas de saida SEM ESTICAR.
    Devolve lista de strings de filtro.
    """
    W = plan["output"]["width"]
    H = plan["output"]["height"]
    rf = plan.get("reframe") or {"mode": "none"}
    mode = rf.get("mode", "none")

    src_w = plan["source"]["width"]
    src_h = plan["source"]["height"]

    if mode == "none" or (src_w == W and src_h == H):
        return ["[%s]scale=%d:%d:force_original_aspect_ratio=disable,setsar=1[%s]"
                % (label_in, W, H, label_out)] if (src_w, src_h) != (W, H) else \
               ["[%s]null[%s]" % (label_in, label_out)]

    if mode == "smart_crop":
        ax = float(rf.get("crop_anchor_x_pct", 0.5))
        ay = float(rf.get("crop_anchor_y_pct", 0.5))
        # cobre o canvas e recorta na ancora, sem distorcer
        return [
            "[%s]scale=%d:%d:force_original_aspect_ratio=increase,"
            "crop=%d:%d:(iw-ow)*%.4f:(ih-oh)*%.4f,setsar=1[%s]"
            % (label_in, W, H, W, H, ax, ay, label_out)
        ]

    if mode == "pad":
        return [
            "[%s]scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[%s]"
            % (label_in, W, H, W, H, label_out)
        ]

    # blurred_background (padrao seguro)
    sigma = float(rf.get("background_sigma", 28))
    bzoom = float(rf.get("background_zoom", 1.08))
    bright = float(rf.get("background_brightness", -0.06))
    sat = float(rf.get("background_saturation", 0.85))
    bw, bh = even(W * bzoom), even(H * bzoom)
    return [
        "[%s]split=2[bgsrc][fgsrc]" % label_in,
        "[bgsrc]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,"
        "gblur=sigma=%.2f,eq=brightness=%.3f:saturation=%.3f,setsar=1[bgblur]"
        % (bw, bh, W, H, sigma, bright, sat),
        "[fgsrc]scale=%d:%d:force_original_aspect_ratio=decrease,setsar=1[fgfit]"
        % (W, H),
        "[bgblur][fgfit]overlay=(W-w)/2:(H-h)/2:format=auto,setsar=1[%s]" % label_out,
    ]


def build_zoom_chain(seg, label_in, label_out, W, H, fps):
    """
    Zoom animado com o filtro zoompan.

    Nao usar crop com expressao temporal em w/h: o crop avalia w/h na
    configuracao do filtro (e a dimensao de saida precisa ser constante),
    entao 't' nao existe ali e o ffmpeg falha com "Error when evaluating the
    expression". zoompan e o filtro proprio para escala animada e ja entrega
    um tamanho de saida fixo (opcao s=).

    A progressao usa o contador de frames de entrada ('in'), que e estavel
    dentro do segmento (o trim ja zerou os PTS).
    """
    z = seg.get("zoom")
    if not z:
        return ["[%s]null[%s]" % (label_in, label_out)]

    s0 = float(z["scale_from"])
    s1 = float(z["scale_to"])
    if abs(s1 - s0) < 0.0005:
        return ["[%s]null[%s]" % (label_in, label_out)]

    dur = float(z.get("duration") or seg["duration"])
    dur = max(0.05, min(dur, seg["duration"]))
    offset = float(z.get("start_offset", 0.0))
    easing = z.get("easing", "ease_out")
    ax = min(1.0, max(0.0, float(z.get("anchor_x_pct", 0.5))))
    ay = min(1.0, max(0.0, float(z.get("anchor_y_pct", 0.5))))

    off_f = max(0.0, offset * fps)
    dur_f = max(1.0, dur * fps)

    prog = "clip((in-%.3f)/%.3f\\,0\\,1)" % (off_f, dur_f)
    curve = easing_expr(easing, prog)
    zexpr = "(%.5f+(%.5f)*%s)" % (s0, s1 - s0, curve)

    # zoompan calcula os PTS na timebase do ENTRADA mas declara 1/fps na saida;
    # um 'fps' logo adiante le esses PTS na timebase errada e duplica os frames
    # (2 s viram 40 s). settb+setpts reconstroem o tempo a partir do indice do
    # frame e deixam a cadeia consistente.
    #
    # Superamostragem ADAPTATIVA: o zoompan arredonda x/y para pixel INTEIRO a
    # cada frame. Em movimento normal, 2.5x basta; em movimento LENTO (creep de
    # ~0.3 px/frame) o arredondamento a 2.5x vira gagueira anda-para-anda
    # (0,75-0,05-0,75 px, medido). O fator sobe ate 6x conforme a velocidade cai,
    # para o passo no grid superamostrado ficar >= ~2 px/frame.
    diag_half = 0.5 * (W * W + H * H) ** 0.5
    est_speed = diag_half * abs(s1 - s0) / max(1e-6, dur * float(fps))
    ss = min(6.0, max(2.5, 2.0 / max(1e-6, est_speed)))
    ssw, ssh = even(W * ss), even(H * ss)
    return [
        "[%s]scale=%dx%d:flags=lanczos[%s_ss]" % (label_in, ssw, ssh, label_out),
        "[%s_ss]zoompan=z='%s':x='(iw-iw/zoom)*%.4f':y='(ih-ih/zoom)*%.4f':"
        "d=1:s=%dx%d:fps=%s,scale=%d:%d:flags=lanczos,setsar=1,settb=AVTB,setpts=N/%s/TB[%s]"
        % (label_out, zexpr, ax, ay, ssw, ssh, fps, W, H, fps, label_out)
    ]


def build_filtergraph(plan, ass_path=None, overlay_inputs=None):
    """
    Monta o filter_complex completo.
    Devolve (filter_complex_str, video_label, audio_label_or_None).
    """
    W = plan["output"]["width"]
    H = plan["output"]["height"]
    fps = plan["output"]["fps"]
    segs = plan["segments"]
    has_audio = plan["source"].get("has_audio", False) and (plan.get("audio", {}).get("enabled", True))

    transitions_by_pair = {}
    for tr in plan.get("transitions", []):
        btw = tr.get("between") or []
        if len(btw) == 2:
            transitions_by_pair[(btw[0], btw[1])] = tr

    parts = []

    # ---- 1. por segmento: trim -> reframe -> zoom -> fps/format
    for i, seg in enumerate(segs):
        vin = "v%d" % i
        parts.append(
            "[0:v]trim=start=%.4f:end=%.4f,setpts=PTS-STARTPTS[%s_t]"
            % (seg["src_start"], seg["src_end"], vin)
        )
        parts += build_reframe_chain(plan, "%s_t" % vin, "%s_r" % vin)
        parts += build_zoom_chain(seg, "%s_r" % vin, "%s_z" % vin, W, H, fps)
        parts.append(
            "[%s_z]fps=%s,format=yuv420p,setsar=1[%s]" % (vin, fps, vin)
        )

        if has_audio:
            parts.append(
                "[0:a]atrim=start=%.4f:end=%.4f,asetpts=PTS-STARTPTS[a%d]"
                % (seg["src_start"], seg["src_end"], i)
            )

    # ---- 2. juncao sequencial (concat para corte seco, xfade para transicao)
    cur_v = "v0"
    cur_a = "a0" if has_audio else None
    acc_dur = segs[0]["duration"]

    for i in range(1, len(segs)):
        prev_id = segs[i - 1]["id"]
        this_id = segs[i]["id"]
        tr = transitions_by_pair.get((prev_id, this_id))
        nv = "vj%d" % i
        na = "aj%d" % i

        if tr and tr.get("duration", 0) > 0:
            tdur = float(tr["duration"])
            tdur = max(0.033, min(tdur, segs[i - 1]["duration"] * 0.9, segs[i]["duration"] * 0.9))
            offset = max(0.0, acc_dur - tdur)
            xname = _xfade_name(tr)

            src_label = cur_v
            # blur_transition: desfoca as bordas da juncao antes do xfade
            if tr.get("type") == "blur_transition":
                sigma = float((tr.get("params") or {}).get("sigma", 14))
                blurred = "vb%d" % i
                parts.append(
                    "[%s]gblur=sigma=%.2f:enable='between(t,%.4f,%.4f)'[%s]"
                    % (src_label, sigma, offset, acc_dur, blurred)
                )
                src_label = blurred

            # xfade exige timebase identico nos dois lados; zoompan/fps podem
            # deixar cada ramo com timebase diferente do acumulado do concat.
            xa, xb = "xa%d" % i, "xb%d" % i
            parts.append("[%s]settb=AVTB[%s]" % (src_label, xa))
            parts.append("[v%d]settb=AVTB[%s]" % (i, xb))
            parts.append(
                "[%s][%s]xfade=transition=%s:duration=%.4f:offset=%.4f,format=yuv420p[%s]"
                % (xa, xb, xname, tdur, offset, nv)
            )
            if has_audio:
                parts.append(
                    "[%s][a%d]acrossfade=d=%.4f:c1=tri:c2=tri[%s]"
                    % (cur_a, i, tdur, na)
                )
            acc_dur = acc_dur + segs[i]["duration"] - tdur
        else:
            parts.append("[%s][v%d]concat=n=2:v=1:a=0[%s]" % (cur_v, i, nv))
            if has_audio:
                parts.append("[%s][a%d]concat=n=2:v=0:a=1[%s]" % (cur_a, i, na))
            acc_dur = acc_dur + segs[i]["duration"]

        cur_v = nv
        if has_audio:
            cur_a = na

    total_dur = acc_dur

    # ---- 3. abertura
    op = plan.get("opening") or {}
    if op.get("enabled") and op.get("type") == "blur_zoom_out":
        # v2.3.2: o MOVIMENTO da abertura vive no zoom do primeiro segmento
        # (superamostrado). Aqui fica so o desfoque GAUSSIANO que resolve, com
        # sigma animado FRAME A FRAME: um gblur por frame, sigma seguindo
        # (1-p)^2 (resolve rapido e assenta). Historico: degraus largos (~2
        # frames) pulsavam; crossfade nitido+desfocado dava cara de dupla
        # exposicao - o usuario pediu o gaussiano de verdade.
        odur = max(0.05, float(op.get("duration", 0.7)))
        sigma0 = float(op.get("blur_sigma_start", 18))
        n = max(2, int(math.ceil(odur * float(fps))))
        prev = cur_v
        k_used = 0
        for k in range(n):
            rem = (1.0 - (k + 0.5) / n) ** 2
            sg = sigma0 * rem
            if sg < 0.25:
                break
            t0, t1 = k / float(fps), (k + 1) / float(fps)
            lbl = "vop%d" % k
            parts.append("[%s]gblur=sigma=%.2f:enable='between(t,%.4f,%.4f)'[%s]"
                         % (prev, sg, t0, t1, lbl))
            prev = lbl
            k_used += 1
        parts.append("[%s]null[vopen]" % prev)
        cur_v = "vopen"
    elif op.get("enabled") and op.get("type") == "fade_in":
        odur = max(0.05, float(op.get("duration", 0.3)))
        nv = "vopen"
        parts.append("[%s]fade=t=in:st=0:d=%.4f[%s]" % (cur_v, odur, nv))
        cur_v = nv

    # ---- 4. desfoques pontuais
    for i, b in enumerate(plan.get("blurs", [])):
        p = b.get("params") or {}
        if p.get("region") not in (None, "full_frame"):
            continue  # regioes especificas exigiriam mascara; nao suportado -> ignorado
        sigma = float(p.get("sigma", p.get("sigma_from", 12)))
        nv = "vblur%d" % i
        parts.append(
            "[%s]gblur=sigma=%.2f:enable='between(t,%.4f,%.4f)'[%s]"
            % (cur_v, sigma, float(b["start"]), float(b["end"]), nv)
        )
        cur_v = nv

    # ---- 5. cor
    col = plan.get("color") or {}
    if col.get("enabled", True):
        eq = col.get("eq") or {}
        cb = col.get("colorbalance") or {}
        chain = []
        if eq:
            chain.append("eq=contrast=%.4f:saturation=%.4f:brightness=%.4f:gamma=%.4f"
                         % (float(eq.get("contrast", 1.0)), float(eq.get("saturation", 1.0)),
                            float(eq.get("brightness", 0.0)), float(eq.get("gamma", 1.0))))
        if cb:
            chain.append("colorbalance=" + ":".join(
                "%s=%.4f" % (k, float(cb.get(k, 0.0)))
                for k in ("rs", "gs", "bs", "rm", "gm", "bm", "rh", "gh", "bh")
            ))
        sharp = float(col.get("sharpen", 0.0) or 0.0)
        if sharp > 0:
            chain.append("unsharp=5:5:%.3f:5:5:0.0" % sharp)
        if chain:
            nv = "vcolor"
            parts.append("[%s]%s[%s]" % (cur_v, ",".join(chain), nv))
            cur_v = nv

    # ---- 6. overlays de imagem (modo classico top_band; os push_down vao
    #         DEPOIS das legendas, na secao 7.5)
    ov_list = plan.get("overlays", []) or []
    for idx, ov in enumerate(ov_list):
        p = ov.get("params") or {}
        if p.get("mode") == "push_down":
            continue
        input_index = overlay_inputs[idx] if overlay_inputs else None
        if input_index is None:
            continue
        pos = p.get("pos") or {}
        ow = even(W * float(pos.get("w_pct", 0.3)))
        ox = int(W * float(pos.get("x_pct", 0.35)))
        oy = int(H * float(pos.get("y_pct", 0.2)))
        opacity = float(p.get("opacity", 1.0))
        entry_ms = float(p.get("entry_ms", 200)) / 1000.0
        exit_ms = float(p.get("exit_ms", 0)) / 1000.0
        st, en = float(ov["start"]), float(ov["end"])

        lbl = "ovl%d" % idx
        # A imagem entra como UM unico frame (sem -loop no input). A mascara
        # geq -- cara, avaliada por pixel -- roda entao uma vez so; o filtro
        # 'loop' replica o frame ja mascarado pelo numero exato de frames que a
        # sobreposicao dura. Usar '-loop 1' no input criaria um stream infinito
        # e o overlay so termina quando TODOS os inputs dao EOF, travando o
        # render indefinidamente.
        chain = ["scale=%d:-2" % ow, "format=rgba"]
        if p.get("mask") == "circle":
            chain.append(
                "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                "a='if(lte(hypot(X-W/2,Y-H/2),min(W,H)/2),alpha(X,Y),0)'"
            )
        elif p.get("mask") == "rounded_rect":
            rad = max(1.0, float(p.get("corner_radius_pct", 0.06)) * ow)
            chain.append(
                "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if("
                "gt(hypot(max(0,max({r}-X,X-(W-{r}))),max(0,max({r}-Y,Y-(H-{r})))),{r}),0,alpha(X,Y))'"
                .format(r=rad)
            )
        if opacity < 1.0:
            chain.append("colorchannelmixer=aa=%.3f" % opacity)

        n_frames = max(2, int(math.ceil((en - st) * float(fps))) + 2)
        chain.append("loop=loop=%d:size=1:start=0" % n_frames)
        chain.append("setpts=N/%s/TB" % fps)

        if p.get("entry") == "fade" and entry_ms > 0:
            chain.append("fade=t=in:st=0:d=%.3f:alpha=1" % entry_ms)
        if p.get("exit") == "fade" and exit_ms > 0:
            chain.append("fade=t=out:st=%.3f:d=%.3f:alpha=1"
                         % (max(0.0, (en - st) - exit_ms), exit_ms))
        # desloca para o instante em que a sobreposicao deve aparecer
        chain.append("setpts=PTS+%.4f/TB" % st)

        parts.append("[%d:v]%s[%s]" % (input_index, ",".join(chain), lbl))
        nv = "vov%d" % idx
        parts.append(
            "[%s][%s]overlay=%d:%d:enable='between(t,%.4f,%.4f)':"
            "eof_action=pass:shortest=0:format=auto[%s]"
            % (cur_v, lbl, ox, oy, st, en, nv)
        )
        cur_v = nv

    # ---- 7. legendas
    if ass_path and (plan.get("captions") or {}).get("enabled"):
        nv = "vsub"
        parts.append(
            "[%s]subtitles='%s':fontsdir='%s'[%s]"
            % (cur_v, _esc_path_for_filter(ass_path), _esc_path_for_filter(FONTS_DIR), nv)
        )
        cur_v = nv

    # ---- 7.5 push-down: o video (com as legendas JA queimadas) desliza para
    #          baixo sobre fundo preto e abre palco no topo para a insercao
    #          aparecer maior. Vem DEPOIS das legendas de proposito: elas descem
    #          junto com o video e nunca trocam de ancora. As imagens do push
    #          entram por cima do conjunto ja deslocado.
    pd = plan.get("push_down") or {}
    push_ovs = [(i, o) for i, o in enumerate(ov_list)
                if (o.get("params") or {}).get("mode") == "push_down"]
    if pd.get("enabled") and pd.get("windows") and push_ovs:
        D = int(pd.get("dist_px", 0))
        ramp = max(0.05, float(pd.get("ramp_s", 0.35)))
        terms = []
        for w in pd["windows"]:
            for sgn, t0 in (("+", float(w["down_start"])),
                            ("-", float(w["up_end"]) - ramp)):
                c = "clip((t-%.4f)/%.4f,0,1)" % (t0, ramp)
                terms.append("%spow(%s,2)*(3-2*%s)" % (sgn, c, c))
        expr = "round(%d*(0%s))" % (D, "".join(terms))
        parts.append("color=c=black:s=%dx%d:r=%s[pdbg]" % (W, H, fps))
        nv = "vpush"
        parts.append("[pdbg][%s]overlay=x=0:y='%s':eval=frame:shortest=1:"
                     "format=auto[%s]" % (cur_v, expr, nv))
        cur_v = nv
        for idx, ov in push_ovs:
            input_index = overlay_inputs[idx] if overlay_inputs else None
            if input_index is None:
                continue
            p = ov.get("params") or {}
            box = p.get("box") or {}
            bw = even(int(box.get("w_px", W * 0.825)))
            bh = even(int(box.get("h_px", H * 0.23)))
            ox = int(round((W - bw) / 2.0))
            oy = int(round(H * float((p.get("pos") or {}).get("y_pct", 0.035))))
            st, en = float(ov["start"]), float(ov["end"])
            entry_ms = float(p.get("entry_ms", 300)) / 1000.0
            exit_ms = float(p.get("exit_ms", 300)) / 1000.0
            rad = max(1.0, float(p.get("corner_radius_pct", 0.03)) * min(bw, bh))
            lbl = "pov%d" % idx
            # cover: preenche a caixa cortando o excesso centrado (a caixa ja
            # foi dimensionada no plano para o corte ficar pequeno). Mesmo
            # padrao da secao 6: frame unico + filtro loop, nunca -loop 1.
            chain = ["scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos"
                     % (bw, bh),
                     "crop=%d:%d" % (bw, bh),
                     "format=rgba",
                     "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if("
                     "gt(hypot(max(0,max({r}-X,X-(W-{r}))),max(0,max({r}-Y,Y-(H-{r})))),{r}),0,alpha(X,Y))'"
                     .format(r=rad)]
            n_frames = max(2, int(math.ceil((en - st) * float(fps))) + 2)
            chain.append("loop=loop=%d:size=1:start=0" % n_frames)
            chain.append("setpts=N/%s/TB" % fps)
            if entry_ms > 0:
                chain.append("fade=t=in:st=0:d=%.3f:alpha=1" % entry_ms)
            if exit_ms > 0:
                chain.append("fade=t=out:st=%.3f:d=%.3f:alpha=1"
                             % (max(0.0, (en - st) - exit_ms), exit_ms))
            chain.append("setpts=PTS+%.4f/TB" % st)
            parts.append("[%d:v]%s[%s]" % (input_index, ",".join(chain), lbl))
            nv = "vpov%d" % idx
            parts.append("[%s][%s]overlay=%d:%d:enable='between(t,%.4f,%.4f)':"
                         "eof_action=pass:shortest=0:format=auto[%s]"
                         % (cur_v, lbl, ox, oy, st, en, nv))
            cur_v = nv

    # ---- 8. encerramento
    cl = plan.get("closing") or {}
    if cl.get("enabled") and cl.get("type") in ("fade_out", "dip_to_black"):
        cdur = max(0.05, float(cl.get("duration", 0.4)))
        nv = "vclose"
        parts.append(
            "[%s]fade=t=out:st=%.4f:d=%.4f[%s]"
            % (cur_v, max(0.0, total_dur - cdur), cdur, nv)
        )
        cur_v = nv

    parts.append("[%s]format=yuv420p[vout]" % cur_v)

    # ---- 9. audio final
    aout = None
    if has_audio:
        au = plan.get("audio") or {}
        achain = ["aresample=%d" % int(plan["output"].get("audio_sample_rate", 48000))]
        if au.get("normalize", True):
            achain.append(
                "loudnorm=I=%.1f:TP=%.1f:LRA=11"
                % (float(au.get("target_lufs", -14.0)), float(au.get("true_peak_db", -1.5)))
            )
        if cl.get("enabled") and cl.get("type") in ("fade_out", "dip_to_black"):
            # o audio pode apagar um pouco mais devagar que a imagem (audio_duration >= duration):
            # a voz some suave enquanto a tela ja esta escurecendo
            cdur = max(0.05, float(cl.get("audio_duration") or cl.get("duration", 0.4)))
            achain.append("afade=t=out:st=%.4f:d=%.4f" % (max(0.0, total_dur - cdur), cdur))
        achain.append("aformat=sample_fmts=fltp:sample_rates=%d:channel_layouts=stereo"
                      % int(plan["output"].get("audio_sample_rate", 48000)))
        parts.append("[%s]%s[aout]" % (cur_a, ",".join(achain)))
        aout = "aout"

    return ";".join(parts), "vout", aout, total_dur


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------

def render(plan, out_path, workdir, print_cmd=False, quiet=False):
    if not FFMPEG:
        sys.stderr.write("ERRO: ffmpeg nao encontrado. Instale com: brew install ffmpeg\n")
        return 2

    os.makedirs(workdir, exist_ok=True)
    src = plan["source"]["path"]

    ass_path = None
    if (plan.get("captions") or {}).get("enabled") and (plan["captions"].get("blocks")):
        ass_path = os.path.join(workdir, "captions.ass")
        build_ass(plan, ass_path)

    ov_list = plan.get("overlays", []) or []
    overlay_inputs = []
    inputs = ["-i", src]
    next_index = 1
    for ov in ov_list:
        p = os.path.expanduser((ov.get("params") or {}).get("path", ""))
        if p and os.path.isfile(p):
            # sem "-loop 1": um unico frame; a replicacao acontece no filtro
            # 'loop', com contagem finita (ver build_filtergraph)
            inputs += ["-i", p]
            overlay_inputs.append(next_index)
            next_index += 1
        else:
            overlay_inputs.append(None)

    fc, vlabel, alabel, total_dur = build_filtergraph(plan, ass_path, overlay_inputs)

    out = plan["output"]
    quality = out.get("quality", "high")
    crf = int(out.get("crf", 18 if quality == "high" else 26))
    preset = out.get("preset", "slow" if quality == "high" else "veryfast")

    partial = out_path + ".partial.mp4"
    if os.path.exists(partial):
        os.remove(partial)

    cmd = [FFMPEG, "-hide_banner", "-nostdin"]
    if quiet:
        cmd += ["-loglevel", "error", "-nostats"]
    cmd += inputs
    cmd += ["-filter_complex", fc, "-map", "[%s]" % vlabel]
    if alabel:
        cmd += ["-map", "[%s]" % alabel]
    else:
        cmd += ["-an"]
    cmd += [
        "-c:v", out.get("video_codec", "libx264"),
        "-crf", str(crf),
        "-preset", preset,
        "-pix_fmt", out.get("pixel_format", "yuv420p"),
        "-profile:v", "high",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-color_range", "tv",
        "-r", str(out["fps"]),
        "-movflags", out.get("movflags", "+faststart"),
    ]
    if alabel:
        cmd += [
            "-c:a", out.get("audio_codec", "aac"),
            "-b:a", out.get("audio_bitrate", "224k"),
            "-ar", str(out.get("audio_sample_rate", 48000)),
            "-ac", "2",
        ]
    cmd += ["-y", partial]

    if print_cmd:
        print(" \\\n  ".join(cmd))

    if not quiet:
        sys.stderr.write("[render] %d segmento(s), %d transicao(oes), duracao prevista %.2fs\n"
                         % (len(plan["segments"]), len(plan.get("transitions", [])), total_dur))

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        sys.stderr.write("ERRO no ffmpeg:\n%s\n" % proc.stderr.decode("utf-8", "replace")[-4000:])
        if os.path.exists(partial):
            os.remove(partial)
        return 1

    if not os.path.isfile(partial) or os.path.getsize(partial) == 0:
        sys.stderr.write("ERRO: arquivo parcial vazio ou ausente\n")
        return 1

    if not quiet:
        sys.stderr.write("[render] parcial escrito: %s (%d bytes)\n"
                         % (partial, os.path.getsize(partial)))
    print(partial)
    return 0


def main():
    ap = argparse.ArgumentParser(description="EditClean - renderizador")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out")
    ap.add_argument("--workdir")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--print-cmd", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    with open(args.plan, encoding="utf-8") as fh:
        plan = json.load(fh)

    errs = validate_plan(plan)
    if errs:
        sys.stderr.write("PLANO INVALIDO (%d erro(s)):\n" % len(errs))
        for e in errs[:60]:
            sys.stderr.write("  - %s\n" % e)
        sys.exit(3)

    if args.validate_only:
        print("plano valido")
        sys.exit(0)

    if not args.out:
        sys.stderr.write("ERRO: --out e obrigatorio para renderizar\n")
        sys.exit(2)

    workdir = args.workdir or os.path.join(os.path.dirname(os.path.abspath(args.plan)), "render_work")
    sys.exit(render(plan, os.path.abspath(args.out), workdir,
                    print_cmd=args.print_cmd, quiet=args.quiet))


if __name__ == "__main__":
    main()
