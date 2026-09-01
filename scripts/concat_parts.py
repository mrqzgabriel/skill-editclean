#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - concat_parts.py  (v2.7)

Video que chega EM TRECHOS (clipes de ~8 s do Veo / influencIA, partes numeradas):
corta o ar morto do FIM e do COMECO de cada trecho e junta tudo num master,
"cortadinho certinho", igual ao render do influencIA
(artifacts/api-server/src/lib/remotion-renderer.ts, normalizeTrimConcat):

  - por parte: transcricao por palavra (faster-whisper) + silencedetect(-25 dB, 0,15 s)
  - comeco: se ha silencio que comeca em < 0,05 s e termina ate 0,2 s depois da
            1a palavra -> (fim do silencio - 0,05); senao -> (1a palavra - 0,08)
  - fim:    (ultima palavra + 0,15 s). Aqui vai uma protecao a mais que o influencIA
            nao tem: se a energia AINDA nao caiu nesse ponto (o Whisper costuma
            fechar a palavra cedo), o corte anda ate o proximo silencio + 0,05,
            no maximo 0,6 s adiante -- nunca decepa silaba (regra 5 da skill).
  - sem fala: comeco do silencio final + 0,05; sem silencio: duracao - 0,5
  - --overrides: JSON por parte para o que a maquina nao pega (balbucio da voz
            gerada, ruido). Chave = nome do arquivo; "start"/"end" em segundos
            LOCAIS da parte; "skip": true descarta a parte inteira.

O script imprime a transcricao de cada parte e o avg_logprob do Whisper:
avg_logprob muito baixo (< -0,8) e sinal de BALBUCIO da voz gerada -- ouca o
trecho e use --overrides. Nunca confie so no numero.

Saida: master .mp4 (cada parte re-encodada crf 12 e o concat SEM re-encode),
mais um report JSON com o que foi decidido por parte.

Uso:
    python3 concat_parts.py parte1.mp4 parte2.mp4 ... --out master.mp4
                            [--overrides ov.json] [--scale 1080:1920]
                            [--language pt] [--model small] [--report report.json]
    python3 concat_parts.py --dir /pasta/com/partes --out master.mp4
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

NOISE_DB = -25.0          # influencIA: detectSilence(wav, -25, 0.15)
MIN_SILENCE_S = 0.15
LEAD_PAD = 0.05           # comeco = fim do silencio inicial - 0,05
LEAD_NO_SIL = 0.08        # sem silencio inicial: 1a palavra - 0,08
TAIL_PAD = 0.15           # fim = ultima palavra + 0,15
TAIL_EXTEND_MAX = 0.60    # protecao extra: estende ate o silencio, no maximo isso
NOSPEECH_TRAIL = 0.05
NOSPEECH_FALLBACK = 0.50
BABBLE_LOGPROB = -0.80    # abaixo disso: provavel balbucio, avisar


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


def log(msg):
    sys.stderr.write("[partes] %s\n" % msg)


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def probe(path):
    rc, out, _ = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                      "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
                      "-show_entries", "format=duration", "-of", "json", path])
    if rc != 0:
        raise SystemExit("ffprobe falhou em %s" % path)
    d = json.loads(out)
    st = (d.get("streams") or [{}])[0]
    num, den = (st.get("r_frame_rate") or "30/1").split("/")
    fps = float(num) / float(den or 1)
    return {"width": int(st.get("width") or 0), "height": int(st.get("height") or 0),
            "fps": fps, "duration": float(d["format"]["duration"])}


def natural_key(path):
    """parte10 depois de parte9, nao entre parte1 e parte2."""
    base = os.path.basename(path)
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", base)]


def extract_wav(video, dest):
    rc, _, err = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", video,
                      "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", dest])
    if rc != 0:
        raise SystemExit("ffmpeg (wav) falhou: %s" % err.strip()[-300:])


def detect_silence(wav, noise_db=NOISE_DB, min_dur=MIN_SILENCE_S):
    """Mesma leitura do influencIA: silence_start/silence_end do silencedetect;
    silencio sem fim = vai ate o final do arquivo (end = inf)."""
    rc, _, err = run([FFMPEG, "-hide_banner", "-nostats", "-i", wav, "-af",
                      "silencedetect=noise=%sdB:d=%s" % (noise_db, min_dur), "-f", "null", "-"])
    sil, cur = [], None
    for line in err.splitlines():
        m = re.search(r"silence_start:\s*([\d.]+)", line)
        if m:
            cur = float(m.group(1))
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m and cur is not None:
            sil.append({"start": cur, "end": float(m.group(1))})
            cur = None
    if cur is not None:
        sil.append({"start": cur, "end": float("inf")})
    return sil


