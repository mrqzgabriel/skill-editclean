#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - transcribe.py

Transcreve o audio de um video com timestamps POR PALAVRA, que e o que o
sistema de legenda "pop-on" do estilo exige.

Ordem de preferencia dos backends:
  1. faster-whisper       (modulo Python; PREFERIDO - timestamp por palavra confiavel)
  2. whisper local        (whisper / whisper-cli / mlx_whisper, se instalados)
  3. OpenAI API           (modelo whisper-1, com timestamp_granularities=word)

Credencial da API, em ordem:
  1. variavel de ambiente OPENAI_API_KEY
  2. arquivo <skill>/.credentials.json (permissao 600)

O script NUNCA imprime a chave. Videos longos sao fatiados em blocos menores
que o limite de upload da API e os timestamps sao reencaixados na timeline.

Saida: JSON com {"words": [{"text","start","end"}], "language", "backend"}.

Uso:
    python3 transcribe.py "<video>" --out palavras.json [--language pt]
                          [--backend auto|local|api] [--quiet]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
CRED_PATH = os.path.join(SKILL_ROOT, ".credentials.json")

# limite da API e 25 MB; usamos blocos de ~10 min em mp3 mono 64k (~4.8 MB)
CHUNK_SECONDS = 600
API_URL = "https://api.openai.com/v1/audio/transcriptions"


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
FFPROBE = _find_bin("ffprobe")


def log(msg, quiet=False):
    if not quiet:
        sys.stderr.write("[transcribe] %s\n" % msg)


def _duration(path):
    p = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        return float(p.stdout.decode().strip())
    except ValueError:
        return 0.0


def extract_audio(video, dest, start=None, dur=None):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", "%.3f" % start]
    cmd += ["-i", video]
    if dur is not None:
        cmd += ["-t", "%.3f" % dur]
    cmd += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "64k", "-y", dest]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError("extracao de audio falhou: %s"
                           % p.stderr.decode("utf-8", "replace")[-400:])
    return dest


# --------------------------------------------------------------------------
# credencial
# --------------------------------------------------------------------------

def load_api_key():
    key = os.environ.get("OPENAI_API_KEY")
    project = os.environ.get("OPENAI_PROJECT_ID", "")
    if key:
        return key, project, "env"
    if os.path.isfile(CRED_PATH):
        try:
            with open(CRED_PATH, encoding="utf-8") as fh:
                c = json.load(fh)
            k = c.get("OPENAI_API_KEY")
            if k:
                return k, c.get("OPENAI_PROJECT_ID", ""), "skill"
        except (ValueError, OSError):
            pass
    return None, None, None


# --------------------------------------------------------------------------
# backends locais
# --------------------------------------------------------------------------

def try_local_whisper(video, language, quiet):
    """whisper CLI / whisper-cli / mlx_whisper com saida JSON e word timestamps."""
    exe = _find_bin("whisper") or _find_bin("mlx_whisper")
    if not exe:
        return None
    tmpdir = os.path.join("/tmp", "editclean_whisper_%s" % uuid.uuid4().hex[:8])
    os.makedirs(tmpdir, exist_ok=True)
    audio = extract_audio(video, os.path.join(tmpdir, "a.mp3"))
    cmd = [exe, audio, "--output_format", "json", "--output_dir", tmpdir,
           "--word_timestamps", "True"]
    if language:
        cmd += ["--language", language]
    log("tentando whisper local...", quiet)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    words = []
    for fn in os.listdir(tmpdir):
        if fn.endswith(".json"):
            with open(os.path.join(tmpdir, fn), encoding="utf-8") as fh:
                data = json.load(fh)
            for seg in data.get("segments", []):
                for w in seg.get("words", []) or []:
                    t = (w.get("word") or w.get("text") or "").strip()
                    if t:
                        words.append({"text": t,
                                      "start": float(w.get("start", 0)),
                                      "end": float(w.get("end", 0))})
            break
    shutil.rmtree(tmpdir, ignore_errors=True)
    return words or None


def try_faster_whisper(video, language, quiet):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    log("tentando faster-whisper...", quiet)
    tmpdir = os.path.join("/tmp", "editclean_fw_%s" % uuid.uuid4().hex[:8])
    os.makedirs(tmpdir, exist_ok=True)
    audio = extract_audio(video, os.path.join(tmpdir, "a.mp3"))
    try:
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _info = model.transcribe(audio, language=language, word_timestamps=True)
        words = []
        for seg in segments:
            for w in (seg.words or []):
                t = (w.word or "").strip()
                if t:
                    words.append({"text": t, "start": float(w.start), "end": float(w.end)})
        return words or None
    except Exception:
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------
# backend API
# --------------------------------------------------------------------------

