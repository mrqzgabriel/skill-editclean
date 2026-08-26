#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_images_apify.py - busca imagens para as insercoes usando o Apify
(actor hooli~google-images-scraper).

Por que existe: os acervos Creative Commons (Openverse, Wikimedia) nao cobrem
nicho comercial. Para "trafego pago", "leads", "follow-up", "corretora" eles so
devolvem foto documental e clipart generico -- e os PNGs marcados como
"transparent background" do Openverse vem com o XADREZ PINTADO na imagem, sem
canal alfa. Este script existe para o caso em que o usuario autoriza busca
aberta.

ATENCAO: o que vem daqui NAO e Creative Commons. Sao imagens de sites
comerciais, com direitos autorais. Sempre:
  * recortar marcas de terceiros (e principalmente de CONCORRENTES do usuario);
  * avisar o usuario no resumo final;
  * preferir substituir por material proprio do usuario quando existir.

O ACERVO E MUITO SUJO (medido em 26/08/2026, 24 consultas / 217 candidatas):
  * 69 de 217 eram a PAGINA DE BLOCO DE HOTLINK -- um retangulo branco com
    "This site does not have permission to access or serve this content".
    Vem de sites de SEO-spam (billionhands, findarticles, accio, spora...) e
    passa por todos os filtros de tamanho e dominio: o arquivo baixa, tem
    1344x768 e e um JPEG valido. So da para pegar OLHANDO o pixel. Por isso
    existe looks_like_block_page() aqui embaixo -- ele roda em todo download.
  * 48 de 217 eram mockup vetorial, render 3D de celular ou composicao de
    Photoshop. O usuario REJEITA esses (ver user_overrides.images_must_be_real).
  * so 33 de 217 eram print ou fotografia real.
