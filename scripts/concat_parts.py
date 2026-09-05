#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - concat_parts.py  (v3.0)

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

Saida: master .mp4 (v3.5: UMA passagem com o filtro concat, corte no grid de quadros, audio continuo),
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
# v3.3 (04/09, "o comeco ta esquisito" / "audio dessincronizado no fim")
SIL_MERGE_GAP = 0.08      # silencios separados por menos que isso sao UM silencio
LEAD_SIL_START = 0.20     # silencio que comeca antes disso conta como ar morto do inicio
FALSE_START_MAX = 0.25    # 1a emissao mais curta que isso...
FALSE_START_GAP = 0.35    # ...seguida de pausa maior que isso = falso comeco
TAIL_CLAMP = 0.28         # nunca deixar mais que isso de video depois que a energia cai
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


def merge_silences(silences, gap=SIL_MERGE_GAP, duration=None):
    """Junta silencios separados por menos que `gap` (um clique de 11 ms entre dois
    silencios fazia o ar morto do inicio passar despercebido)."""
    out = []
    for s in sorted(silences, key=lambda x: x["start"]):
        e = duration if (s["end"] == float("inf") and duration) else s["end"]
        if out and s["start"] - out[-1]["end"] <= gap:
            out[-1]["end"] = max(out[-1]["end"], e)
        else:
            out.append({"start": s["start"], "end": e})
    return out


def decide_cut(duration, words, silences, is_last=False, false_start=True):
    """Regra do influencIA + protecao do fim. Devolve (start, end, detalhe)."""
    sil = merge_silences(silences, duration=duration)
    if words:
        first, last = words[0], words[-1]
        detail = "whisper %.2f-%.2f" % (first["start"], last["end"])

        # ---- COMECO (v3.3) ----
        # O whisper costuma cravar a 1a palavra em 0,00 mesmo quando a fala so
        # comeca depois; quem sabe a verdade e o silencio MEDIDO. Antes a regra
        # exigia silencio comecando em < 0,05 s e o ar morto passava batido.
        lead = next((x for x in sil if x["start"] < LEAD_SIL_START
                     and x["end"] > first["start"] + 0.02), None)
        if lead:
            start = max(lead["end"] - LEAD_PAD, 0.0)
            detail += " | inicio pelo silencio medido (ar morto ate %.2f)" % lead["end"]
        else:
            start = max(first["start"] - LEAD_NO_SIL, 0.0)

        # falso comeco: silaba solta e curta + pausa longa ("A ....... Anthropic")
        if false_start:
            nxt = next((x for x in sil if x["start"] >= start), None)
            if (nxt and nxt["start"] - start <= FALSE_START_MAX
                    and (nxt["end"] - nxt["start"]) >= FALSE_START_GAP and nxt["end"] < duration - 0.5):
                detail += " | FALSO COMECO: silaba de %.2fs + pausa de %.2fs cortadas" % (
                    nxt["start"] - start, nxt["end"] - nxt["start"])
                start = max(nxt["end"] - LEAD_PAD, 0.0)

        # ---- FIM ----
        end = min(last["end"] + TAIL_PAD, duration)
        # protecao: se em `end` a energia ainda nao caiu, anda ate o silencio seguinte
        inside = any(x["start"] <= end <= x["end"] for x in sil)
        if not inside:
            nx = [x for x in sil if last["end"] - 0.10 <= x["start"] <= last["end"] + TAIL_EXTEND_MAX]
            if nx:
                end2 = min(nx[0]["start"] + NOSPEECH_TRAIL, duration)
                if end2 > end:
                    detail += " | fala continuava, fim -> %.2f (silencio em %.2f)" % (end2, nx[0]["start"])
                    end = end2
            else:
                detail += " | AVISO: sem silencio medido apos a ultima palavra"
        # v3.3: o timestamp da ULTIMA palavra costuma esticar ate 0,5 s alem do audio
        # real. Sem trava, a ultima parte ficava com ~1 s de boca mexendo em silencio
        # digital ("audio dessincronizado no fim"). Corta pelo silencio medido.
        tail_sil = next((x for x in sil if x["start"] >= last["start"]
                         and x["end"] >= duration - 0.20), None)
        if tail_sil and end > tail_sil["start"] + TAIL_CLAMP:
            detail += " | fim travado no silencio medido (%.2f -> %.2f)" % (
                end, tail_sil["start"] + TAIL_CLAMP)
            end = tail_sil["start"] + TAIL_CLAMP
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


