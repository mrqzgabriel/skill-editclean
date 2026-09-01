#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - make_caption.py  (v2.14)

Legenda do post (texto que vai no Reels, nao a legenda queimada no video), gerada do MESMO
jeito que o influencIA (artifacts/api-server/src/lib/openai.ts generateCaption): gpt-5.5 com
o prompt de social media do sistema (pt-BR, 100-200 caracteres, CTA, no maximo 5 hashtags,
ate 3-4 emojis, tom direto/opinativo, nao repete o titulo), resposta JSON {caption, hashtags}.
Pedido do Gabriel (01/09): "gere um .txt com a legenda do video pra colocar no Reels".

Entradas: --project (titulo, texto original, roteiro e nome do influencer vem da API do
influencIA) ou --title + --words (words.json do WORK: o roteiro vira a transcricao) [+ --source
texto original]. Regras da casa por cima do prompt do sistema: NUNCA travessao (—) na copy
(preferencia registrada do Gabriel) -- o prompt proibe e o script ainda troca se escapar.

Uso:
  python3 make_caption.py --project "Claude Fable 5.1" --out "<pasta>/<nome>_LEGENDA.txt"
  python3 make_caption.py --title "..." --words "$WORK/words.json" --influencer "Gabriel Marquez" --out legenda.txt
"""

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
CRED_PATH = os.path.join(SKILL_ROOT, ".credentials.json")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-5.5"


def log(msg):
    sys.stderr.write("[legenda] %s\n" % msg)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def openai_key():
    k = os.environ.get("OPENAI_API_KEY")
    if k:
        return k
    try:
        k = (json.load(open(CRED_PATH, encoding="utf-8")) or {}).get("OPENAI_API_KEY")
        if k:
            return k
    except Exception:
        pass
    try:
        infl = _load("influencia_fix_part")
        return infl.load_env().get("_openai")
    except SystemExit:
        return None


def build_prompt(influencer, title, script_parts, original_text):
    """Prompt do generateCaption do influencIA + a regra da casa (sem travessao)."""
    summary = "\n".join("Parte %d: %s" % (i + 1, t) for i, t in enumerate(script_parts))
    return (
        "Voce e um social media manager especialista em engajamento no Instagram e TikTok. Crie uma LEGENDA "
        "para acompanhar o video de noticias abaixo.\n\n"
        "INFLUENCIADOR(A): %s\nTITULO DO VIDEO: %s\n\nROTEIRO DO VIDEO:\n%s\n\n"
        "TEXTO ORIGINAL DA NOTICIA (resumido):\n%s\n\n"
        "INSTRUCOES:\n"
        "- Escreva em portugues brasileiro (pt-BR)\n"
        "- O texto principal deve ter entre 100-200 caracteres (curto e impactante)\n"
        "- Inclua um CTA (call-to-action) convidando a audiencia a comentar, compartilhar ou seguir\n"
        "- Adicione no maximo 5 hashtags relevantes ao tema da noticia\n"
        "- Use emojis com moderacao (maximo 3-4 emojis no total)\n"
        "- O tom deve combinar com o estilo do(a) influenciador(a) — direto, opinativo, engajador\n"
        "- NAO repita o titulo literalmente — reescreva de forma mais provocativa\n"
        "- A legenda deve funcionar sozinha, sem precisar ver o video\n"
        "- NUNCA use travessao (o caractere —) nem meia-risca; separe ideias com ponto, virgula ou dois-pontos\n\n"
        "Responda APENAS com um JSON valido:\n"
        "{\n  \"caption\": \"texto principal da legenda com CTA e emojis\",\n"
        "  \"hashtags\": \"#hashtag1 #hashtag2 #hashtag3 ...\"\n}"
        % (influencer, title, summary, (original_text or "")[:1500])
    )


def no_dash(text):
    """Regra da casa: sem travessao/meia-risca na copy."""
    text = re.sub(r"\s*[—–]\s*", ": ", text)
    return re.sub(r":\s*:", ":", text)


def call_openai(key, prompt):
    body = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}],
                       "response_format": {"type": "json_object"}}).encode("utf-8")
    req = urllib.request.Request(OPENAI_URL, data=body, method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    txt = (d.get("choices") or [{}])[0].get("message", {}).get("content") or "{}"
    parsed = json.loads(txt)
    if not parsed.get("caption"):
        raise SystemExit("OpenAI devolveu legenda vazia")
    tags = [h for h in (parsed.get("hashtags") or "").split() if h.startswith("#")][:5]
    return no_dash(parsed["caption"].strip()), tags


def main():
    ap = argparse.ArgumentParser(description="Legenda do post para o Reels (metodo do influencIA)")
    ap.add_argument("--project", default=None, help="titulo (trecho) ou id do projeto no influencIA")
    ap.add_argument("--title", default=None)
    ap.add_argument("--words", default=None, help="words.json do WORK (roteiro = transcricao)")
    ap.add_argument("--source", default=None, help="arquivo com o texto original da noticia (opcional)")
    ap.add_argument("--influencer", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    if os.path.exists(args.out) and not args.overwrite:
        raise SystemExit("saida ja existe (use --overwrite): %s" % args.out)

    title, influencer, parts, original = args.title, args.influencer, [], ""
    if args.project:
        infl = _load("influencia_fix_part")
        api = infl.Api(infl.load_env())
        proj = infl.find_project(api, args.project)
        title = title or proj.get("title") or ""
        influencer = influencer or (proj.get("influencer") or {}).get("name") or ""
        parts = [c["text"] for c in sorted(proj.get("copyParts", []), key=lambda c: c["partNumber"])]
        original = proj.get("originalText") or ""
    if args.words and not parts:
        ws = json.load(open(args.words, encoding="utf-8"))["words"]
        txt = " ".join(w["text"] for w in ws)
        parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", txt) if p.strip()]
    if args.source and os.path.isfile(args.source):
        original = open(args.source, encoding="utf-8").read()
    if not title or not parts:
        raise SystemExit("preciso de --project, ou de --title e --words")
    key = openai_key()
    if not key:
        raise SystemExit("sem OPENAI_API_KEY (ambiente, .credentials.json ou .env do influencIA)")

    caption, tags = call_openai(key, build_prompt(influencer or "", title, parts, original))
    full = caption + ("\n\n" + " ".join(tags) if tags else "")
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(full + "\n")
    json.dump({"model": MODEL, "title": title, "influencer": influencer, "caption": caption, "hashtags": tags,
               "chars": len(caption), "rule": "prompt do generateCaption do influencIA + sem travessao"},
              open(os.path.splitext(args.out)[0] + ".legenda.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("legenda (%d caracteres, %d hashtags) -> %s" % (len(caption), len(tags), args.out))
    print(full)


if __name__ == "__main__":
    main()