Conclusao pratica: peca 30 resultados por consulta, nao 10, e conte com
descartar ~85%. Consulta generica de conceito de negocio ("grafico de
crescimento", "ampulheta", "dinheiro na mesa") atrai o spam; consulta com termo
concreto e especifico ("whatsapp", "excel", nome de produto) traz resultado real.

QUANDO O FULL FALHA: o campo thumbnailUrl aponta para encrypted-tbn0.gstatic.com,
que baixa sempre e costuma ter 500-740px de largura -- suficiente para uma
insercao, que raramente passa de 1240px. Use --fallback-thumb (padrao ligado).
O gstatic tambem pode ter cacheado a pagina de bloqueio, entao ele passa pelo
mesmo detector.

Token: variavel de ambiente APIFY_TOKEN, ou --token, ou o campo "apify_token"
em <skill>/.credentials.json.

Uso:
    python3 fetch_images_apify.py --outdir DIR --query "..." --query "..." \
        [--per-query 30] [--min-width 700] [--min-height 420]
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
CRED = os.path.join(SKILL_ROOT, ".credentials.json")
ACTOR = "hooli~google-images-scraper"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# dominios que so devolvem placeholder de hotlink ou marca d'agua
BLOCKED = ("foter.com", "alicdn", "findmycollege", "placeholder", "shutterstock",
           "gettyimages", "istockphoto", "dreamstime", "123rf", "depositphotos",
           "alamy", "stock.adobe", "bigstock",
           # SEO-spam medido em 26/08: servem a pagina de bloqueio de hotlink
           # ate para o crawler do Google, entao envenenam tambem o thumbnail
           "billionhands", "findarticles", "accio.com", "spora.social",
           "energynetworkproductions", "nollymove", "anniesdeli", "behope.com",
           "j-air.jp", "chini.kvarti.ru")


def get_token(cli_token=None):
    if cli_token:
        return cli_token
    if os.environ.get("APIFY_TOKEN"):
        return os.environ["APIFY_TOKEN"]
    if os.path.exists(CRED):
        try:
            with open(CRED, encoding="utf-8") as fh:
                return json.load(fh).get("apify_token")
        except Exception:
            pass
    return None


def run_actor(token, queries, per_query, timeout=300):
    url = ("https://api.apify.com/v2/acts/%s/run-sync-get-dataset-items?token=%s"
           % (ACTOR, urllib.parse.quote(token)))
    body = json.dumps({"queries": queries, "maxResultsPerQuery": per_query}).encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download(url, dest, timeout=25, min_bytes=9000, referer=None):
    hdr = {"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    if referer:
        hdr["Referer"] = referer
    req = urllib.request.Request(url, headers=hdr)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < min_bytes:
        raise ValueError("arquivo pequeno demais (%d bytes) - provavel placeholder" % len(data))
    with open(dest, "wb") as fh:
        fh.write(data)
    return len(data)


def _image_stats(path):
    """(fracao quase-branca, fracao com cor, numero de tons distintos)."""
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.thumbnail((160, 160))
    px = list(im.getdata())
    n = max(1, len(px))
    white = sum(1 for r, g, b in px if r > 235 and g > 235 and b > 235)
    color = sum(1 for r, g, b in px if max(r, g, b) - min(r, g, b) > 28)
    buckets = {}
    for r, g, b in px:
        k = (r >> 4, g >> 4, b >> 4)
        buckets[k] = buckets.get(k, 0) + 1
    tons = sum(1 for v in buckets.values() if v >= n * 0.002)
    return white / float(n), color / float(n), tons


def looks_like_block_page(path):
    """Pega a pagina de bloqueio de hotlink pelo PIXEL, nao pelo dominio.

    'This site does not have permission to access or serve this content' baixa
    como um JPEG valido de 1344x768 e passa por qualquer filtro de tamanho.
    A assinatura e ser quase so branco e preto: sem area saturada e com um
    punhado de tons distintos, onde qualquer foto tem dezenas.

    LIMIARES MEDIDOS num corpus de 217 candidatas reais (26/08/2026), onde 86
    eram a pagina de bloqueio:
        pagina de bloqueio -> cor <= 0.0028, tons 13-16, branco 0.474-0.940
        imagem legitima     -> cor >= 0.0120, tons >= 19  (a grande maioria)
    O unico caso que encostou foi um print REAL em escala de cinza (tela de
    traducao do WhatsApp, so dois emojis vermelhos de cor): cor 0.0024, o que
    invade a faixa do bloqueio. Quem o salva e o BRANCO -- 0.420, contra o
    minimo 0.474 dos bloqueios. Por isso o piso de branco e 0.45 e nao 0.30.
    Resultado nesse corpus: 86/86 bloqueios pegos, 0 falso positivo em 131.

    ATENCAO ao contra-intuitivo: 'tons' de uma pagina de bloqueio e 16, nao 2 --
    texto preto suavizado sobre branco gera a rampa de cinza inteira. Um limite
    de tons baixo (<=10) nao pega NADA. Quem separa de verdade e a saturacao:
    a pagina de bloqueio nao tem um unico pixel colorido.

    Nao pega a foto de uma TELA exibindo a pagina de bloqueio (fica escura e
    ganha cor); essa so a conferencia visual pega.

    Conservador de proposito -- perder uma candidata custa pouco (o acervo ja
    descarta ~85%), mas deixar passar contamina a insercao. O que ele barra vai
    para <outdir>/rejeitadas/ e fica listado em images.json, nunca some calado.
    """
    try:
        white, color, tons = _image_stats(path)
    except ImportError:
        return False, ""          # sem PIL: deixa passar, a conferencia visual pega
    except Exception:
        return False, ""
    if color <= 0.004 and tons <= 18 and white >= 0.45:
        return True, ("nenhum pixel colorido (cor %.2f%%, %d tons, branco %.0f%%) - "
                      "assinatura da pagina de bloqueio de hotlink"
                      % (color * 100, tons, white * 100))
    return False, ""


def main():
    ap = argparse.ArgumentParser(description="Busca imagens via Apify (Google Images)")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--query", action="append", required=True)
    ap.add_argument("--per-query", type=int, default=30,
                    help="o acervo descarta ~85%%; peca bastante (padrao 30)")
    ap.add_argument("--min-width", type=int, default=700)
    ap.add_argument("--min-height", type=int, default=420)
    ap.add_argument("--token", default=None)
    ap.add_argument("--max-download", type=int, default=60)
    ap.add_argument("--no-fallback-thumb", action="store_true",
                    help="nao cair para o thumbnail do gstatic quando o full falhar")
    args = ap.parse_args()

    token = get_token(args.token)
    if not token:
        sys.stderr.write(
            "ERRO: token do Apify nao encontrado.\n"
            "  defina APIFY_TOKEN, passe --token, ou grave \"apify_token\" em\n"
            "  %s (chmod 600)\n" % CRED)
        return 2

    os.makedirs(args.outdir, exist_ok=True)
    print("[apify] %d consulta(s), %d resultados cada..." % (len(args.query), args.per_query))
    try:
        items = run_actor(token, args.query, args.per_query)
    except urllib.error.HTTPError as exc:
        sys.stderr.write("ERRO: Apify respondeu %s: %s\n" % (exc.code, exc.reason))
        return 3
    except Exception as exc:
        sys.stderr.write("ERRO ao chamar o Apify: %s\n" % exc)
        return 3
    print("[apify] %d resultado(s) brutos" % len(items))

    def bloqueado(*campos):
        alvo = " ".join((c or "") for c in campos).lower()
        return any(b in alvo for b in BLOCKED)

    seen, keep = set(), []
    for it in items:
        u = it.get("imageUrl") or ""
        if not u or u in seen:
            continue
        if bloqueado(u, it.get("origin"), it.get("contentUrl")):
            continue
        w, h = it.get("imageWidth") or 0, it.get("imageHeight") or 0
        t = it.get("thumbnailWidth") or 0
        # o thumbnail do gstatic serve de plano B, entao um full pequeno demais
        # ainda vale se o thumbnail tiver tamanho util
        if (w < args.min_width or h < args.min_height) and not (
                not args.no_fallback_thumb and t >= args.min_width):
            continue
        seen.add(u)
        keep.append(it)
    print("[apify] %d apos filtro de tamanho/dominio" % len(keep))

    rejdir = os.path.join(args.outdir, "rejeitadas")
    saved, notes, rejeitadas = [], [], []
    for i, it in enumerate(keep[:args.max_download]):
        u = it["imageUrl"]
        ext = os.path.splitext(urllib.parse.urlparse(u).path)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        name = "%02d_%s%s" % (i, hashlib.md5(u.encode()).hexdigest()[:6], ext)
        dest = os.path.join(args.outdir, name)

        # tenta o full; se falhar ou vier pagina de bloqueio, cai para o gstatic
        tentativas = [("full", u, it.get("contentUrl"))]
        if not args.no_fallback_thumb and it.get("thumbnailUrl"):
            tentativas.append(("thumb", it["thumbnailUrl"], None))

        size = origem_ok = None
        motivo = ""
        for rotulo, url, ref in tentativas:
            try:
                size = download(url, dest, referer=ref)
            except Exception as exc:
                motivo = "download %s falhou: %s" % (rotulo, exc)
                continue
            bloco, por_que = looks_like_block_page(dest)
            if bloco:
                motivo = "%s: %s" % (rotulo, por_que)
                continue
            origem_ok = rotulo
            break

        if not origem_ok:
            os.makedirs(rejdir, exist_ok=True)
            alvo = os.path.join(rejdir, name)
            try:
                os.replace(dest, alvo)
            except OSError:
                alvo = None
            rejeitadas.append({"url": u, "motivo": motivo, "guardada_em": alvo,
                               "origin": it.get("origin")})
            notes.append("descartada %s: %s" % (u[:60], motivo))
            continue

        saved.append({
            "path": dest, "url": u, "baixada_de": origem_ok,
            "query": it.get("query"),
            "width": it.get("imageWidth"), "height": it.get("imageHeight"),
            "title": it.get("title"), "origin": it.get("origin"),
            "page": it.get("contentUrl"), "bytes": size,
            "rights": "NAO e Creative Commons - imagem de site comercial, "
                      "provavelmente com direitos autorais",
        })

    out = os.path.join(args.outdir, "images.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"provider": "apify/google-images", "images": saved,
                   "rejeitadas": rejeitadas, "notes": notes},
                  fh, indent=1, ensure_ascii=False)
    print("[apify] %d imagem(ns) baixada(s), %d descartada(s) -> %s"
          % (len(saved), len(rejeitadas), out))
    if rejeitadas:
        print("[apify] as descartadas ficaram em %s (nenhuma some calada)" % rejdir)
    print("[apify] LEMBRETE: OLHAR cada imagem. O detector so pega a pagina de")
    print("[apify]           bloqueio; mockup vetorial, render 3D, arte de IA e")
    print("[apify]           composicao de Photoshop so o olho pega -- e o usuario")
    print("[apify]           rejeita todos eles (user_overrides.images_must_be_real).")
    print("[apify]           Recortar marcas de terceiros e avisar sobre direitos.")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
