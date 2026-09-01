#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - make_cover.py  (v2.10)

Capa (thumbnail) do video editado, gerada IGUAL ao influencIA: mesmo modelo
(gemini-3-pro-image no Vertex, location global), mesma foto de referencia do
influencer, mesmo prompt de thumbnail (pessoa em primeiro plano do peito para cima,
fundo cinematografico escuro ligado ao assunto, TEXTO GRANDE em vermelho/amarelo/
branco na metade de baixo, 9:16) e o mesmo ajuste final para 1080x1920 sobre fundo
(18,18,24). Por cima disso, duas coisas que o sistema nao tem:

  - --logo <marca|png>: o logotipo OFICIAL (registro do brand_logos.py) entra como
    segunda imagem e o prompt manda reproduzi-lo exatamente, grande, como elemento da
    cena. Pedido do Gabriel (01/09): "uma capa com o logo do Claude falando que a
    Anthropic lancou o Fable".
  - --headline: a frase do texto grande, em vez de deixar o modelo extrair do titulo.

A foto de referencia vem da API do influencIA (--project), ou de --ref. A geracao
usa a credencial do proprio sistema (cover_gemini.cjs). Saida: PNG 1080x1920 + um
.json de procedencia (prompt, modelo, entradas) ao lado.

Uso:
  python3 make_cover.py --project "Claude Fable 5.1" --headline "ANTHROPIC LANCOU O FABLE 5.1" \
          --logo claude --out ~/Desktop/capa.png
  python3 make_cover.py --ref foto.png --title "..." --headline "..." --out capa.png [--no-logo]