def _post_multipart(url, fields, file_field, file_path, headers, timeout=600):
    """multipart/form-data com stdlib (sem requests)."""
    import urllib.request
    boundary = "----editclean%s" % uuid.uuid4().hex
    body = bytearray()

    def add(name, value):
        body.extend(("--%s\r\n" % boundary).encode())
        body.extend(('Content-Disposition: form-data; name="%s"\r\n\r\n' % name).encode())
        body.extend(("%s\r\n" % value).encode())

    for k, v in fields:
        add(k, v)

    fname = os.path.basename(file_path)
    body.extend(("--%s\r\n" % boundary).encode())
    body.extend(('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
                 % (file_field, fname)).encode())
    body.extend(b"Content-Type: audio/mpeg\r\n\r\n")
    with open(file_path, "rb") as fh:
        body.extend(fh.read())
    body.extend(b"\r\n")
    body.extend(("--%s--\r\n" % boundary).encode())

    h = dict(headers)
    h["Content-Type"] = "multipart/form-data; boundary=%s" % boundary
    req = urllib.request.Request(url, data=bytes(body), headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def try_openai_api(video, language, quiet):
    import urllib.error
    key, project, origin = load_api_key()
    if not key:
        return None, "nenhuma credencial OpenAI disponivel"
    log("usando OpenAI API (credencial: %s)" % origin, quiet)

    total = _duration(video)
    tmpdir = os.path.join("/tmp", "editclean_api_%s" % uuid.uuid4().hex[:8])
    os.makedirs(tmpdir, exist_ok=True)
    words = []
    detected_lang = language
    try:
        n_chunks = max(1, int((total + CHUNK_SECONDS - 1) // CHUNK_SECONDS))
        for i in range(n_chunks):
            offset = i * CHUNK_SECONDS
            dur = min(CHUNK_SECONDS, total - offset)
            if dur <= 0.05:
                break
            chunk = extract_audio(video, os.path.join(tmpdir, "c%02d.mp3" % i),
                                  start=offset, dur=dur)
            size_mb = os.path.getsize(chunk) / 1e6
            if size_mb > 24.5:
                return None, ("bloco de audio com %.1f MB excede o limite de 25 MB da API"
                              % size_mb)
            log("bloco %d/%d (%.1f MB)..." % (i + 1, n_chunks, size_mb), quiet)

            fields = [("model", "whisper-1"),
                      ("response_format", "verbose_json"),
                      ("timestamp_granularities[]", "word")]
            if language:
                fields.append(("language", language))
            headers = {"Authorization": "Bearer %s" % key}
            if project:
                headers["OpenAI-Project"] = project

            try:
                data = _post_multipart(API_URL, fields, "file", chunk, headers)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                return None, "API retornou HTTP %d: %s" % (exc.code, detail)
            except Exception as exc:
                return None, "falha ao chamar a API: %s" % exc

            detected_lang = data.get("language") or detected_lang
            for w in data.get("words", []) or []:
                t = (w.get("word") or "").strip()
                if not t:
                    continue
                words.append({"text": t,
                              "start": round(float(w.get("start", 0)) + offset, 3),
                              "end": round(float(w.get("end", 0)) + offset, 3)})
        return (words or None), (None if words else "a API nao devolveu palavras")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="EditClean - transcricao com timestamps por palavra")
    ap.add_argument("video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--language", default=None, help="ex: pt, en. Omitir = deteccao automatica")
    ap.add_argument("--backend", default="auto", choices=["auto", "local", "api"])
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not FFMPEG or not FFPROBE:
        sys.stderr.write("ERRO: ffmpeg/ffprobe nao encontrados\n")
        sys.exit(2)

    video = os.path.abspath(os.path.expanduser(args.video))
    if not os.path.isfile(video):
        sys.stderr.write("ERRO: video nao encontrado: %s\n" % video)
        sys.exit(2)

    words, backend, err = None, None, None

    # faster-whisper PRIMEIRO: alinhamento por palavra de verdade. A API whisper-1
    # devolve timestamps colapsados (varias palavras com o mesmo start, duracao 0)
    # que dessincronizam a legenda; so usar como ultimo recurso.
    if args.backend in ("auto", "local"):
        words = try_faster_whisper(video, args.language, args.quiet)
        if words:
            backend = "faster_whisper"
        if not words:
            words = try_local_whisper(video, args.language, args.quiet)
            if words:
                backend = "whisper_local"

    if not words and args.backend in ("auto", "api"):
        words, err = try_openai_api(video, args.language, args.quiet)
        if words:
            backend = "openai_api"

    if not words:
        sys.stderr.write("ERRO: nenhum backend de transcricao produziu resultado.\n")
        if err:
            sys.stderr.write("  motivo: %s\n" % err)
        sys.stderr.write(
            "  opcoes: exportar OPENAI_API_KEY, gravar <skill>/.credentials.json,\n"
            "          ou instalar um whisper local (pip3 install --user faster-whisper)\n")
        sys.exit(1)

    words.sort(key=lambda w: w["start"])
    result = {
        "backend": backend,
        "language": args.language or "auto",
        "n_words": len(words),
        "duration": round(_duration(video), 3),
        "words": words,
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    log("%d palavras via %s -> %s" % (len(words), backend, args.out), args.quiet)
    print(args.out)


if __name__ == "__main__":
    main()
