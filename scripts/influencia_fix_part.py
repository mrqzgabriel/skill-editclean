#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - influencia_fix_part.py  (v2.9)

Video que veio do influencIA (clipes do Veo com a voz trocada): quando a voz gerada
PRONUNCIA ERRADO uma palavra (ou balbucia), a correcao certa nao e na edicao -- e na
origem. Este script fecha o ciclo pela API de PRODUCAO do influencIA:

  check   baixa/usa as partes, transcreve cada uma com o whisper-1 da OpenAI (o mesmo
          transcritor que o sistema usa) e compara token a token com a COPIA de cada
          parte no banco. Classifica: OK / PRONUNCIA (palavra trocada) / BALBUCIO
          (fala continua muito alem do fim da copia -- copia curta demais para os 8 s).
  fix     troca o texto da copia (PUT), regenera SO aquela parte (POST generate-video),
          espera o poller da producao terminar (Veo + troca de voz), baixa o video novo
          para a pasta das partes (guardando o antigo como parteN_vK.mp4) e reconfere
          com o whisper-1. Repete ate --retries se ainda sair errado.

Pedido do Gabriel (01/09/2026): "quando identificar algum problema assim, entrar no
sistema influencIA e regenerar, podendo ate mesmo mudar a copy pra pronuncia ficar
certa". A escolha da palavra nova e editorial (SKILL.md 1c); aqui e so a mecanica.

Credenciais: le LOGIN/SENHA/OPENAI_API_KEY do .env do influencIA. O caminho vem de
$INFLUENCIA_ENV, de "influencia_env" no .credentials.json da skill, ou do padrao
~/Desktop/MandatoJá/influencIA/.env. A API vem de $INFLUENCIA_API / "influencia_api" /
o padrao abaixo. NUNCA imprime chave ou senha.

Uso:
  python3 influencia_fix_part.py check --project "Claude Fable 5.1" --parts-dir "<pasta>"
  python3 influencia_fix_part.py fix   --project "Claude Fable 5.1" --parts-dir "<pasta>" \
          --part 2 --text "A promessa e simples e pesada, tocar projetos longos sem quebrar tudo por um erro pequeno."
