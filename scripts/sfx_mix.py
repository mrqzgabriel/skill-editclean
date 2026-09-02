#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - sfx_mix.py  (v2.16)

Sound design do video editado: coloca efeitos sonoros (SFX) nos eventos de motion do
plano e mixa ABAIXO da voz, sem re-encodar o video.

Eventos lidos do edit-plan.json (timeline de SAIDA) e do brand-logos.json:

  opening        abertura (desfoque que resolve)           -> riser curto + soft impact no assentar
  logo in/out    logo sobe (t_in) / sai (t_out)            -> whoosh_in antes da subida; shimmer no
                                                             assentar (t_settle); whoosh_out na saida
  push-down      video desce (down_start) / sobe (up_start)-> slide/whoosh curto nas duas rampas
  overlay in     imagem acende (start, fade 350 ms)        -> pop suave
  overlay swap   troca seca entre duas imagens             -> click/tick
  punch          punch_release / punch_hold (corte seco)   -> bass_hit sutil
  closing        fade final                                -> (nada; a voz apaga com o afade)

Regras (pesquisa 01/09/2026, ver style-spec 20): whoosh ANTECEDE o movimento (~120-180 ms),
pop/click caem NO frame em que o elemento aparece, hit cai no corte; SFX entre -18 e -12 dB
abaixo da voz, no maximo um SFX "grande" a cada poucos segundos, nunca em cima de silaba
importante se for estridente. Jump cuts comuns NAO recebem SFX (vira metralhadora).

Biblioteca: assets/sfx/<categoria>/<arquivo> com assets/sfx/manifest.json (origem, licenca).
O usuario pode trocar qualquer arquivo pelo dele. Mapa de categorias -> arquivo em --library
ou no manifest ("default").

Uso:
  python3 sfx_mix.py --plan edit-plan.json --events brand-logos.json --in final.partial.mp4 \
          --out final_sfx.partial.mp4 [--gain-db -14] [--report sfx-events.json]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)
SFX_DIR = os.path.join(SKILL_ROOT, "assets", "sfx")
MANIFEST = os.path.join(SFX_DIR, "manifest.json")


def _find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    for cand in (os.path.expanduser("~/.local/tools/%s" % name), "/opt/homebrew/bin/%s" % name, "/usr/local/bin/%s" % name):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


FFMPEG = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")


def log(msg):
    sys.stderr.write("[sfx] %s\n" % msg)


