#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - analyze_video.py

Analisa um video de entrada com ffprobe/ffmpeg e produz um MANIFESTO JSON
com sinais objetivos (metadados, cenas, silencios, transientes, movimento,
nitidez, frames pretos, congelamentos) + frames de evidencia extraidos.

Este script NAO toma decisoes esteticas. Ele so mede. As decisoes de edicao
sao do Claude, a partir deste manifesto + style-profile.json.

O arquivo de entrada e tratado como SOMENTE LEITURA.

Uso:
    python3 analyze_video.py "<input>" --outdir "<dir>" [--max-frames N] [--quiet]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys


# --------------------------------------------------------------------------
# localizacao de binarios
# --------------------------------------------------------------------------

def _find_bin(name):
    """Procura o binario no PATH e em locais conhecidos do usuario."""
    p = shutil.which(name)
    if p:
        return p
    for cand in (
        os.path.expanduser(f"~/.local/tools/{name}"),
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


FFMPEG = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")


def _require_bins():
    missing = []
    if not FFMPEG:
        missing.append("ffmpeg")
    if not FFPROBE:
        missing.append("ffprobe")
    if missing:
        sys.stderr.write(
            "ERRO: dependencia ausente: %s\n"
            "Instale com Homebrew:  brew install ffmpeg\n"
            "Ou baixe um binario estatico para ~/.local/tools/\n" % ", ".join(missing)
        )
        sys.exit(2)


def run(cmd, timeout=None):
    """Executa e devolve (returncode, stdout, stderr)."""
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
    )
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


# --------------------------------------------------------------------------
# 1. metadados
# --------------------------------------------------------------------------

def probe(path):
    rc, out, err = run([
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", path,
    ])
    if rc != 0:
        raise RuntimeError("ffprobe falhou: %s" % err.strip())
    return json.loads(out)


