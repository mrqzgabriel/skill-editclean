#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - validate_output.py

Valida integralmente um MP4 renderizado antes de promove-lo ao destino final.

Executa:
  - decodificacao completa (ffmpeg -v error -i <out> -f null -)
  - ffprobe de streams e formato
  - presenca de video e (quando esperado) audio
  - duracao, resolucao, proporcao, fps, codec, pixel format
  - sincronizacao aproximada A/V (diferenca de duracao entre streams)
  - frames pretos inesperados
  - congelamentos longos inesperados
  - audio ausente / silencioso
  - inspecao do primeiro, do meio e do ultimo frame
  - legendas cortadas (texto fora do canvas / colado na borda)
  - arquivo vazio ou corrompido

Saida: JSON no stdout com {"ok": bool, "checks": [...], "errors": [...]}.
Codigo de saida 0 se aprovado, 1 se reprovado.

Uso:
    python3 validate_output.py "<video>" [--plan plan.json] [--frames-dir DIR] [--json-only]
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys


def _find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    for cand in (
        os.path.expanduser("~/.local/tools/%s" % name),
        "/opt/homebrew/bin/%s" % name,
        "/usr/local/bin/%s" % name,
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


FFMPEG = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")


def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return (p.returncode,
            p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace"))


def _rate(s):
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


class Report:
    def __init__(self):
        self.checks = []
        self.errors = []
        self.warnings = []

    def ok(self, name, detail=""):
        self.checks.append({"check": name, "status": "ok", "detail": detail})

    def fail(self, name, detail=""):
        self.checks.append({"check": name, "status": "fail", "detail": detail})
        self.errors.append("%s: %s" % (name, detail))

    def warn(self, name, detail=""):
        self.checks.append({"check": name, "status": "warn", "detail": detail})
        self.warnings.append("%s: %s" % (name, detail))


def validate(video, plan=None, frames_dir=None):
    rep = Report()

    # ---- 0. arquivo existe e nao esta vazio
    if not os.path.isfile(video):
        rep.fail("arquivo_existe", "nao encontrado: %s" % video)
        return rep, None
    size = os.path.getsize(video)
    if size <= 0:
        rep.fail("arquivo_nao_vazio", "0 bytes")
        return rep, None
    rep.ok("arquivo_nao_vazio", "%d bytes" % size)

    # ---- 1. ffprobe
    rc, out, err = run([FFPROBE, "-v", "error", "-print_format", "json",
                        "-show_format", "-show_streams", video])
    if rc != 0:
        rep.fail("ffprobe", err.strip()[:400])
        return rep, None
    try:
        info = json.loads(out)
    except ValueError as exc:
        rep.fail("ffprobe_json", str(exc))
        return rep, None
    rep.ok("ffprobe", "leitura de streams bem-sucedida")

    vs = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    aud = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]

    if not vs:
        rep.fail("stream_video", "nenhum stream de video")
        return rep, info
    v = vs[0]
    rep.ok("stream_video", "%s %sx%s" % (v.get("codec_name"), v.get("width"), v.get("height")))

    fmt = info.get("format", {})
    try:
        duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        rep.fail("duracao", "duracao invalida ou zero")
    else:
        rep.ok("duracao", "%.3fs" % duration)

    # ---- 2. decodificacao completa
    rc, out, err = run([FFMPEG, "-v", "error", "-i", video, "-f", "null", "-"])
    if rc != 0 or err.strip():
        rep.fail("decodificacao_integral", (err.strip()[:500] or "codigo %d" % rc))
    else:
        rep.ok("decodificacao_integral", "arquivo decodifica do inicio ao fim sem erros")

    # ---- 3. codec / pix_fmt / fps / resolucao
    pix = v.get("pix_fmt")
    if pix != "yuv420p":
        rep.warn("pixel_format", "esperado yuv420p, obtido %s" % pix)
    else:
        rep.ok("pixel_format", pix)

    if v.get("codec_name") != "h264":
        rep.warn("codec_video", "esperado h264, obtido %s" % v.get("codec_name"))
    else:
        rep.ok("codec_video", "h264")

    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    if w <= 0 or h <= 0 or w % 2 or h % 2:
        rep.fail("resolucao", "dimensoes invalidas ou impares: %dx%d" % (w, h))
    else:
        rep.ok("resolucao", "%dx%d" % (w, h))

    fps = _rate(v.get("avg_frame_rate")) or _rate(v.get("r_frame_rate"))
    if not fps or fps <= 0:
        rep.fail("fps", "fps invalido")
    else:
        rep.ok("fps", "%.4f" % fps)

    # ---- 4. conferencia contra o plano
    if plan:
        po = plan.get("output", {})
        if po.get("width") and po.get("height"):
            if (w, h) != (int(po["width"]), int(po["height"])):
                rep.fail("resolucao_vs_plano",
                         "plano pedia %dx%d, saida tem %dx%d"
                         % (po["width"], po["height"], w, h))
            else:
                rep.ok("resolucao_vs_plano", "%dx%d" % (w, h))
        if po.get("fps") and fps:
            if abs(fps - float(po["fps"])) > 0.5:
                rep.warn("fps_vs_plano", "plano pedia %.3f, saida tem %.3f" % (po["fps"], fps))
            else:
                rep.ok("fps_vs_plano", "%.3f" % fps)

        segs = plan.get("segments", [])
        if segs:
            expected = sum(s["duration"] for s in segs)
            for tr in plan.get("transitions", []):
                expected -= float(tr.get("duration", 0))
            if duration > 0 and expected > 0:
                drift = abs(duration - expected)
                tol = max(0.5, expected * 0.06)
                if drift > tol:
                    rep.fail("duracao_vs_plano",
                             "esperado ~%.2fs, obtido %.2fs (desvio %.2fs)"
                             % (expected, duration, drift))
                else:
                    rep.ok("duracao_vs_plano",
                           "esperado ~%.2fs, obtido %.2fs" % (expected, duration))

        # proporcao
        want_aspect = po.get("aspect")
        if want_aspect and want_aspect != "keep" and w and h:
            try:
                aw, ah = (int(x) for x in want_aspect.split(":"))
                if abs((w / float(h)) - (aw / float(ah))) > 0.02:
                    rep.fail("proporcao", "esperado %s, saida tem %.4f" % (want_aspect, w / float(h)))
                else:
                    rep.ok("proporcao", want_aspect)
            except (ValueError, ZeroDivisionError):
                pass

    # ---- 5. audio
    expects_audio = True
    if plan:
        expects_audio = bool(plan.get("source", {}).get("has_audio", True)) and \
                        bool((plan.get("audio") or {}).get("enabled", True))

    if expects_audio:
        if not aud:
            rep.fail("stream_audio", "audio esperado mas ausente na saida")
        else:
            a = aud[0]
            rep.ok("stream_audio", "%s %sHz %sch"
                   % (a.get("codec_name"), a.get("sample_rate"), a.get("channels")))
            # audio silencioso?
            rc2, o2, e2 = run([FFMPEG, "-hide_banner", "-nostats", "-i", video,
                               "-af", "volumedetect", "-vn", "-f", "null", "-"])
            m = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", e2)
            if m:
                mean_db = float(m.group(1))
                if mean_db < -60.0:
                    rep.fail("audio_nao_silencioso", "volume medio %.1f dB (praticamente mudo)" % mean_db)
                else:
                    rep.ok("audio_nao_silencioso", "volume medio %.1f dB" % mean_db)
            else:
                rep.warn("audio_nao_silencioso", "nao foi possivel medir o volume")

            # sincronizacao aproximada A/V
            try:
                adur = float(a.get("duration") or 0)
            except (TypeError, ValueError):
                adur = 0.0
            try:
                vdur = float(v.get("duration") or 0)
            except (TypeError, ValueError):
                vdur = 0.0
            if adur > 0 and vdur > 0:
                delta = abs(adur - vdur)
                if delta > 0.35:
                    rep.fail("sincronia_av", "video %.3fs vs audio %.3fs (delta %.3fs)"
                             % (vdur, adur, delta))
                else:
                    rep.ok("sincronia_av", "delta %.3fs" % delta)
            else:
                rep.warn("sincronia_av", "duracao por stream indisponivel")
    else:
        rep.ok("stream_audio", "sem audio esperado")

    # ---- 6. frames pretos inesperados
    rc3, o3, e3 = run([FFMPEG, "-hide_banner", "-nostats", "-i", video,
                       "-vf", "blackdetect=d=0.25:pic_th=0.98", "-an", "-f", "null", "-"])
    blacks = [(float(m.group(1)), float(m.group(2)))
              for m in re.finditer(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", e3)]
    allowed_black = []
    if plan:
        cl = plan.get("closing") or {}
        if cl.get("type") in ("fade_out", "dip_to_black"):
            allowed_black.append((max(0.0, duration - float(cl.get("duration", 0.5)) - 0.6), duration + 1))
        for tr in plan.get("transitions", []):
            if tr.get("type") == "dip_to_black":
                allowed_black.append((float(tr["start"]) - 0.4, float(tr["end"]) + 0.4))
    unexpected = [b for b in blacks
                  if not any(lo <= b[0] <= hi for lo, hi in allowed_black)]
    if unexpected:
        rep.fail("frames_pretos", "trechos pretos inesperados: %s"
                 % ", ".join("%.2f-%.2fs" % b for b in unexpected[:6]))
    else:
        rep.ok("frames_pretos", "nenhum trecho preto inesperado")

    # ---- 7. congelamentos longos
    rc4, o4, e4 = run([FFMPEG, "-hide_banner", "-nostats", "-i", video,
                       "-vf", "freezedetect=n=-60dB:d=1.5", "-an", "-f", "null", "-"])
    freezes, cur = [], None
    for m in re.finditer(r"freeze_start:\s*([0-9.]+)|freeze_end:\s*([0-9.]+)", e4):
        if m.group(1) is not None:
            cur = float(m.group(1))
        elif m.group(2) is not None and cur is not None:
            freezes.append((cur, float(m.group(2))))
            cur = None
    long_freezes = [f for f in freezes if (f[1] - f[0]) >= 1.5]
    if long_freezes:
        rep.warn("congelamentos", "trechos congelados >=1.5s: %s"
                 % ", ".join("%.2f-%.2fs" % f for f in long_freezes[:6]))
    else:
        rep.ok("congelamentos", "nenhum congelamento longo")

    # ---- 8. inspecao de frames (primeiro, meio, ultimo)
    if frames_dir:
        os.makedirs(frames_dir, exist_ok=True)
        picked = []
        for label, t in (("first", 0.05), ("mid", max(0.1, duration / 2.0)),
                         ("last", max(0.1, duration - 0.10))):
            dest = os.path.join(frames_dir, "validate_%s.jpg" % label)
            rcf, _, _ = run([FFMPEG, "-hide_banner", "-loglevel", "error",
                             "-ss", "%.3f" % t, "-i", video, "-frames:v", "1",
                             "-q:v", "3", "-y", dest])
            if rcf == 0 and os.path.isfile(dest) and os.path.getsize(dest) > 0:
                picked.append({"label": label, "time": round(t, 3), "path": dest})
        if len(picked) == 3:
            rep.ok("frames_inspecao", "extraidos: %s"
                   % ", ".join("%s@%.2fs" % (p["label"], p["time"]) for p in picked))
        else:
            rep.fail("frames_inspecao", "nao foi possivel extrair os 3 frames de referencia")

    # ---- 9. legendas cortadas
    if plan and (plan.get("captions") or {}).get("enabled"):
        caps = plan["captions"]
        fsize = int(caps.get("font_size_px") or round(h * 0.038))
        max_w_pct = float(caps.get("max_width_pct", 0.76))
        problems = []
        anchors = {"lower_default": 0.59, "footer": 0.76, "upper": 0.155}
        for b in caps.get("blocks", []):
            n_lines = int(b.get("lines", 1))
            y0 = anchors.get(b.get("anchor", "lower_default"), 0.59) * h
            y1 = y0 + n_lines * fsize * 1.21
            if y1 > h * 0.98:
                problems.append("bloco %s ultrapassa a base (y_final=%.0fpx de %d)"
                                % (b.get("id"), y1, h))
            if y0 < h * 0.02:
                problems.append("bloco %s acima do topo seguro" % b.get("id"))
            # v3.0: largura MEDIDA com as fontes reais (TextMeasure do build_plan, com o
            # accent_size_ratio) -- a estimativa por caractere dava falso positivo em todo bloco
            # com palavra serifada. Cai na estimativa so se o build_plan nao importar.
            bfs = int(b.get("font_size_px") or fsize)
            for ln in range(n_lines):
                items = [(wd.get("style", "normal"), wd["text"]) for wd in b.get("words", [])
                         if int(wd.get("line", 0)) == ln]
                if not items:
                    continue
                if _MEAS is not None:
                    est_w = _MEAS.width(items, bfs)
                    limit = w * float(_PROF.get("captions", {}).get("layout", {}).get("max_width_pct_of_canvas", 0.82)) * 1.06
                    how = "medida"
                else:
                    est_w = sum(len(t) + 1 for _, t in items) * bfs * 0.52
                    limit = w * max_w_pct * 1.25
                    how = "estimada"
                if est_w > limit:
                    problems.append("bloco %s linha %d larga demais (%s: %.0fpx, limite %.0fpx)"
                                    % (b.get("id"), ln, how, est_w, limit))
        if problems:
            rep.warn("legendas_dentro_do_canvas", "; ".join(problems[:6]))
        else:
            rep.ok("legendas_dentro_do_canvas",
                   "%d bloco(s) dentro da area segura" % len(caps.get("blocks", [])))

    return rep, info


_MEAS, _PROF = None, {}


def _init_measure(plan):
    """TextMeasure do build_plan com o perfil e o canvas do plano (fontes reais)."""
    global _MEAS, _PROF
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import build_plan as bp
        _PROF = json.load(open(bp.PROFILE_PATH, encoding="utf-8"))
        W = int(plan["output"]["width"]); H = int(plan["output"]["height"])
        _MEAS = bp.TextMeasure(_PROF, W, H)
    except Exception as e:  # pragma: no cover
        sys.stderr.write("[validate] medidor de fontes indisponivel (%s); usando estimativa\n" % e)
        _MEAS = None


def main():
    ap = argparse.ArgumentParser(description="EditClean - validacao do video final")
    ap.add_argument("video")
    ap.add_argument("--plan")
    ap.add_argument("--frames-dir")
    ap.add_argument("--json-only", action="store_true")
    args = ap.parse_args()

    if not FFMPEG or not FFPROBE:
        sys.stderr.write("ERRO: ffmpeg/ffprobe nao encontrados\n")
        sys.exit(2)

    plan = None
    if args.plan:
        with open(args.plan, encoding="utf-8") as fh:
            plan = json.load(fh)

    if plan:
        _init_measure(plan)
    rep, info = validate(os.path.abspath(args.video), plan, args.frames_dir)

    result = {
        "ok": not rep.errors,
        "video": os.path.abspath(args.video),
        "n_checks": len(rep.checks),
        "n_errors": len(rep.errors),
        "n_warnings": len(rep.warnings),
        "checks": rep.checks,
        "errors": rep.errors,
        "warnings": rep.warnings,
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if not args.json_only:
        sys.stderr.write("\n%s  %d checagens, %d erro(s), %d aviso(s)\n"
                         % ("APROVADO" if result["ok"] else "REPROVADO",
                            result["n_checks"], result["n_errors"], result["n_warnings"]))
        for e in rep.errors:
            sys.stderr.write("  ERRO   %s\n" % e)
        for w in rep.warnings:
            sys.stderr.write("  aviso  %s\n" % w)

    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