def _snap(start, end, fps, duration):
    """v3.5 (04/09/2026): fronteiras no GRID DE QUADROS. Com '-ss/-t' em tempo livre, o video saia
    arredondado para cima (corte de 6,690 s virava 161 quadros = 6,708 s) e o audio ficava exato;
    a juncao alinhava a peca seguinte pelo video e sobrava um buraco no audio em cada fronteira."""
    s = round(start * fps) / fps
    last = int(duration * fps + 1e-6) / fps
    e = min(round(end * fps) / fps, last)
    if e - s < 2.0 / fps:
        e = min(s + 2.0 / fps, last)
    return s, e


def _build_master(cuts, out, fps, scale):
    """v3.5: video e audio decodificados, cortados no grid de quadros, concatenados como fluxos
    CONTINUOS pelo filtro concat e encodados UMA vez, com o audio de cada parte RECARIMBADO
    (ver comentario no loop). Antes: '-ss/-t' por peca + '-f concat -c copy' preservava o salto
    falso de timestamp que cada parte do influencIA traz (~80 ms a ~5,1 s); o atrim do render,
    que corta por timestamp, perdia ~80 ms de audio em cada parte e a voz adiantava em degraus
    (+0,42 s no fim do GPT-6 Astra). Regra 18 do SKILL.md."""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y"]
    for src, _, _ in cuts:
        cmd += ["-i", src]
    parts, labels = [], ""
    for k, (src, s, e) in enumerate(cuts):
        d = e - s
        vf = ["trim=start=%.6f:end=%.6f" % (s, e), "setpts=PTS-STARTPTS"]
        if scale:
            vf.append("scale=%s:flags=lanczos" % scale)
        vf += ["setsar=1", "fps=%g" % fps, "format=yuv420p"]
        parts.append("[%d:v]%s[v%d]" % (k, ",".join(vf), k))
        # v3.5 (04/09/2026): as PARTES do influencIA chegam com um SALTO FALSO de timestamp no
        # audio a ~5,1 s de cada clipe (372 pacotes AAC = 7,915 s de amostras continuas num fluxo
        # carimbado com 8,016 s). Medido com lipsync por metade: o audio corrido por amostras casa
        # com a boca (-0,04/-0,04 s); honrar o timestamp (silencio no salto) desalinha a 2a metade
        # (ate -0,42 s). Entao: recarimbar CONTINUO a partir de 0 (asetpts=N/SR/TB) ANTES do atrim,
        # e completar com silencio so no FIM (apad) para o audio ter exatamente a duracao do video.
        af = ["asetpts=N/SR/TB",
              "atrim=start=%.6f:end=%.6f" % (s, e), "asetpts=PTS-STARTPTS",
              "aresample=48000", "aformat=sample_fmts=fltp:channel_layouts=stereo",
              "apad=whole_dur=%.6f" % d, "atrim=end=%.6f" % d,
              "afade=t=in:st=0:d=0.012", "afade=t=out:st=%.6f:d=0.012" % max(0.0, d - 0.012)]
        parts.append("[%d:a]%s[a%d]" % (k, ",".join(af), k))
        labels += "[v%d][a%d]" % (k, k)
    parts.append("%sconcat=n=%d:v=1:a=1[v][a]" % (labels, len(cuts)))
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
            "-r", "%g" % fps, "-c:v", "libx264", "-crf", "12", "-preset", "slow",
            "-pix_fmt", "yuv420p", "-profile:v", "high",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
            "-video_track_timescale", "90000", "-movflags", "+faststart", out]
    rc, _, err = run(cmd)
    if rc != 0:
        raise SystemExit("ffmpeg (master) falhou: %s" % err.strip()[-600:])