"""

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
LOGO_DIR = os.path.join(SKILL_ROOT, "assets", "logos")
NODE_HELPER = os.path.join(HERE, "cover_gemini.cjs")
BG = (18, 18, 24)


def log(msg):
    sys.stderr.write("[capa] %s\n" % msg)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_prompt(title, headline, has_logo, brand_name):
    """Prompt do generateThumbnail do influencIA, com o headline e o logo por cima."""
    logo_block = ""
    if has_logo:
        logo_block = (
            "- A SECOND IMAGE is provided: it is the OFFICIAL LOGO of %s, the company/product this news is about. "
            "Include this logo as a PROMINENT visual element of the scene — large, glowing, integrated into the "
            "background or floating beside the person. Reproduce its shape EXACTLY as given; do not redraw, "
            "restyle, distort or recolor it beyond lighting effects.\n" % (brand_name or "the brand")
        )
    headline_block = (
        "- The BOLD LARGE TEXT must say exactly: \"%s\" (Brazilian Portuguese, keep the accents). "
        "Do not add other sentences.\n" % headline if headline else
        "- BOLD LARGE TEXT overlay with the key phrase from the title\n"
    )
    return (
        "Generate a vertical thumbnail image (9:16 aspect ratio, 1080x1920 pixels) for a news video in the style of "
        "Brazilian influencer thumbnails.\n\n"
        "VIDEO TITLE: %s\n\n"
        "STYLE REQUIREMENTS:\n"
        "- The person from the reference photo must appear prominently in the FOREGROUND — close-up, from chest up, "
        "looking directly at the camera with an intense/serious expression\n"
        "- DRAMATIC cinematic background behind the person related to the news topic (could include relevant "
        "buildings, symbols, objects that relate to \"%s\")\n"
        "%s"
        "- Dark, moody, cinematic tone with dramatic lighting (volumetric light, rim lighting, high contrast)\n"
        "%s"
        "- Use BIG, HEAVY, IMPACTFUL typography\n"
        "- Some words should be in RED (#E53935) and others in YELLOW (#FFD600) for emphasis, remaining words in WHITE\n"
        "- The text should be positioned in the lower 60%% of the image, overlapping slightly with the person\n"
        "- The overall look should be eye-catching, clickbait-style, like a YouTube/Instagram news thumbnail\n"
        "- Photorealistic quality for the person, dramatic/composite style for the background\n\n"
        "CRITICAL:\n"
        "- Keep the person's face EXACTLY as in the reference photo — same features, same appearance\n"
        "- The image MUST be vertical (taller than wide), 9:16 aspect ratio\n"
        "- Make the text LARGE and READABLE even at small sizes\n"
        "- Do NOT write any person's name on the image — no influencer names, no presenter names, no names at all\n"
        "- NO watermarks, NO social media handles (no \"@\" symbols or usernames anywhere in the image)%s\n"
        "- The background scene must NOT contain any readable text — no signs, banners, building names, watermarks, "
        "or any written words in the scene. Only the TITLE overlay text is allowed\n"
        "- Buildings, objects, and scenery in the background must be clean, with no visible text or lettering on them"
        % (title, title, logo_block, headline_block,
           " and no logos other than the official one provided" if has_logo else ", no logos")
    )


def fit_vertical(src, dest, w=1080, h=1920):
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


def main():
    ap = argparse.ArgumentParser(description="Capa do video, igual ao thumbnail do influencIA")
    ap.add_argument("--project", default=None, help="titulo (trecho) ou id do projeto no influencIA")
    ap.add_argument("--ref", default=None, help="foto de referencia (senao vem do influencer do projeto)")
    ap.add_argument("--title", default=None, help="titulo do video (senao vem do projeto)")
    ap.add_argument("--headline", default=None, help="frase do texto grande; senao o modelo tira do titulo")
    ap.add_argument("--logo", default=None, help="marca do registro (claude, openai...) ou caminho de PNG")
    ap.add_argument("--no-logo", action="store_true")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="gemini-3-pro-image")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    if os.path.exists(args.out) and not args.overwrite:
        raise SystemExit("saida ja existe (use --overwrite): %s" % args.out)
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
        # o Gemini recebe o logo sobre fundo escuro (PNG com alfa vira preto em alguns caminhos)
        from PIL import Image
        im = Image.open(logo_path).convert("RGBA")
        pad = int(max(im.size) * 0.12)
        bgim = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (8, 8, 10, 255))
        bgim.alpha_composite(im, (pad, pad))
        logo_send = os.path.join(tmp, "logo.png")
        bgim.convert("RGB").resize((min(1024, bgim.width), int(bgim.height * min(1024, bgim.width) / bgim.width)), Image.LANCZOS).save(logo_send)
        logo_path = logo_send

    prompt = build_prompt(title, args.headline, bool(logo_path), brand_name)
    prompt_file = os.path.join(tmp, "prompt.txt")
    open(prompt_file, "w", encoding="utf-8").write(prompt)
    raw = os.path.join(tmp, "raw.png")
    node = shutil.which("node")
    if not node:
        raise SystemExit("node nao encontrado no PATH")
    cmd = [node, NODE_HELPER, "--env", env_path, "--ref", ref, "--prompt", prompt_file, "--out", raw, "--model", args.model]
    if logo_path:
        cmd += ["--logo", logo_path]
    log("gerando com %s..." % args.model)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sys.stderr.write(p.stderr.decode("utf-8", "replace"))
    if p.returncode != 0 or not os.path.isfile(raw):
        raise SystemExit("geracao da capa falhou")
    size = fit_vertical(raw, args.out)
    meta = {"generated_at": time.strftime("%Y-%m-%d %H:%M"), "model": args.model, "title": title,
            "headline": args.headline, "logo": args.logo if logo_path else None, "reference": ref if args.ref else "influencer do projeto",
            "raw_size": size, "prompt": prompt, "rule": "mesmo metodo do generateThumbnail do influencIA + logo oficial"}
    json.dump(meta, open(os.path.splitext(args.out)[0] + ".capa.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)
    log("capa: %s (imagem gerada %dx%d, ajustada a 1080x1920)" % (args.out, size[0], size[1]))
    print(args.out)


if __name__ == "__main__":
    main()