def _parse_rate(s):
    """'30000/1001' -> 29.97"""
    if not s:
        return None
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            a, b = float(a), float(b)
        except ValueError:
            return None
        return (a / b) if b else None
    try:
        return float(s)
    except ValueError:
        return None


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def build_metadata(raw, path):
    vstreams = [s for s in raw.get("streams", []) if s.get("codec_type") == "video"]
    astreams = [s for s in raw.get("streams", []) if s.get("codec_type") == "audio"]
    if not vstreams:
        raise RuntimeError("nenhum stream de video encontrado")

    v = vstreams[0]
    a = astreams[0] if astreams else None
    fmt = raw.get("format", {})

    w = int(v.get("width") or 0)
    h = int(v.get("height") or 0)

    # rotacao (side data ou tag)
    rotation = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rotation = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    if not rotation:
        try:
            rotation = int(float(v.get("tags", {}).get("rotate", 0)))
        except (TypeError, ValueError):
            rotation = 0
    # dimensoes efetivas apos rotacao
    disp_w, disp_h = (h, w) if abs(rotation) % 180 == 90 else (w, h)

    duration = None
    for src in (v.get("duration"), fmt.get("duration")):
        if src:
            try:
                duration = float(src)
                break
            except (TypeError, ValueError):
                pass

    r_fps = _parse_rate(v.get("r_frame_rate"))
    avg_fps = _parse_rate(v.get("avg_frame_rate"))
    fps = avg_fps or r_fps or 30.0

    nb_frames = v.get("nb_frames")
    try:
        nb_frames = int(nb_frames)
    except (TypeError, ValueError):
        nb_frames = int(round(duration * fps)) if (duration and fps) else None

    g = _gcd(disp_w, disp_h) or 1
    aspect = "%d:%d" % (disp_w // g, disp_h // g)

    return {
        "path": os.path.abspath(path),
        "filename": os.path.basename(path),
        "size_bytes": int(fmt.get("size") or os.path.getsize(path)),
        "container": fmt.get("format_name"),
        "duration": duration,
        "bit_rate": int(fmt.get("bit_rate")) if fmt.get("bit_rate") else None,
        "video": {
            "codec": v.get("codec_name"),
            "profile": v.get("profile"),
            "width": w,
            "height": h,
            "display_width": disp_w,
            "display_height": disp_h,
            "aspect": aspect,
            "sample_aspect_ratio": v.get("sample_aspect_ratio"),
            "display_aspect_ratio": v.get("display_aspect_ratio"),
            "pix_fmt": v.get("pix_fmt"),
            "fps": round(fps, 6),
            "r_frame_rate": v.get("r_frame_rate"),
            "avg_frame_rate": v.get("avg_frame_rate"),
            "time_base": v.get("time_base"),
            "nb_frames": nb_frames,
            "rotation": rotation,
            "color_space": v.get("color_space"),
            "color_primaries": v.get("color_primaries"),
            "color_transfer": v.get("color_transfer"),
            "color_range": v.get("color_range"),
            "field_order": v.get("field_order", "progressive"),
            "vfr_suspected": bool(
                r_fps and avg_fps and abs(r_fps - avg_fps) > 0.01
            ),
        },
        "audio": ({
            "codec": a.get("codec_name"),
            "sample_rate": int(a.get("sample_rate")) if a.get("sample_rate") else None,
            "channels": a.get("channels"),
            "channel_layout": a.get("channel_layout"),
            "bit_rate": int(a.get("bit_rate")) if a.get("bit_rate") else None,
            "duration": float(a["duration"]) if a.get("duration") else None,
        } if a else None),
        "has_audio": a is not None,
    }


# --------------------------------------------------------------------------
# 2. deteccoes por filtro ffmpeg
# --------------------------------------------------------------------------

def detect_scenes(path, threshold=0.22):
    """scdet -> lista de cortes provaveis com score."""
    rc, out, err = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", path,
        "-vf", "scdet=threshold=%.4f" % (threshold * 100.0),
        "-an", "-f", "null", "-",
    ])
    scenes = []
    for m in re.finditer(
        r"lavfi\.scd\.score:\s*([0-9.]+).*?lavfi\.scd\.time:\s*([0-9.]+)", err, re.S
    ):
        scenes.append({"time": float(m.group(2)), "score": float(m.group(1))})
    if not scenes:
        for m in re.finditer(r"scene.*?score:\s*([0-9.]+).*?time:\s*([0-9.]+)", err):
            scenes.append({"time": float(m.group(2)), "score": float(m.group(1))})
    scenes.sort(key=lambda s: s["time"])
    # dedup de eventos muito proximos (< 200ms)
    dedup = []
    for s in scenes:
        if dedup and (s["time"] - dedup[-1]["time"]) < 0.2:
            if s["score"] > dedup[-1]["score"]:
                dedup[-1] = s
            continue
        dedup.append(s)
    return dedup


def detect_silences(path, noise_db=-32.0, min_dur=0.30):
    rc, out, err = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", path,
        "-af", "silencedetect=noise=%ddB:d=%.3f" % (int(noise_db), min_dur),
        "-vn", "-f", "null", "-",
    ])
    silences, cur = [], None
    for m in re.finditer(
        r"silence_start:\s*(-?[0-9.]+)|silence_end:\s*(-?[0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)",
        err,
    ):
        if m.group(1) is not None:
            cur = max(0.0, float(m.group(1)))
        elif m.group(2) is not None and cur is not None:
            end = float(m.group(2))
            silences.append({
                "start": round(cur, 4),
                "end": round(end, 4),
                "duration": round(float(m.group(3)), 4),
            })
            cur = None
    return silences


def detect_black(path, min_dur=0.10):
    rc, out, err = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", path,
        "-vf", "blackdetect=d=%.3f:pic_th=0.98" % min_dur,
        "-an", "-f", "null", "-",
    ])
    return [
        {"start": float(m.group(1)), "end": float(m.group(2)), "duration": float(m.group(3))}
        for m in re.finditer(
            r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)", err
        )
    ]