def transcribe(wav, language, model_size):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("faster-whisper nao instalado: pip3 install --user faster-whisper")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segs, _ = model.transcribe(wav, language=language, word_timestamps=True,
                               beam_size=5, vad_filter=False,
                               condition_on_previous_text=False)
    words, texts, lp_num, lp_den = [], [], 0.0, 0.0
    for s in segs:
        texts.append(s.text.strip())
        d = max(0.05, float(s.end) - float(s.start))
        lp_num += float(s.avg_logprob) * d
        lp_den += d
        for w in (s.words or []):
            t = w.word.strip()
            if t:
                words.append({"text": t, "start": float(w.start), "end": float(w.end)})
    return {"words": words, "text": " ".join(texts).strip(),
            "avg_logprob": (lp_num / lp_den) if lp_den else None}


def decide_cut(duration, words, silences):
    """Regra do influencIA + protecao do fim. Devolve (start, end, detalhe)."""
    if words:
        first, last = words[0], words[-1]
        lead = next((s for s in silences if s["start"] < 0.05 and s["end"] <= first["start"] + 0.2), None)
        start = max(lead["end"] - LEAD_PAD, 0.0) if lead else max(first["start"] - LEAD_NO_SIL, 0.0)
        end = min(last["end"] + TAIL_PAD, duration)
        detail = "whisper %.2f-%.2f -> %.2f-%.2f" % (first["start"], last["end"], start, end)
        # protecao: se em `end` a energia ainda nao caiu, anda ate o silencio seguinte
        inside = any(s["start"] <= end <= s["end"] for s in silences)
        if not inside:
            nxt = [s for s in silences if last["end"] - 0.10 <= s["start"] <= last["end"] + TAIL_EXTEND_MAX]
            if nxt:
                end2 = min(nxt[0]["start"] + NOSPEECH_TRAIL, duration)
                if end2 > end:
                    detail += " | fala continuava, fim -> %.2f (silencio em %.2f)" % (end2, nxt[0]["start"])
                    end = end2
            else:
                detail += " | AVISO: sem silencio medido apos a ultima palavra"
        return start, end, detail
    trailing = None
    for s in reversed(silences):
        if s["end"] == float("inf") or s["end"] >= duration - 0.15:
            trailing = s
            break
    if trailing:
        return 0.0, min(trailing["start"] + NOSPEECH_TRAIL, duration), \
            "sem fala | silencio final em %.2f" % trailing["start"]
    return 0.0, max(duration - NOSPEECH_FALLBACK, 0.1), "sem fala, sem silencio final, fallback -0,5 s"


def encode_segment(src, dest, start, end, fps, scale=None):
    dur = end - start
    af = "afade=t=in:st=0:d=0.012,afade=t=out:st=%.4f:d=0.012" % max(0.0, dur - 0.012)
    vf = ["scale=%s:flags=lanczos" % scale] if scale else []
    vf.append("setsar=1")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
           "-ss", "%.4f" % start, "-i", src, "-t", "%.4f" % dur,
           "-vf", ",".join(vf), "-af", af,
           "-r", "%g" % fps, "-c:v", "libx264", "-crf", "12", "-preset", "slow",
           "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           "-video_track_timescale", "90000", "-movflags", "+faststart", dest]
    rc, _, err = run(cmd)
    if rc != 0:
        raise SystemExit("ffmpeg (trecho) falhou em %s: %s" % (src, err.strip()[-400:]))