def probe_duration(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode().strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def load_library(path=None):
    """{'categoria': {'file': ..., 'gain_db': ..., 'lead_ms': ...}}"""
    man = json.load(open(path or MANIFEST, encoding="utf-8"))
    lib = {}
    for cat, entry in (man.get("default") or {}).items():
        f = entry["file"] if isinstance(entry, dict) else entry
        if not os.path.isabs(f):
            f = os.path.join(SFX_DIR, f)
        if not os.path.isfile(f):
            log("AVISO: %s -> %s nao existe" % (cat, f))
            continue
        lib[cat] = {"file": f, "gain_db": float(entry.get("gain_db", 0.0)) if isinstance(entry, dict) else 0.0,
                    "lead_ms": float(entry.get("lead_ms", 0.0)) if isinstance(entry, dict) else 0.0,
                    "trim_s": float(entry.get("trim_s", 0.0)) if isinstance(entry, dict) else 0.0,
                    "max_s": float(entry.get("max_s", 0.0)) if isinstance(entry, dict) else 0.0}
    return lib, man


# ---------------------------------------------------------------- eventos
def collect_events(plan, logos, rules):
    """Devolve lista de {t, cat, why}. t em segundos da timeline de saida."""
    ev = []
    dur = float(plan.get("output", {}).get("duration") or plan.get("duration") or 0.0)

    def add(t, cat, why):
        if t is None or t < 0:
            return
        ev.append({"t": round(float(t), 3), "cat": cat, "why": why})

    # abertura
    op = plan.get("opening") or {}
    if op.get("enabled", True) and rules.get("opening", True):
        add(0.0, "riser", "abertura: desfoque resolve")
        add(float(op.get("duration", 0.7)) * 0.85, "impact", "abertura assenta")

    # logos
    for e in (logos or {}).get("events", []) if isinstance(logos, dict) else (logos or []):
        t_in, t_settle, t_out = float(e["t_in"]), float(e.get("t_settle", e["t_in"] + 0.66)), float(e["t_out"])
        add(t_in, "whoosh_in", "logo %s sobe" % e.get("mention", e.get("brand")))
        add(t_settle, "logo_land", "logo %s pousa (hit macio)" % e.get("mention", e.get("brand")))
        add(t_settle, "shimmer", "logo %s acende (sparkle)" % e.get("mention", e.get("brand")))
        add(t_out, "whoosh_out", "logo %s sai" % e.get("mention", e.get("brand")))

    # push-down
    pd = plan.get("push_down") or {}
    for w in (pd.get("windows") or []) if isinstance(pd, dict) else []:
        ds = w.get("down_start", w.get("start"))
        us = w.get("up_start")
        if us is None and w.get("up_end") is not None:
            us = float(w["up_end"]) - float(pd.get("ramp_s", 0.35))
        elif us is None and w.get("end") is not None:
            us = float(w["end"]) - float(pd.get("ramp_s", 0.35))
        add(ds, "slide", "video desce (push-down)")
        add(us, "slide_back", "video volta")

    # overlays (imagens): pop na entrada; click na troca seca
    ovs = sorted([o for o in plan.get("overlays", []) if o.get("type") == "image"], key=lambda o: float(o["start"]))
    prev_end = None
    for o in ovs:
        st = float(o["start"])
        entry_ms = float((o.get("params") or {}).get("entry_ms", 350))
        if prev_end is not None and abs(st - prev_end) < 0.05 and entry_ms == 0:
            add(st, "click", "troca seca %s" % o.get("id"))
        else:
            add(st + entry_ms / 1000.0 * 0.9, "pop", "imagem %s chega" % o.get("id"))
        prev_end = float(o["end"])

    # punch-in (corte seco com salto de escala): o build_plan guarda o padrao
    # dentro do segmento (segments[].zoom.preset_id = punch_release_NN / punch_hold_NN)
    for sg in plan.get("segments", []) or []:
        z = sg.get("zoom") or {}
        pid = str(z.get("preset_id") or z.get("pattern") or "")
        if pid.startswith("punch") and sg.get("out_start") is not None and float(sg["out_start"]) > 0.05:
            add(float(sg["out_start"]), "bass_hit", "punch-in %s (%s)" % (pid, sg.get("id")))
    for m in plan.get("moves", []) or []:
        pid = str(m.get("pattern") or (m.get("params") or {}).get("pattern") or "")
        if pid.startswith("punch"):
            add(float(m["start"]), "bass_hit", "punch-in %s" % pid)

    ev.sort(key=lambda x: x["t"])
    # abertura + logo no mesmo instante: o impacto do assentar ja "lanca" o logo;
    # um whoosh_in em cima vira barulho duplo -> sai o whoosh_in
    impacts = [e["t"] for e in ev if e["cat"] == "impact"]
    ev = [e for e in ev if not (e["cat"] == "whoosh_in" and any(abs(e["t"] - t) < 0.4 for t in impacts))]
    # dois hits a menos de 0,7 s (impacto da abertura + pouso do logo) viram um so: fica o pouso
    lands = [e["t"] for e in ev if e["cat"] == "logo_land"]
    ev = [e for e in ev if not (e["cat"] == "impact" and any(abs(e["t"] - t) < 0.7 for t in lands))]
    # anti-metralhadora: dois SFX da mesma categoria a < 250 ms -> fica o primeiro
    out, last = [], {}
    for e in ev:
        if e["cat"] in last and e["t"] - last[e["cat"]] < 0.25:
            continue
        last[e["cat"]] = e["t"]
        out.append(e)
    return out, dur


# ---------------------------------------------------------------- mix
def build_mix(events, lib, video_in, out, gain_db, workdir, ducking):
    inputs = [video_in]
    chains = []
    labels = []
    k = 0
    used = []
    for e in events:
        spec = lib.get(e["cat"])
        if not spec:
            log("sem arquivo para %s (%s) -- pulando" % (e["cat"], e["why"]))
            continue
        k += 1
        inputs.append(spec["file"])
        t = max(0.0, e["t"] - spec["lead_ms"] / 1000.0)
        delay_ms = int(round(t * 1000))
        f = "[%d:a]" % k
        chain = "aformat=sample_rates=48000:channel_layouts=stereo"
        if spec["trim_s"] > 0:
            chain += ",atrim=start=%.3f,asetpts=PTS-STARTPTS" % spec["trim_s"]
        if spec["max_s"] > 0:
            chain += ",atrim=end=%.3f" % spec["max_s"]
            chain += ",afade=t=out:st=%.3f:d=0.08" % max(0.0, spec["max_s"] - 0.08)
        chain += ",volume=%.2fdB" % (gain_db + spec["gain_db"])
        chain += ",adelay=%d|%d" % (delay_ms, delay_ms)
        lab = "[s%d]" % k
        chains.append(f + chain + lab)
        labels.append(lab)
        used.append(dict(e, file=os.path.basename(spec["file"]), at=round(t, 3), gain_db=round(gain_db + spec["gain_db"], 1)))
    if not labels:
        raise SystemExit("nenhum SFX para mixar")
    n = len(labels)
    # soma dos SFX (amix normaliza por padrao -> desligar com normalize=0)
    sfx_sum = "%samix=inputs=%d:normalize=0:dropout_transition=0[sfx]" % ("".join(labels), n)
    voice = "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voz]"
    if ducking:
        # a voz manda: SFX abaixa levemente quando a voz esta presente (sidechain suave)
        mix = "[sfx][voz]sidechaincompress=threshold=0.05:ratio=2:attack=20:release=250:makeup=1[sfxd];" \
              "[voz][sfxd]amix=inputs=2:normalize=0:dropout_transition=0[aout]"
        # sidechaincompress consome [voz]; precisamos de uma copia
        voice = "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[voz][vozsc]"
        mix = "[sfx][vozsc]sidechaincompress=threshold=0.05:ratio=2:attack=20:release=250:makeup=1[sfxd];" \
              "[voz][sfxd]amix=inputs=2:normalize=0:dropout_transition=0[aout]"
    else:
        mix = "[voz][sfx]amix=inputs=2:normalize=0:dropout_transition=0[aout]"
    fc = ";".join(chains + [sfx_sum, voice, mix])
    os.makedirs(workdir, exist_ok=True)
    open(os.path.join(workdir, "sfx_filtergraph.txt"), "w").write(fc)
    # bus so de SFX (para conferir nivel): mesma cadeia sem a voz
    fc_bus = ";".join(chains + [sfx_sum])
    cmd_bus = [FFMPEG, "-y", "-v", "error"]
    for p in inputs:
        cmd_bus += ["-i", p]
    cmd_bus += ["-filter_complex", fc_bus, "-map", "[sfx]", "-c:a", "pcm_s16le", "-t", "%.3f" % (probe_duration(video_in) or 600),
                os.path.join(workdir, "sfx_bus.wav")]
    subprocess.run(cmd_bus, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    cmd = [FFMPEG, "-y", "-v", "error", "-stats"]
    for p in inputs:
        cmd += ["-i", p]
    cmd += ["-filter_complex", fc, "-map", "0:v", "-map", "[aout]", "-map_chapters", "-1", "-map_metadata", "0",
            "-dn", "-sn", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "224k", "-ar", "48000", "-movflags", "+faststart", "-shortest", out]
    log("mixando %d SFX..." % n)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        sys.stderr.write(p.stderr.decode("utf-8", "replace")[-3000:])
        raise SystemExit("ffmpeg falhou")
    return used


def main():
    ap = argparse.ArgumentParser(description="EditClean: sound design (SFX) nos eventos de motion")
    ap.add_argument("--plan", required=True)
    ap.add_argument("--events", default=None, help="brand-logos.json (eventos de logo)")
    ap.add_argument("--in", dest="video_in", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--library", default=None, help="manifest.json alternativo")
    ap.add_argument("--gain-db", type=float, default=-14.0, help="ganho global dos SFX (abaixo da voz)")
    ap.add_argument("--no-ducking", action="store_true")
    ap.add_argument("--no-opening", action="store_true")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--dry-run", action="store_true", help="so listar os eventos")
    args = ap.parse_args()
    if not FFMPEG or not FFPROBE:
        raise SystemExit("ffmpeg/ffprobe nao encontrados")
    plan = json.load(open(args.plan, encoding="utf-8"))
    logos = json.load(open(args.events, encoding="utf-8")) if args.events and os.path.isfile(args.events) else \
        {"events": plan.get("brand_logos") or []}
    lib, man = load_library(args.library)
    events, dur = collect_events(plan, logos, {"opening": not args.no_opening})
    for e in events:
        log("%7.3f  %-11s %s%s" % (e["t"], e["cat"], e["why"], "" if e["cat"] in lib else "   (SEM ARQUIVO)"))
    if args.dry_run:
        print(json.dumps(events, ensure_ascii=False, indent=1))
        return
    workdir = args.workdir or os.path.join(os.path.dirname(os.path.abspath(args.out)), "sfx_work")
    used = build_mix(events, lib, args.video_in, args.out, args.gain_db, workdir, not args.no_ducking)
    rep = {"version": "2.16", "gain_db": args.gain_db, "ducking": not args.no_ducking,
           "library": man.get("_license_note"), "events": used}
    if args.report:
        json.dump(rep, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("%d SFX mixados -> %s" % (len(used), args.out))
    print(args.out)


if __name__ == "__main__":
    main()