def detect_freeze(path, min_dur=0.7):
    rc, out, err = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", path,
        "-vf", "freezedetect=n=-60dB:d=%.2f" % min_dur,
        "-an", "-f", "null", "-",
    ])
    freezes, cur = [], None
    for m in re.finditer(
        r"freeze_start:\s*([0-9.]+)|freeze_end:\s*([0-9.]+)", err
    ):
        if m.group(1) is not None:
            cur = float(m.group(1))
        elif m.group(2) is not None and cur is not None:
            freezes.append({"start": cur, "end": float(m.group(2)),
                            "duration": round(float(m.group(2)) - cur, 4)})
            cur = None
    return freezes


def _parse_metadata_stream(stderr_text, key_regex):
    """
    Le a saida do filtro metadata=print, que emite pares de linhas:
        frame:N  pts:X  pts_time:T
        lavfi.<chave>=<valor>
    Importante: nunca usar setpts junto com select nessas cadeias -- setpts
    renumeraria o tempo e os timestamps deixariam de corresponder ao original.
    """
    out, cur_t = [], None
    for line in stderr_text.splitlines():
        m = re.search(r"pts_time:(-?[0-9.]+)", line)
        if m:
            try:
                cur_t = float(m.group(1))
            except ValueError:
                cur_t = None
            continue
        m = re.search(key_regex, line)
        if m and cur_t is not None:
            try:
                out.append((cur_t, float(m.group(1))))
            except ValueError:
                pass
            cur_t = None
    return out


def sample_motion(path, duration, fps, max_samples=900):
    """signalstats YDIF por frame -> proxy de movimento, subamostrado."""
    step = 1
    if duration and fps:
        total = duration * fps
        if total > max_samples:
            step = max(1, int(total / max_samples))
    vf = "signalstats,metadata=print"
    if step > 1:
        # sem setpts: preserva o pts_time real dos frames selecionados
        vf = "select='not(mod(n\\,%d))'," % step + vf
    rc, out, err = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", path,
        "-vf", vf, "-an", "-f", "null", "-",
    ])
    pairs = _parse_metadata_stream(err, r"lavfi\.signalstats\.YDIF=([0-9.]+)")
    return [{"t": round(t, 3), "ydif": round(v, 4)} for t, v in pairs], step


def sample_blur(path, duration, fps, max_samples=160):
    """blurdetect em amostras espacadas -> pontos de baixa nitidez."""
    if not duration or duration <= 0:
        return []
    total_frames = max(1, int(duration * (fps or 30.0)))
    step = max(1, int(total_frames / max_samples))
    vf = "blurdetect,metadata=print"
    if step > 1:
        vf = "select='not(mod(n\\,%d))'," % step + vf
    rc, out, err = run([
        FFMPEG, "-hide_banner", "-nostats", "-i", path,
        "-vf", vf, "-an", "-f", "null", "-",
    ])
    pairs = _parse_metadata_stream(err, r"lavfi\.blur=([0-9.]+)")
    return [{"t": round(t, 3), "blur": round(v, 4)} for t, v in pairs]