"""

import argparse
import http.cookiejar
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
CRED_PATH = os.path.join(SKILL_ROOT, ".credentials.json")
DEFAULT_ENV = os.path.expanduser("~/Desktop/MandatoJá/influencIA/.env")
DEFAULT_API = "https://solange-solange.feyjc1.easypanel.host/api"
WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"
POLL_S = 15
POLL_MAX_S = 25 * 60

NUMEROS = {"zero": "0", "um": "1", "uma": "1", "dois": "2", "duas": "2", "tres": "3", "quatro": "4",
           "cinco": "5", "seis": "6", "sete": "7", "oito": "8", "nove": "9", "dez": "10", "onze": "11",
           "doze": "12", "treze": "13", "catorze": "14", "quatorze": "14", "quinze": "15", "dezesseis": "16",
           "dezessete": "17", "dezoito": "18", "dezenove": "19", "vinte": "20", "trinta": "30",
           "quarenta": "40", "cinquenta": "50", "sessenta": "60", "setenta": "70", "oitenta": "80",
           "noventa": "90", "cem": "100", "mil": "1000"}


def log(msg):
    sys.stderr.write("[influencia] %s\n" % msg)


# ---------------------------------------------------------------- config
def _cred(key):
    try:
        return (json.load(open(CRED_PATH, encoding="utf-8")) or {}).get(key)
    except Exception:
        return None


def load_env():
    path = os.environ.get("INFLUENCIA_ENV") or _cred("influencia_env") or DEFAULT_ENV
    if not os.path.isfile(path):
        raise SystemExit("nao achei o .env do influencIA em %s (defina INFLUENCIA_ENV ou "
                         "\"influencia_env\" no .credentials.json)" % path)
    env = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
        if m:
            env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    for k in ("LOGIN", "SENHA"):
        if not env.get(k):
            raise SystemExit("o .env do influencIA nao tem %s" % k)
    env["_api"] = (os.environ.get("INFLUENCIA_API") or _cred("influencia_api") or DEFAULT_API).rstrip("/")
    env["_openai"] = os.environ.get("OPENAI_API_KEY") or env.get("OPENAI_API_KEY") or _cred("OPENAI_API_KEY")
    if not env["_openai"]:
        raise SystemExit("sem OPENAI_API_KEY (ambiente, .env do influencIA ou .credentials.json)")
    return env


# ---------------------------------------------------------------- API
class Api:
    def __init__(self, env):
        self.base = env["_api"]
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self._login(env["LOGIN"], env["SENHA"])

    def _req(self, method, path, body=None, timeout=60):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "User-Agent": "EditCleanSkill/2.9"})
        try:
            with self.opener.open(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            raise SystemExit("API %s %s -> HTTP %d: %s" % (method, path, e.code, raw[:300]))
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def _login(self, login, senha):
        self._req("POST", "/auth/login", {"login": login, "senha": senha})
        me = self._req("GET", "/auth/me")
        if isinstance(me, dict) and me.get("error"):
            raise SystemExit("login no influencIA falhou")
        log("login ok em %s" % self.base)

    def projects(self):
        return self._req("GET", "/projects")

    def project(self, pid):
        return self._req("GET", "/projects/%s" % pid)

    def put_copy(self, copy_id, text):
        return self._req("PUT", "/copy-parts/%s" % copy_id, {"text": text})

    def generate_video(self, copy_id):
        return self._req("POST", "/copy-parts/%s/generate-video" % copy_id, timeout=120)

    def video_part(self, vp_id):
        return self._req("GET", "/video-parts/%s" % vp_id)


def find_project(api, query):
    projs = api.projects()
    if isinstance(projs, dict):
        projs = projs.get("projects", [])
    q = _norm_str(query)
    hit = [p for p in projs if p.get("id") == query] or \
          [p for p in projs if q and q in _norm_str(p.get("title", ""))]
    if not hit:
        raise SystemExit("projeto nao encontrado: %s (titulos: %s)" %
                         (query, "; ".join(p.get("title", "")[:40] for p in projs[:8])))
    if len(hit) > 1:
        log("mais de um projeto casa com '%s'; usando o mais recente: %s" % (query, hit[0].get("title")))
    return api.project(hit[0]["id"])


# ---------------------------------------------------------------- whisper-1
def _norm_str(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def tokens(s):
    out = []
    for t in re.findall(r"[a-z0-9]+", _norm_str(s)):
        out.append(NUMEROS.get(t, t))
    return out


def whisper1(env, path):
    """Mesma chamada do lib/whisper.ts do influencIA: whisper-1, verbose_json, palavras."""
    boundary = "----EditClean" + uuid.uuid4().hex
    fields = [("model", "whisper-1"), ("language", "pt"), ("response_format", "verbose_json"),
              ("timestamp_granularities[]", "word")]
    body = b""
    for k, v in fields:
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode()
    body += ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
             "Content-Type: video/mp4\r\n\r\n" % (boundary, os.path.basename(path))).encode()
    body += open(path, "rb").read() + ("\r\n--%s--\r\n" % boundary).encode()
    req = urllib.request.Request(WHISPER_URL, data=body, method="POST", headers={
        "Authorization": "Bearer " + env["_openai"],
        "Content-Type": "multipart/form-data; boundary=" + boundary})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    if "error" in d:
        raise SystemExit("whisper-1: %s" % d["error"])
    return d


def diff_copy(copy_text, wh):
    """Compara a copia com o que o whisper-1 ouviu. Devolve (classe, detalhe)."""
    a, b = tokens(copy_text), tokens(wh.get("text", ""))
    extra = [w for w in b if w not in a]
    missing = [w for w in a if w not in b]
    words = wh.get("words") or []
    dur = float(wh.get("duration") or 0)
    if not extra and not missing:
        return "OK", ""
    # balbucio: muitos tokens a mais, concentrados depois do ultimo token da copia
    if len(extra) >= 6 and len(missing) <= 1:
        return "BALBUCIO", "%d palavras sem sentido alem da copia; fala vai ate %.1fs de %.1fs" % (
            len(extra), words[-1]["end"] if words else -1, dur)
    if extra and missing and len(extra) <= 3 and len(missing) <= 3:
        return "PRONUNCIA", "ouviu %s no lugar de %s" % (extra, missing)
    return "DIVERGE", "a mais %s | faltou %s" % (extra, missing)


# ---------------------------------------------------------------- partes locais
def local_part_path(parts_dir, n):
    if not parts_dir:
        return None
    for cand in ("parte%d.mp4" % n, "parte%02d.mp4" % n, "part%d.mp4" % n):
        p = os.path.join(parts_dir, cand)
        if os.path.isfile(p):
            return p
    return None


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "EditCleanSkill/2.9"})
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as fh:
        shutil.copyfileobj(r, fh)
    return dest


def backup_name(parts_dir, n, tag):
    k = 1
    while True:
        cand = os.path.join(parts_dir, "parte%d_v%d%s.mp4" % (n, k, ("_" + tag) if tag else ""))
        if not os.path.exists(cand):
            return cand
        k += 1


# ---------------------------------------------------------------- comandos
def cmd_check(args):
    env = load_env()
    api = Api(env)
    proj = find_project(api, args.project)
    log("projeto: %s | influencer: %s" % (proj.get("title"), (proj.get("influencer") or {}).get("name")))
    tmp = tempfile.mkdtemp(prefix="editclean-infl-")
    report = {"project_id": proj["id"], "title": proj.get("title"), "parts": []}
    for cp in sorted(proj.get("copyParts", []), key=lambda c: c["partNumber"]):
        n = cp["partNumber"]
        vp = cp.get("videoPart") or {}
        url = vp.get("finalVideoUrl")
        path = local_part_path(args.parts_dir, n)
        src = "local"
        if not path:
            if not url:
                report["parts"].append({"part": n, "status": "SEM_VIDEO", "copy": cp["text"]})
                log("parte %d: sem video final (%s)" % (n, vp.get("status")))
                continue
            path = download(url, os.path.join(tmp, "parte%d.mp4" % n))
            src = "baixado"
        wh = whisper1(env, path)
        cls, detail = diff_copy(cp["text"], wh)
        entry = {"part": n, "status": cls, "detail": detail, "copy": cp["text"], "heard": wh.get("text", "").strip(),
                 "copy_part_id": cp["id"], "video_part_id": vp.get("id"), "source": src,
                 "attempts": vp.get("generationAttempts")}
        report["parts"].append(entry)
        log("parte %d [%s] %s" % (n, cls, detail))
        if cls != "OK":
            log("   copia : %s" % cp["text"])
            log("   ouviu : %s" % wh.get("text", "").strip())
    shutil.rmtree(tmp, ignore_errors=True)
    if args.report:
        json.dump(report, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    bad = [p for p in report["parts"] if p["status"] not in ("OK",)]
    log("%d parte(s) com problema" % len(bad))
    print(json.dumps({"project_id": proj["id"], "problems": [(p["part"], p["status"]) for p in bad]}))


def cmd_fix(args):
    env = load_env()
    api = Api(env)
    proj = find_project(api, args.project)
    cps = {c["partNumber"]: c for c in proj.get("copyParts", [])}
    if args.part not in cps:
        raise SystemExit("parte %d nao existe no projeto" % args.part)
    cp = cps[args.part]
    vp = cp.get("videoPart") or {}
    old_text = cp["text"]
    if args.text and args.text.strip() != old_text.strip():
        api.put_copy(cp["id"], args.text.strip())
        log("parte %d: copia trocada\n   de : %s\n   para: %s" % (args.part, old_text, args.text.strip()))
        new_text = args.text.strip()
    else:
        new_text = old_text
        log("parte %d: mantendo a copia, so regenerando" % args.part)

    for attempt in range(1, args.retries + 2):
        r = api.generate_video(cp["id"])
        vp_id = r.get("id") or vp.get("id")
        log("geracao disparada (tentativa %d do script; generationAttempts=%s)" % (attempt, r.get("generationAttempts")))
        t0 = time.time()
        status = None
        while time.time() - t0 < POLL_MAX_S:
            time.sleep(POLL_S)
            cur = api.video_part(vp_id)
            status = cur.get("status")
            if status in ("completed", "failed"):
                break
            log("   %s... (%ds)" % (status, int(time.time() - t0)))
        if status != "completed":
            raise SystemExit("parte %d terminou como %s: %s" % (args.part, status, cur.get("errorMessage")))
        url = cur.get("finalVideoUrl")
        if not url:
            raise SystemExit("parte %d completed sem finalVideoUrl" % args.part)
        tmp = tempfile.mkdtemp(prefix="editclean-infl-")
        new_path = download(url, os.path.join(tmp, "parte%d.mp4" % args.part))
        wh = whisper1(env, new_path)
        cls, detail = diff_copy(new_text, wh)
        log("reconferencia whisper-1: [%s] %s\n   ouviu: %s" % (cls, detail, wh.get("text", "").strip()))
        if cls == "OK" or cls == "BALBUCIO" and args.accept_babble:
            break
        if attempt <= args.retries:
            log("ainda errado; regenerando de novo")
            continue
        raise SystemExit("parte %d continua errada depois de %d tentativa(s): %s" % (args.part, attempt, detail))

    if args.parts_dir:
        old = local_part_path(args.parts_dir, args.part)
        if old:
            bak = backup_name(args.parts_dir, args.part, args.tag)
            shutil.move(old, bak)
            log("antiga guardada em %s" % bak)
        dest = os.path.join(args.parts_dir, "parte%d.mp4" % args.part)
        shutil.copyfile(new_path, dest)
        log("nova parte em %s" % dest)
        print(dest)
    else:
        print(new_path)
    if cur.get("errorMessage"):
        log("aviso do sistema: %s" % cur["errorMessage"])


def main():
    ap = argparse.ArgumentParser(description="influencIA: achar pronuncia errada e regenerar a parte")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("check")
    p1.add_argument("--project", required=True, help="titulo (trecho) ou id do projeto")
    p1.add_argument("--parts-dir", default=None, help="pasta com parteN.mp4 (senao baixa da API)")
    p1.add_argument("--report", default=None)
    p2 = sub.add_parser("fix")
    p2.add_argument("--project", required=True)
    p2.add_argument("--part", type=int, required=True)
    p2.add_argument("--text", default=None, help="copia nova (omitir = regenerar com a mesma)")
    p2.add_argument("--parts-dir", default=None, help="onde trocar parteN.mp4 (a antiga vira parteN_vK.mp4)")
    p2.add_argument("--tag", default="", help="sufixo do backup, ex.: derrugar")
    p2.add_argument("--retries", type=int, default=2, help="regeneracoes extras se ainda sair errado")
    p2.add_argument("--accept-babble", action="store_true",
                    help="aceitar BALBUCIO na reconferencia (copia curta, vai para o trim)")
    args = ap.parse_args()
    (cmd_check if args.cmd == "check" else cmd_fix)(args)


if __name__ == "__main__":
    main()