def _verify_master(out, fps):
    """Trava do v3.5: recusa master cujo audio DECODIFICADO nao tem a mesma duracao do video.
    Conta amostras decodificadas (s16le mono) -- duracao de pacote no MP4 nao serve: o muxer
    'estica' o pacote anterior a um buraco e a soma das duracoes bate com o span mesmo faltando
    0,6 s de amostras (foi assim que o GPT-6 Astra passou). Tambem lista pacotes esticados."""
    rc, o, _ = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=nb_frames", "-of", "csv=p=0", out])
    nb = int((o.strip().split(",") or ["0"])[0] or 0)
    vdur = nb / fps
    p = subprocess.run([FFMPEG, "-v", "error", "-i", out, "-vn", "-ac", "1", "-ar", "48000",
                        "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    samples = len(p.stdout) / 2.0 / 48000.0
    rc, o, _ = run([FFPROBE, "-v", "error", "-select_streams", "a:0",
                    "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", out])
    stretched = []
    for line in o.strip().splitlines():
        f = [x for x in line.split(",") if x != ""]
        if len(f) >= 2 and float(f[1]) > 1.5 * 1024.0 / 48000.0:
            stretched.append((round(float(f[0]), 3), round(float(f[1]), 4)))
    diff = samples - vdur
    log("master A/V: video %d quadros = %.3f s | audio decodificado %.3f s | diferenca %+.3f s | pacotes esticados %d"
        % (nb, vdur, samples, diff, len(stretched)))
    if stretched or abs(diff) > 0.05:
        raise SystemExit("master com A/V desalinhado (audio - video = %+.3f s; %d pacote(s) esticado(s) %s). "
                         "Isso dessincroniza a voz no render; nao siga." % (diff, len(stretched), stretched[:6]))
    return {"video_s": round(vdur, 3), "audio_decoded_s": round(samples, 3), "diff_s": round(diff, 3),
            "stretched_packets": len(stretched)}


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
    ap.add_argument("--no-false-start", action="store_true",
                    help="nao cortar silaba solta + pausa longa no comeco da parte")
    ap.add_argument("--last-tail-extra", type=float, default=0.0,
                    help="segundos a MAIS depois da ultima palavra so na ULTIMA parte, para o fade "
                         "de encerramento nao apagar a fala (v2.8: use ~1.4 quando closing.fade_out)")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--include-backups", action="store_true",
                    help="incluir parteN_vK_*.mp4 (por padrao backups do fix sao ignorados)")
    args = ap.parse_args()

    if not FFMPEG or not FFPROBE:
        raise SystemExit("ffmpeg/ffprobe nao encontrados")
    parts = list(args.parts)
    if args.dir:
        found = glob.glob(os.path.join(args.dir, args.pattern))
        # v3.0: backups do influencia_fix_part (parteN_v1_<tag>.mp4) ficam na MESMA pasta e o
        # glob parte*.mp4 os pegava -> trechos duplicados no master (aconteceu 01/09). So entram
        # arquivos <prefixo><numero>.mp4; o resto e listado e ignorado.
        keep, skipped = [], []
        for f in found:
            bn = os.path.basename(f)
            if re.search(r"_v\d+", bn) or re.search(r"_(bak|old|backup)", bn, re.I):
                skipped.append(bn)
            else:
                keep.append(f)
        if skipped and not args.include_backups:
            log("ignorando %d backup(s): %s" % (len(skipped), ", ".join(sorted(skipped))))
            parts += keep
        else:
            parts += found
    parts = sorted({os.path.abspath(p) for p in parts}, key=natural_key)
    if not parts:
        raise SystemExit("nenhuma parte informada")
    nums = [re.findall(r"(\d+)", os.path.basename(p)) for p in parts]
    seen = {}
    for p, n in zip(parts, nums):
        key = n[0] if n else os.path.basename(p)
        if key in seen:
            raise SystemExit("duas partes com o mesmo numero (%s): %s e %s -- tire o backup da pasta ou use --include-backups"
                             % (key, os.path.basename(seen[key]), os.path.basename(p)))
        seen[key] = p
    log("partes: " + ", ".join(os.path.basename(p) for p in parts))
    if os.path.exists(args.out) and not args.overwrite:
        raise SystemExit("saida ja existe (use --overwrite): %s" % args.out)
    overrides = {}
    if args.overrides:
        overrides = json.load(open(args.overrides, encoding="utf-8"))

    tmp = tempfile.mkdtemp(prefix="editclean-partes-")
    report, cuts, fps_ref = [], [], None
    kept_idx = [i for i, p in enumerate(parts) if not overrides.get(os.path.basename(p), {}).get("skip")]
    last_idx = kept_idx[-1] if kept_idx else -1
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
        start, end, detail = decide_cut(info["duration"], tr["words"], silences,
                                        is_last=(i == last_idx), false_start=not args.no_false_start)
        if "start" in ov:
            start, detail = float(ov["start"]), detail + " | start por override=%.2f" % float(ov["start"])
        if "end" in ov:
            end, detail = float(ov["end"]), detail + " | end por override=%.2f" % float(ov["end"])
        if i == last_idx and args.last_tail_extra > 0:
            end2 = min(info["duration"], end + args.last_tail_extra)
            detail += " | cauda +%.2fs para o fade de encerramento" % (end2 - end)
            end = end2
        start = max(0.0, min(start, info["duration"] - 0.1))
        end = max(start + 0.1, min(end, info["duration"]))
        start, end = _snap(start, end, fps_ref, info["duration"])   # v3.5: grid de quadros
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
        cuts.append((src, start, end))

    if not cuts:
        raise SystemExit("nenhuma parte sobrou")
    _build_master(cuts, args.out, fps_ref, args.scale)
    av_check = _verify_master(args.out, fps_ref)
    total = probe(args.out)["duration"]
    orig = sum(e["duration"] for e in report)
    summary = {"parts": report, "output": os.path.abspath(args.out), "fps": fps_ref, "av_check": av_check,
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