def audio_transients(path, duration, has_audio, win_s=0.05):
    """
    Envelope RMS lido direto do PCM decodificado (mono 8 kHz).
    Ler PCM e mais robusto do que parsear metadados do filtro astats,
    cujas chaves variam entre versoes do ffmpeg.
    """
    if not has_audio or not duration:
        return {"rms": [], "transients": [], "window_s": win_s}

    sr = 8000
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", path,
         "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    data = proc.stdout
    if not data:
        return {"rms": [], "transients": [], "window_s": win_s}

    import array as _array
    import math as _math
    samples = _array.array("h")
    samples.frombytes(data[: len(data) // 2 * 2])

    win = max(1, int(sr * win_s))
    rms = []
    for i in range(len(samples) // win):
        seg = samples[i * win:(i + 1) * win]
        acc = 0
        for x in seg:
            acc += x * x
        r = _math.sqrt(acc / len(seg)) / 32768.0
        db = 20.0 * _math.log10(r + 1e-9)
        rms.append({"t": round(i * win_s, 3), "db": round(db, 2)})

    transients = []
    for i in range(1, len(rms)):
        rise = rms[i]["db"] - rms[i - 1]["db"]
        if rise >= 8.0 and rms[i]["db"] > -45.0:
            if not transients or (rms[i]["t"] - transients[-1]["t"]) > 0.12:
                transients.append({"t": rms[i]["t"], "rise_db": round(rise, 2)})
    return {"rms": rms, "transients": transients, "window_s": win_s}


# --------------------------------------------------------------------------
# 3. derivacoes
# --------------------------------------------------------------------------

def build_shots(scenes, duration):
    """Converte cortes detectados em planos (shots)."""
    bounds = [0.0] + [s["time"] for s in scenes if 0.05 < s["time"] < duration - 0.05]
    bounds.append(duration)
    shots = []
    for i in range(len(bounds) - 1):
        st, en = bounds[i], bounds[i + 1]
        if en - st < 0.05:
            continue
        shots.append({
            "id": "SH%03d" % (len(shots) + 1),
            "start": round(st, 4),
            "end": round(en, 4),
            "duration": round(en - st, 4),
        })
    return shots


def motion_intervals(samples, hi_percentile=0.80):
    """Trechos com movimento acima do percentil."""
    if not samples:
        return []
    vals = sorted(s["ydif"] for s in samples)
    thr = vals[int(len(vals) * hi_percentile)] if len(vals) > 4 else (vals[-1] if vals else 0)
    out, cur = [], None
    for s in samples:
        if s["ydif"] >= thr and thr > 0:
            if cur is None:
                cur = {"start": s["t"], "end": s["t"], "peak": s["ydif"]}
            else:
                cur["end"] = s["t"]
                cur["peak"] = max(cur["peak"], s["ydif"])
        elif cur is not None:
            if cur["end"] - cur["start"] >= 0.15:
                out.append({k: round(v, 4) for k, v in cur.items()})
            cur = None
    if cur is not None and cur["end"] - cur["start"] >= 0.15:
        out.append({k: round(v, 4) for k, v in cur.items()})
    return out


def low_sharpness_intervals(blur_samples):
    if not blur_samples:
        return []
    vals = sorted(s["blur"] for s in blur_samples)
    med = vals[len(vals) // 2]
    thr = med * 0.45
    out = []
    for s in blur_samples:
        if s["blur"] <= thr:
            out.append({"t": s["t"], "blur": s["blur"], "median_ref": round(med, 4)})
    return out


def speech_spans(silences, duration, pad=0.09):
    """Complemento dos silencios = trechos com fala/som."""
    spans, cursor = [], 0.0
    for s in silences:
        if s["start"] - cursor > 0.05:
            spans.append({"start": round(cursor, 4), "end": round(s["start"], 4)})
        cursor = s["end"]
    if duration - cursor > 0.05:
        spans.append({"start": round(cursor, 4), "end": round(duration, 4)})
    # padding para nao cortar respiracao/inicio de palavra
    padded = []
    for sp in spans:
        padded.append({
            "start": round(max(0.0, sp["start"] - pad), 4),
            "end": round(min(duration, sp["end"] + pad), 4),
        })
    merged = []
    for sp in padded:
        if merged and sp["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], sp["end"])
        else:
            merged.append(dict(sp))
    return merged


def detect_existing_captions(path, meta, frames_dir, n=6):
    """
    Heuristica para legendas ja queimadas: amostra frames, mede a densidade de
    bordas na faixa inferior vs. faixa central usando o proxy de nitidez do
    blurdetect em recortes. Reporta indicio + confianca, nunca certeza.
    """
    dur = meta.get("duration") or 0
    if dur <= 0:
        return {"likely": False, "confidence": 0, "method": "sem duracao"}
    h = meta["video"]["display_height"]
    w = meta["video"]["display_width"]
    band_h = max(2, int(h * 0.22))
    band_y = int(h * 0.60)
    scores = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        rc, out, err = run([
            FFMPEG, "-hide_banner", "-nostats", "-ss", "%.3f" % t, "-i", path,
            "-vf", ("crop=%d:%d:0:%d,format=gray,edgedetect=low=0.1:high=0.35,"
                    "signalstats,metadata=print:key=lavfi.signalstats.YAVG"
                    % (w, band_h, band_y)),
            "-frames:v", "1", "-an", "-f", "null", "-",
        ])
        m = re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", err)
        if m:
            scores.append(float(m.group(1)))
    if not scores:
        return {"likely": False, "confidence": 0, "method": "sem amostras"}
    avg = sum(scores) / len(scores)
    # bordas fortes e consistentes na faixa inferior sugerem texto queimado
    likely = avg > 12.0
    conf = int(min(85, max(20, (avg - 6.0) * 7)))
    return {
        "likely": bool(likely),
        "edge_score_avg": round(avg, 3),
        "samples": [round(s, 3) for s in scores],
        "confidence": conf if likely else int(min(80, max(20, (12.0 - avg) * 8))),
        "method": "densidade de bordas na faixa inferior (heuristica)",
        "note": "Indicio, nao prova. Claude deve confirmar inspecionando os frames extraidos.",
    }


# --------------------------------------------------------------------------
# 4. extracao de frames de evidencia
# --------------------------------------------------------------------------

def extract_frames(path, times, outdir, width=480):
    os.makedirs(outdir, exist_ok=True)
    written = []
    for i, t in enumerate(times):
        name = "f%03d_t%07.3f.jpg" % (i, t)
        dest = os.path.join(outdir, name)
        rc, out, err = run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-ss", "%.3f" % t,
            "-i", path, "-frames:v", "1",
            "-vf", "scale=%d:-2:flags=bicubic" % width,
            "-q:v", "3", "-y", dest,
        ])
        if rc == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 0:
            written.append({"index": i, "time": round(t, 3), "path": dest})
    return written


def pick_frame_times(duration, shots, motion, blur_low, scenes, max_frames=40):
    times = set()
    if duration <= 0:
        return []
    times.add(0.0)
    times.add(max(0.0, duration - 0.05))
    for s in scenes[:14]:
        times.add(max(0.0, s["time"] - 0.05))
        times.add(min(duration - 0.01, s["time"] + 0.05))
    for sh in shots[:20]:
        times.add(sh["start"] + min(0.15, sh["duration"] * 0.1))
        times.add(sh["start"] + sh["duration"] * 0.5)
        times.add(sh["end"] - min(0.15, sh["duration"] * 0.1))
    for m in motion[:10]:
        times.add((m["start"] + m["end"]) / 2.0)
    for b in blur_low[:6]:
        times.add(b["t"])
    # amostras periodicas
    n_periodic = min(12, max(4, int(duration / 6)))
    for i in range(n_periodic):
        times.add(duration * (i + 0.5) / n_periodic)

    clean = sorted(t for t in times if 0 <= t < duration)
    # dedup por proximidade
    out = []
    for t in clean:
        if out and (t - out[-1]) < 0.25:
            continue
        out.append(t)
    if len(out) > max_frames:
        stride = len(out) / float(max_frames)
        out = [out[int(i * stride)] for i in range(max_frames)]
    return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="EditClean - analise de video (manifesto JSON)")
    ap.add_argument("input")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--max-frames", type=int, default=40)
    ap.add_argument("--scene-threshold", type=float, default=0.22)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    _require_bins()

    src = os.path.abspath(os.path.expanduser(args.input))
    if not os.path.isfile(src):
        sys.stderr.write("ERRO: arquivo nao encontrado: %s\n" % src)
        sys.exit(2)
    if not os.access(src, os.R_OK):
        sys.stderr.write("ERRO: arquivo sem permissao de leitura: %s\n" % src)
        sys.exit(2)

    outdir = os.path.abspath(os.path.expanduser(args.outdir))
    os.makedirs(outdir, exist_ok=True)
    frames_dir = os.path.join(outdir, "frames")

    def log(msg):
        if not args.quiet:
            sys.stderr.write("[analyze] %s\n" % msg)

    log("ffprobe...")
    try:
        raw = probe(src)
        meta = build_metadata(raw, src)
    except Exception as exc:
        sys.stderr.write("ERRO: nao foi possivel ler o video: %s\n" % exc)
        sys.exit(2)

    duration = meta.get("duration") or 0.0
    if duration <= 0:
        sys.stderr.write("ERRO: duracao invalida ou nula\n")
        sys.exit(2)

    fps = meta["video"]["fps"]

    log("cenas...")
    scenes = detect_scenes(src, args.scene_threshold)
    log("silencios...")
    silences = detect_silences(src) if meta["has_audio"] else []
    log("frames pretos...")
    black = detect_black(src)
    log("congelamentos...")
    freeze = detect_freeze(src)
    log("movimento...")
    motion_samples, motion_step = sample_motion(src, duration, fps)
    log("nitidez...")
    blur_samples = sample_blur(src, duration, fps)
    log("audio...")
    audio = audio_transients(src, duration, meta["has_audio"])

    shots = build_shots(scenes, duration)
    motion = motion_intervals(motion_samples)
    blur_low = low_sharpness_intervals(blur_samples)
    speech = speech_spans(silences, duration) if meta["has_audio"] else [
        {"start": 0.0, "end": round(duration, 4)}
    ]

    log("legendas queimadas (heuristica)...")
    burned = detect_existing_captions(src, meta, frames_dir)

    log("extraindo frames de evidencia...")
    ftimes = pick_frame_times(duration, shots, motion, blur_low, scenes, args.max_frames)
    frames = extract_frames(src, ftimes, frames_dir)

    removable = [
        s for s in silences
        if s["duration"] >= 0.45 and s["start"] > 0.2 and s["end"] < duration - 0.2
    ]

    manifest = {
        "manifest_version": "1.0.0",
        "generated_by": "editclean/analyze_video.py",
        "source": meta,
        "analysis": {
            "scene_changes": scenes,
            "shots": shots,
            "silences": silences,
            "removable_silences": removable,
            "speech_spans": speech,
            "black_intervals": black,
            "freeze_intervals": freeze,
            "motion_intervals": motion,
            "motion_samples_step_frames": motion_step,
            "motion_samples": motion_samples,
            "low_sharpness_points": blur_low,
            "blur_samples": blur_samples,
            "audio_rms": audio.get("rms", []),
            "audio_transients": audio.get("transients", []),
            "existing_burned_captions": burned,
        },
        "summary": {
            "duration": round(duration, 4),
            "fps": fps,
            "resolution": "%dx%d" % (meta["video"]["display_width"], meta["video"]["display_height"]),
            "aspect": meta["video"]["aspect"],
            "has_audio": meta["has_audio"],
            "n_scene_changes": len(scenes),
            "n_shots": len(shots),
            "n_silences": len(silences),
            "n_removable_silences": len(removable),
            "removable_silence_total_s": round(sum(s["duration"] for s in removable), 3),
            "n_audio_transients": len(audio.get("transients", [])),
            "n_motion_intervals": len(motion),
            "n_low_sharpness_points": len(blur_low),
            "n_black_intervals": len(black),
            "n_freeze_intervals": len(freeze),
            "n_evidence_frames": len(frames),
        },
        "evidence_frames": frames,
        "frames_dir": frames_dir,
    }

    out_path = os.path.join(outdir, "manifest.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    log("manifesto: %s" % out_path)
    print(out_path)


if __name__ == "__main__":
    main()
