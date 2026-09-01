#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - make_cover.py  (v2.12)

Capa (thumbnail) do video editado. Dois estilos:

  --style cinema      (padrao desde a v2.11, pedido do Gabriel 01/09: "algo mais cinematografico
                       com a mesma fonte de legenda do video... estilo cinema mesmo, e nao quero
                       cara de bravo na pessoa")
      1. gemini-3-pro-image (mesma credencial/rota do influencIA) gera um FRAME DE CINEMA sem
         nenhum texto: pessoa do peito para cima com expressao CALMA e confiante, luz de cinema
         (key suave + rim light, pouca profundidade de campo, flare anamorfico discreto, grao
         fino, realces quentes e sombras frias), fundo escuro e atmosferico ligado ao assunto,
         e o logotipo OFICIAL da marca como emblema aceso na cena (reproduzido exatamente).
      2. A tipografia e composta AQUI, com as fontes da legenda do video: Helvetica Neue Bold
         para o texto corrente e Playfair Display Italic 1,55x maior para a enfase (marque a
         enfase com *asteriscos* no --headline). Cor #FCF8F6, halo escuro difuso, glow claro no
         serifado, degrade escuro no rodape -- as mesmas regras do style-profile.

  --style influencia  o thumbnail do sistema como ele e (texto vermelho/amarelo/branco gerado
                       pelo proprio modelo, pessoa "intensa"). Mantido para quem quiser o padrao.

Entradas: --project (foto de referencia e titulo vem da API do influencIA) ou --ref/--title.
--logo <marca|png> manda o logotipo oficial (brand-logos.json). --mood escolhe o cenario
(cinema). --text-only recompoe so a tipografia sobre uma imagem ja gerada (iterar sem gastar
credito). Saida: PNG 1080x1920 + .capa.json de procedencia.

Uso:
  python3 make_cover.py --project "Claude Fable 5.1" --headline "ANTHROPIC LANÇOU O *Fable 5.1*" \
          --logo claude --out ~/Desktop/capa.png [--mood studio_haze]
  python3 make_cover.py --text-only --ref capa_sem_texto.png --headline "..." --out capa.png
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
NODE_HELPER = os.path.join(HERE, "cover_gemini.cjs")
PROFILE = os.path.join(SKILL_ROOT, "references", "style-profile.json")
FONT_SANS = "/System/Library/Fonts/HelveticaNeue.ttc"     # index 1 = Bold (mesmo da legenda)
FONT_SERIF = os.path.join(SKILL_ROOT, "assets", "fonts", "PlayfairDisplay-Italic[wght].ttf")
BG = (18, 18, 24)
W, H = 1080, 1920

MOODS = {
    "studio_haze": "a dark studio filled with soft haze, slow drifting warm light beams and faint floating "
                   "particles, very shallow depth of field",
    "server_room": "a quiet data-center corridor at night, rows of racks fading into darkness, cold blue "
                   "practical lights far behind, everything out of focus",
    "city_window": "a dark room at night in front of a large window, rain-blurred city lights as soft bokeh "
                   "far behind the person",
    "void_light": "an almost black void with a single warm volumetric light from above and a thin cool rim "
                  "light from behind, cinematic negative space",
}


def log(msg):
    sys.stderr.write("[capa] %s\n" % msg)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# =============================================================================
# prompts
# =============================================================================
def prompt_influencia(title, headline, has_logo, brand_name):
    """Prompt do generateThumbnail do influencIA (v2.10), com headline e logo opcionais."""
    logo_block = ""
    if has_logo:
        logo_block = (
            "- A SECOND IMAGE is provided: it is the OFFICIAL LOGO of %s, the company/product this news is about. "
            "Include this logo as a PROMINENT visual element of the scene — large, glowing, integrated into the "
            "background or floating beside the person. Reproduce its shape EXACTLY as given; do not redraw, "
            "restyle, distort or recolor it beyond lighting effects.\n" % (brand_name or "the brand"))
    headline_block = (
        "- The BOLD LARGE TEXT must say exactly: \"%s\" (Brazilian Portuguese, keep the accents). "
        "Do not add other sentences.\n" % headline if headline else
        "- BOLD LARGE TEXT overlay with the key phrase from the title\n")
    return (
        "Generate a vertical thumbnail image (9:16 aspect ratio, 1080x1920 pixels) for a news video in the style of "
        "Brazilian influencer thumbnails.\n\nVIDEO TITLE: %s\n\nSTYLE REQUIREMENTS:\n"
        "- The person from the reference photo must appear prominently in the FOREGROUND — close-up, from chest up, "
        "looking directly at the camera with an intense/serious expression\n"
        "- DRAMATIC cinematic background behind the person related to the news topic (could include relevant "
        "buildings, symbols, objects that relate to \"%s\")\n%s"
        "- Dark, moody, cinematic tone with dramatic lighting (volumetric light, rim lighting, high contrast)\n%s"
        "- Use BIG, HEAVY, IMPACTFUL typography\n"
        "- Some words should be in RED (#E53935) and others in YELLOW (#FFD600) for emphasis, remaining words in WHITE\n"
        "- The text should be positioned in the lower 60%% of the image, overlapping slightly with the person\n"
        "- The overall look should be eye-catching, clickbait-style, like a YouTube/Instagram news thumbnail\n"
        "- Photorealistic quality for the person, dramatic/composite style for the background\n\nCRITICAL:\n"
        "- Keep the person's face EXACTLY as in the reference photo — same features, same appearance\n"
        "- The image MUST be vertical (taller than wide), 9:16 aspect ratio\n"
        "- Make the text LARGE and READABLE even at small sizes\n"
        "- Do NOT write any person's name on the image — no influencer names, no presenter names, no names at all\n"
        "- NO watermarks, NO social media handles (no \"@\" symbols or usernames anywhere in the image)%s\n"
        "- The background scene must NOT contain any readable text — no signs, banners, building names, watermarks, "
        "or any written words in the scene. Only the TITLE overlay text is allowed\n"
        "- Buildings, objects, and scenery in the background must be clean, with no visible text or lettering on them"
        % (title, title, logo_block, headline_block,
           " and no logos other than the official one provided" if has_logo else ", no logos"))


def prompt_cinema(title, has_logo, brand_name, mood):
    """Frame de cinema SEM texto; a tipografia entra depois com as fontes da legenda."""
    scene = MOODS.get(mood, mood)
    logo_block = ""
    if has_logo:
        logo_block = (
            "- The SECOND IMAGE is the OFFICIAL LOGO of %s. Place it in the scene as ONE large glowing emblem "
            "behind or beside the person, slightly OFF-CENTER (never a perfect symmetric halo behind the head), "
            "partly softened by the haze so it reads as a practical light in the environment, not a sticker — "
            "its tips no brighter than a real lamp, its warm light spilling softly onto the person's cheek, hair "
            "and shoulder on that side. Reproduce its shape EXACTLY — do not redraw, simplify, distort, "
            "duplicate or recolor it beyond lighting.\n" % (brand_name or "the brand"))
    return (
        "Create a single cinematic film still — a frame from a prestige sci-fi drama, vertical 9:16, 1080x1920 "
        "pixels. Subject of the film: \"%s\".\n\n"
        "THE PERSON: the person from the reference photo is the protagonist, framed from the chest up, slightly "
        "off-center, looking straight into the lens with a CALM, composed, quietly confident expression — relaxed "
        "brow, soft neutral mouth, no anger, no frown, no smile forced. Keep the face EXACTLY as in the reference "
        "(same features, same skin, same hair). Same dark plain sweatshirt.\n\n"
        "CINEMATOGRAPHY: shot on a large-format cinema camera with an anamorphic lens — very shallow depth of field, "
        "gentle oval bokeh, one subtle horizontal lens flare, fine film grain. Lighting: soft warm key light from "
        "the front-left, a thin cool rim light separating the person from the background, deep clean blacks. "
        "Color grading: restrained warm highlights and cool shadows, low saturation, high dynamic range, no neon "
        "clutter.\n\n"
        "ENVIRONMENT: %s. Everything behind the person is out of focus.\n"
        "%s"
        "COMPOSITION: keep the lower third of the frame calm and dark (negative space) — a title will be added "
        "there later. Nothing bright or busy below the person's chest.\n\n"
        "ABSOLUTELY NO TEXT in the image: no titles, no captions, no letters, no numbers, no signs, no watermarks, "
        "no social handles, and no logos other than the official one provided. Photorealistic, like a real "
        "photograph, not an illustration."
        % (title, scene, logo_block))


# =============================================================================
# tipografia com as fontes da legenda
# =============================================================================
def _profile_caption():
    try:
        p = json.load(open(PROFILE, encoding="utf-8"))
        c = p["captions"]
        return {"accent_ratio": float(c["typography"].get("accent_size_ratio", 1.55)),
                "color": c.get("color_hex") or "#FCF8F6",
                "line_height": float(c["typography"].get("line_height_ratio", 1.205))}
    except Exception:
        return {"accent_ratio": 1.55, "color": "#FCF8F6", "line_height": 1.205}


def parse_headline(headline):
    """'ANTHROPIC LANÇOU O *Fable 5.1*' -> [(palavra, accent?)...] com quebra por espaco."""
    runs = []
    for i, seg in enumerate(re.split(r"\*", headline)):
        accent = (i % 2 == 1)
        for w in seg.split():
            runs.append((w, accent))
    return runs


def _fonts(size, accent_ratio):
    from PIL import ImageFont
    sans = ImageFont.truetype(FONT_SANS, size, index=1)
    serif = ImageFont.truetype(FONT_SERIF, int(round(size * accent_ratio)))
    try:
        serif.set_variation_by_axes([400])
    except Exception:
        pass
    return sans, serif


def _measure(words, sans, serif, space_scale=0.8):
    """largura total de uma linha [(palavra, accent)] e altura da linha."""
    from PIL import ImageFont
    w_total, asc_max, desc_max = 0, 0, 0
    for i, (txt, acc) in enumerate(words):
        f = serif if acc else sans
        bbox = f.getbbox(txt)
        w_total += bbox[2] - bbox[0]
        asc, desc = f.getmetrics()
        asc_max, desc_max = max(asc_max, asc), max(desc_max, desc)
        if i < len(words) - 1:
            w_total += int((sans.getbbox(" ")[2] - sans.getbbox(" ")[0] or sans.size * 0.3) * space_scale * (1.6 if acc or words[i + 1][1] else 1.0))
    return w_total, asc_max, desc_max


def layout(runs, max_w, max_h, accent_ratio, size_hi, size_lo):
    """maior corpo em que o texto cabe em ate 3 linhas dentro de max_w x max_h."""
    for size in range(size_hi, size_lo - 1, -4):
        sans, serif = _fonts(size, accent_ratio)
        lines, cur = [], []
        ok = True
        for word in runs:
            trial = cur + [word]
            if _measure(trial, sans, serif)[0] <= max_w:
                cur = trial
            else:
                if not cur:
                    ok = False
                    break
                lines.append(cur)
                cur = [word]
        if cur:
            lines.append(cur)
        if not ok or len(lines) > 3:
            continue
        heights = [_measure(l, sans, serif)[1] + _measure(l, sans, serif)[2] for l in lines]
        total = sum(int(h * 1.02) for h in heights)
        if total <= max_h:
            return size, lines, sans, serif
    sans, serif = _fonts(size_lo, accent_ratio)
    return size_lo, [runs], sans, serif


def accent_color_from_image(image_path, fallback="#D97757"):
    """Cor da enfase = a cor com que o LOGO saiu na imagem (pixels laranja saturados e claros);
    se nao houver o bastante, a cor oficial da marca."""
    from PIL import Image
    import colorsys
    im = Image.open(image_path).convert("RGB").resize((270, 480))
    acc, n = [0, 0, 0], 0
    for r, g, b in im.getdata():
        h, s_, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if 0.02 <= h <= 0.13 and s_ >= 0.45 and v >= 0.62:
            acc[0] += r; acc[1] += g; acc[2] += b; n += 1
    if n < 150:
        return fallback
    r, g, b = [int(x / n) for x in acc]
    # garante leitura sobre fundo escuro: leva um pouco para o claro sem lavar
    h, s_, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    r, g, b = colorsys.hsv_to_rgb(h, min(1.0, s_ * 0.95), max(v, 0.92))
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def compose_headline(image_path, headline, out_path, center_pct=0.775, max_w_pct=0.86, max_h_pct=0.30,
                     accent_color="auto"):
    """Compoe o titulo com Helvetica Neue Bold + Playfair Italic (enfase 1,55x), halo difuso,
    glow no serifado e degrade escuro no rodape, sobre a imagem 1080x1920.
    v2.12 (pedido 01/09): bloco CENTRADO em center_pct da altura (era ancorado no rodape) e a
    enfase serifada na COR DO LOGO (accent_color="auto" le da imagem; ou hex; ou None = branco)."""
    from PIL import Image, ImageDraw, ImageFilter
    cap = _profile_caption()
    base = Image.open(image_path).convert("RGBA")
    if base.size != (W, H):
        base = base.resize((W, H), Image.LANCZOS)
    runs = parse_headline(headline)
    size, lines, sans, serif = layout(runs, int(W * max_w_pct), int(H * max_h_pct), cap["accent_ratio"], 150, 70)

    # degrade escuro no rodape (cinema): transparente em 52% -> 78% preto na base
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    y0 = int(H * 0.52)
    for y in range(y0, H):
        a = int(200 * ((y - y0) / float(H - y0)) ** 1.4)
        gd.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    base.alpha_composite(grad)

    # posicoes das linhas (bloco ancorado pelo fundo em bottom_pct)
    metrics = [_measure(l, sans, serif) for l in lines]
    line_h = [int((m[1] + m[2]) * 1.02) for m in metrics]
    block_h = sum(line_h)
    y = int(H * center_pct) - block_h // 2
    color = tuple(int(cap["color"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    if accent_color == "auto":
        accent_color = accent_color_from_image(image_path)
    acc_rgb = (tuple(int(accent_color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) if accent_color else color)

    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dh, dg, dt = ImageDraw.Draw(halo), ImageDraw.Draw(glow), ImageDraw.Draw(text)
    space = int((sans.getbbox(" ")[2] - sans.getbbox(" ")[0] or sans.size * 0.3) * 0.8)
    for li, line in enumerate(lines):
        lw, asc, desc = metrics[li]
        x = (W - lw) // 2
        baseline = y + asc
        for i, (txt, acc) in enumerate(line):
            f = serif if acc else sans
            bbox = f.getbbox(txt)
            fa, _ = f.getmetrics()
            pos = (x - bbox[0], baseline - fa)
            dh.text(pos, txt, font=f, fill=(0, 0, 0, 255), stroke_width=max(2, size // 14), stroke_fill=(0, 0, 0, 255))
            if acc:
                dg.text(pos, txt, font=f, fill=acc_rgb + (255,), stroke_width=max(1, size // 30), stroke_fill=acc_rgb + (255,))
            dt.text(pos, txt, font=f, fill=(acc_rgb if acc else color) + (255,))
            x += bbox[2] - bbox[0]
            if i < len(line) - 1:
                x += int(space * (1.6 if acc or line[i + 1][1] else 1.0))
        y += line_h[li]

    halo = halo.filter(ImageFilter.GaussianBlur(max(6, size * 0.22)))
    halo.putalpha(halo.split()[3].point(lambda v: int(v * 0.62)))
    halo = Image.eval(halo, lambda v: v)  # no-op para manter RGBA
    glow = glow.filter(ImageFilter.GaussianBlur(max(3, size * 0.10)))
    glow.putalpha(glow.split()[3].point(lambda v: int(v * 0.60)))
    base.alpha_composite(halo, (0, max(2, size // 40)))
    base.alpha_composite(glow)
    base.alpha_composite(text)
    base.convert("RGB").save(out_path, "PNG")
    return {"font_size": size, "lines": [" ".join(w for w, _ in l) for l in lines],
            "center_pct": center_pct, "accent_color": accent_color}


def fit_vertical(src, dest, w=W, h=H):
    """Igual ao fitToVertical do sistema: contain em 1080x1920 sobre (18,18,24)."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    scale = min(w / im.width, h / im.height)
    nw, nh = max(1, int(round(im.width * scale))), max(1, int(round(im.height * scale)))
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (w, h), BG)
    canvas.paste(im, ((w - nw) // 2, (h - nh) // 2))
    canvas.save(dest, "PNG")
    return (nw, nh)


# =============================================================================
def main():
    ap = argparse.ArgumentParser(description="Capa do video (cinema / influencia)")
    ap.add_argument("--style", default="cinema", choices=["cinema", "influencia"])
    ap.add_argument("--project", default=None, help="titulo (trecho) ou id do projeto no influencIA")
    ap.add_argument("--ref", default=None, help="foto de referencia (ou, com --text-only, a imagem pronta)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--headline", default=None, help="texto grande; *asteriscos* marcam a enfase serifada")
    ap.add_argument("--logo", default=None, help="marca do registro (claude, openai...) ou caminho de PNG")
    ap.add_argument("--no-logo", action="store_true")
    ap.add_argument("--mood", default="studio_haze", help="cenario do cinema: %s ou texto livre" % ", ".join(MOODS))
    ap.add_argument("--text-only", action="store_true", help="so compor a tipografia sobre --ref")
    ap.add_argument("--text-center", type=float, default=0.775, help="centro vertical do bloco de titulo (fracao da altura)")
    ap.add_argument("--accent-color", default="auto", help="cor da enfase serifada: auto (cor do logo na imagem), #hex ou none")
    ap.add_argument("--keep-raw", default=None, help="salvar tambem a imagem sem texto neste caminho")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    if os.path.exists(args.out) and not args.overwrite:
        raise SystemExit("saida ja existe (use --overwrite): %s" % args.out)
    meta = {"generated_at": time.strftime("%Y-%m-%d %H:%M"), "style": args.style, "headline": args.headline}

    if args.text_only:
        if not args.ref or not args.headline:
            raise SystemExit("--text-only precisa de --ref (imagem) e --headline")
        acc = None if str(args.accent_color).lower() == "none" else args.accent_color
        info = compose_headline(args.ref, args.headline, args.out, center_pct=args.text_center, accent_color=acc)
        meta.update({"base_image": args.ref, "typography": info})
        json.dump(meta, open(os.path.splitext(args.out)[0] + ".capa.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log("tipografia composta sobre %s -> %s (corpo %d px, %d linha(s))" % (args.ref, args.out, info["font_size"], len(info["lines"])))
        print(args.out)
        return

    infl = _load("influencia_fix_part")
    env = infl.load_env()
    env_path = os.environ.get("INFLUENCIA_ENV") or infl._cred("influencia_env") or infl.DEFAULT_ENV
    tmp = tempfile.mkdtemp(prefix="editclean-capa-")

    title, ref = args.title, args.ref
    if args.project and (not ref or not title):
        api = infl.Api(env)
        proj = infl.find_project(api, args.project)
        title = title or proj.get("title") or ""
        if not ref:
            url = proj.get("referenceImageUrl") or (proj.get("influencer") or {}).get("referenceImageUrl")
            if not url:
                raise SystemExit("projeto sem foto de referencia; passe --ref")
            ref = infl.download(url, os.path.join(tmp, "ref.png"))
            log("foto de referencia do influencer %s baixada" % (proj.get("influencer") or {}).get("name"))
    if not ref or not title:
        raise SystemExit("preciso de --ref e --title (ou --project)")

    logo_path, brand_name = None, None
    if args.logo and not args.no_logo:
        if os.path.isfile(args.logo):
            logo_path, brand_name = args.logo, os.path.splitext(os.path.basename(args.logo))[0]
        else:
            bl = _load("brand_logos")
            logo_path = bl.fetch_logo(args.logo)
            if not logo_path:
                raise SystemExit("marca sem logotipo oficial no registro: %s" % args.logo)
            brand_name = bl.load_registry()["brands"][args.logo].get("name", args.logo)
        from PIL import Image
        im = Image.open(logo_path).convert("RGBA")
        pad = int(max(im.size) * 0.12)
        bgim = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (8, 8, 10, 255))
        bgim.alpha_composite(im, (pad, pad))
        logo_send = os.path.join(tmp, "logo.png")
        tw = min(1024, bgim.width)
        bgim.convert("RGB").resize((tw, int(bgim.height * tw / bgim.width)), Image.LANCZOS).save(logo_send)
        logo_path = logo_send

    if args.style == "cinema":
        prompt = prompt_cinema(title, bool(logo_path), brand_name, args.mood)
    else:
        prompt = prompt_influencia(title, (args.headline or "").replace("*", ""), bool(logo_path), brand_name)
    prompt_file = os.path.join(tmp, "prompt.txt")
    open(prompt_file, "w", encoding="utf-8").write(prompt)
    raw = os.path.join(tmp, "raw.png")
    node = shutil.which("node")
    if not node:
        raise SystemExit("node nao encontrado no PATH")
    cmd = [node, NODE_HELPER, "--env", env_path, "--ref", ref, "--prompt", prompt_file, "--out", raw, "--model", args.model]
    if logo_path:
        cmd += ["--logo", logo_path]
    log("gerando (%s, mood %s) com %s..." % (args.style, args.mood if args.style == "cinema" else "-", args.model))
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sys.stderr.write(p.stderr.decode("utf-8", "replace"))
    if p.returncode != 0 or not os.path.isfile(raw):
        raise SystemExit("geracao da capa falhou")
    fitted = os.path.join(tmp, "fitted.png")
    size = fit_vertical(raw, fitted)
    if args.keep_raw:
        shutil.copyfile(fitted, args.keep_raw)
    if args.style == "cinema" and args.headline:
        acc = None if str(args.accent_color).lower() == "none" else args.accent_color
        info = compose_headline(fitted, args.headline, args.out, center_pct=args.text_center, accent_color=acc)
        meta["typography"] = info
    else:
        shutil.copyfile(fitted, args.out)
    meta.update({"model": args.model, "title": title, "mood": args.mood if args.style == "cinema" else None,
                 "logo": args.logo if logo_path else None, "reference": ref if args.ref else "influencer do projeto",
                 "raw_size": size, "prompt": prompt})
    json.dump(meta, open(os.path.splitext(args.out)[0] + ".capa.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)
    log("capa: %s (imagem %dx%d -> 1080x1920)" % (args.out, size[0], size[1]))
    print(args.out)


if __name__ == "__main__":
    main()
