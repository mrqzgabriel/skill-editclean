#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - broll_fetch.py (v4.0, 05/09/2026) -- b-roll em VIDEO do assunto, dos canais OFICIAIS.

O yt-dlp do Python 3.9 do sistema esta preso numa versao velha (YouTube devolve "The page needs to
be reloaded" e o cliente android so da 360p). Este script cria um venv com um Python >= 3.11
(~/.local/bin/python3.12) em <skill>/.venv-ytdlp e usa o yt-dlp atual: 1080p sem drama.

  broll_fetch.py search "OpenAI GPT-6 Astra" [--channel OpenAI] [-n 12]
      lista id | canal | duracao | titulo (filtre pelo canal oficial da empresa)
  broll_fetch.py get <id> <nome> --outdir "$WORK/broll" [--channel-expected OpenAI]
      baixa so o video (<=1080p, sem audio) em <outdir>/<nome>.mp4, gera <outdir>/sheet_<nome>.png
      (1 quadro a cada 2 s, para escolher os trechos) e registra origem em <outdir>/broll.json

Direitos: material do canal oficial da empresa, usado em trechos curtos (2-4 s) para comentario.
Registre a origem no relatorio. Nunca use video de terceiros (reacoes, canais de noticia) sem aviso.
"""
import argparse, json, os, subprocess, sys, glob

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(SKILL, ".venv-ytdlp")
FF = os.path.expanduser("~/.local/tools/ffmpeg") if os.path.isfile(os.path.expanduser("~/.local/tools/ffmpeg")) else "ffmpeg"
FP = os.path.expanduser("~/.local/tools/ffprobe") if os.path.isfile(os.path.expanduser("~/.local/tools/ffprobe")) else "ffprobe"


def ytdlp():
    exe = os.path.join(VENV, "bin", "yt-dlp")
    if os.path.isfile(exe):
        return exe
    py = None
    for c in ("~/.local/bin/python3.13", "~/.local/bin/python3.12", "~/.local/bin/python3.11", "/opt/homebrew/bin/python3", "python3.12", "python3.11"):
        c2 = os.path.expanduser(c)
        try:
            v = subprocess.run([c2, "-c", "import sys;print(sys.version_info[:2]>=(3,11))"], capture_output=True, text=True).stdout.strip()
            if v == "True": py = c2; break
        except Exception:
            continue
    if not py:
        raise SystemExit("preciso de um Python >= 3.11 para o yt-dlp atual (ex.: ~/.local/bin/python3.12)")
    subprocess.run([py, "-m", "venv", VENV], check=True)
    subprocess.run([os.path.join(VENV, "bin", "pip"), "install", "-q", "-U", "yt-dlp"], check=True)
    return exe


def cmd_search(a):
    yt = ytdlp()
    r = subprocess.run([yt, "--no-warnings", "--flat-playlist", "--print", "%(id)s | %(channel)s | %(duration)s s | %(title).90s",
                        "ytsearch%d:%s" % (a.n, a.query)], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if a.channel and a.channel.lower() not in line.lower(): continue
        print(line)


def cmd_get(a):
    yt = ytdlp(); os.makedirs(a.outdir, exist_ok=True)
    url = "https://www.youtube.com/watch?v=%s" % a.id
    meta = json.loads(subprocess.run([yt, "--no-warnings", "-J", "--no-playlist", url], capture_output=True, text=True).stdout or "{}")
    ch = meta.get("channel") or meta.get("uploader") or "?"
    if a.channel_expected and a.channel_expected.lower() not in ch.lower():
        raise SystemExit("canal do video e '%s', nao '%s' -- so canal oficial (regra 22)" % (ch, a.channel_expected))
    tmpl = os.path.join(a.outdir, a.name + ".%(ext)s")
    subprocess.run([yt, "--no-warnings", "-q", "-f", "bv*[height<=1080][ext=mp4]/bv*[height<=1080]", "-o", tmpl, url], check=True)
    f = [x for x in glob.glob(os.path.join(a.outdir, a.name + ".*")) if not x.endswith((".png", ".json"))][0]
    dest = os.path.join(a.outdir, a.name + ".mp4")
    if f != dest:
        subprocess.run([FF, "-v", "error", "-y", "-i", f, "-c:v", "copy", "-an", dest], check=True); os.remove(f)
    info = subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name,duration",
                           "-of", "csv=p=0", dest], capture_output=True, text=True).stdout.strip()
    sheet = os.path.join(a.outdir, "sheet_%s.png" % a.name)
    subprocess.run([FF, "-v", "error", "-y", "-i", dest, "-vf",
                    "fps=1/2,scale=240:-1,drawtext=fontfile=/System/Library/Fonts/HelveticaNeue.ttc:text='%{pts\\:hms}':x=5:y=5:fontsize=20:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=8x12",
                    "-frames:v", "1", sheet], check=False)
    reg = os.path.join(a.outdir, "broll.json"); d = json.load(open(reg)) if os.path.isfile(reg) else {}
    d[a.name] = {"id": a.id, "url": url, "channel": ch, "title": meta.get("title"), "duration_s": meta.get("duration"), "file": dest, "stream": info}
    json.dump(d, open(reg, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%s | %s | %s | folha %s" % (dest, ch, info, sheet))


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--channel", default=None); s.add_argument("-n", type=int, default=12)
    g = sub.add_parser("get"); g.add_argument("id"); g.add_argument("name"); g.add_argument("--outdir", required=True); g.add_argument("--channel-expected", default=None)
    a = ap.parse_args()
    (cmd_search if a.cmd == "search" else cmd_get)(a)


if __name__ == "__main__":
    main()