def main():
    ap = argparse.ArgumentParser(description="Corta o ar morto de cada trecho e junta num master")
    ap.add_argument("parts", nargs="*", help="arquivos das partes (ordem natural pelo numero no nome)")
    ap.add_argument("--dir", default=None, help="pasta com as partes")
    ap.add_argument("--pattern", default="parte*.mp4",
                    help="glob dentro de --dir (padrao parte*.mp4; a pasta costuma ter masters junto)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--overrides", default=None, help="JSON {\"parte9.mp4\": {\"end\": 1.53}, ...}")
    ap.add_argument("--scale", default=None, help="ex: 1080:1920 (lanczos) no mesmo encode")
    ap.add_argument("--language", default="pt")
    ap.add_argument("--model", default="small")
    ap.add_argument("--report", default=None)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    if not FFMPEG or not FFPROBE:
        raise SystemExit("ffmpeg/ffprobe nao encontrados")
    parts = list(args.parts)
    if args.dir:
        parts += glob.glob(os.path.join(args.dir, args.pattern))
    parts = sorted({os.path.abspath(p) for p in parts}, key=natural_key)
    if not parts:
        raise SystemExit("nenhuma parte informada")
    if os.path.exists(args.out) and not args.overwrite:
        raise SystemExit("saida ja existe (use --overwrite): %s" % args.out)
    overrides = {}
    if args.overrides:
        overrides = json.load(open(args.overrides, encoding="utf-8"))

    tmp = tempfile.mkdtemp(prefix="editclean-partes-")
    report, seg_files, fps_ref = [], [], None
    log("%d parte(s)" % len(parts))
    for i, src in enumerate(parts):
        base = os.path.basename(src)
        info = probe(src)
        fps_ref = fps_ref or info["fps"]
        ov = overrides.get(base, {})
        entry = {"index": i, "file": src, "duration": round(info["duration"], 3)}
        if ov.get("skip"):
            entry.update({"skipped": True, "detail": "descartada por override"})
            report.append(entry)
            log("%s: DESCARTADA (override)" % base)
            continue
        wav = os.path.join(tmp, "p%02d.wav" % i)
        extract_wav(src, wav)
        silences = detect_silence(wav)
        tr = transcribe(wav, args.language, args.model)
        start, end, detail = decide_cut(info["duration"], tr["words"], silences)
        if "start" in ov:
            start, detail = float(ov["start"]), detail + " | start por override=%.2f" % float(ov["start"])
        if "end" in ov:
            end, detail = float(ov["end"]), detail + " | end por override=%.2f" % float(ov["end"])
        start = max(0.0, min(start, info["duration"] - 0.1))
        end = max(start + 0.1, min(end, info["duration"]))
        warn = []
        if tr["avg_logprob"] is not None and tr["avg_logprob"] < BABBLE_LOGPROB:
            warn.append("avg_logprob %.2f: PROVAVEL BALBUCIO/RUIDO -- ouca e use --overrides" % tr["avg_logprob"])
        if "AVISO" in detail:
            warn.append("sem silencio apos a ultima palavra; conferir o fim")
        entry.update({"start": round(start, 4), "end": round(end, 4), "kept": round(end - start, 4),
                      "removed_tail": round(info["duration"] - end, 4), "removed_head": round(start, 4),
                      "detail": detail, "text": tr["text"], "avg_logprob": tr["avg_logprob"],
                      "silences": [{"start": round(s["start"], 3),
                                    "end": (None if s["end"] == float("inf") else round(s["end"], 3))}
                                   for s in silences],
                      "warnings": warn})
        report.append(entry)
        log("%s: %.2f-%.2f (mantem %.2fs, tira %.2fs do fim) | %s" %
            (base, start, end, end - start, info["duration"] - end, detail))
        log("   texto: %s" % (tr["text"] or "(sem fala)"))
        for w in warn:
            log("   !! " + w)
        seg = os.path.join(tmp, "seg%02d.mp4" % i)
        encode_segment(src, seg, start, end, fps_ref, args.scale)
        seg_files.append(seg)

    if not seg_files:
        raise SystemExit("nenhuma parte sobrou")
    lst = os.path.join(tmp, "lista.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for s in seg_files:
            fh.write("file '%s'\n" % s.replace("'", r"'\''"))
    rc, _, err = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                      "-i", lst, "-c", "copy", "-movflags", "+faststart", args.out])
    if rc != 0:
        raise SystemExit("ffmpeg (concat) falhou: %s" % err.strip()[-400:])
    total = probe(args.out)["duration"]
    orig = sum(e["duration"] for e in report)
    summary = {"parts": report, "output": os.path.abspath(args.out), "fps": fps_ref,
               "duration_in": round(orig, 3), "duration_out": round(total, 3),
               "removed": round(orig - total, 3),
               "rule": "influencIA normalizeTrimConcat: silencedetect -25dB/0.15s; inicio = fim do "
                       "silencio inicial - 0.05 (ou 1a palavra - 0.08); fim = ultima palavra + 0.15, "
                       "estendido ate o proximo silencio + 0.05 se a fala continuava"}
    if args.report:
        json.dump(summary, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    shutil.rmtree(tmp, ignore_errors=True)
    log("master: %s  (%.2fs -> %.2fs, removido %.2fs)" % (args.out, orig, total, orig - total))
    print(os.path.abspath(args.out))


if __name__ == "__main__":
    main()
