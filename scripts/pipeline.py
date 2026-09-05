#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - pipeline.py  (v3.0)

Orquestra o fluxo inteiro a partir de um job.json no diretorio de trabalho, em estagios que
podem ser repetidos (regenerou uma parte? roda 'prep' de novo e segue). Cada estagio imprime o
que decidiu; o Claude continua responsavel por OLHAR (blocos, frames, imagens) entre eles.

job.json:
{
  "name": "Fable 5.1 Chegou 25% Mais Barato",          # nome da entrega (pasta no Desktop)
  "parts_dir": "partes",                                  # video em trechos (parteN.mp4) ...
  "source": null,                                         # ... ou um video unico
  "overrides": {"parte9.mp4": {"end": 2.28}},             # cortes manuais por parte (balbucio)
  "influencia_project": "59a7affc-...",                   # id/titulo no influencIA (opcional)
  "copies": "project_meta.json",                          # copias p/ corrigir a transcricao (opcional)
  "overlays": [...], "accent_words": [...],               # ver anchor_overlays.py
  "cover": {"headline": "O *Fable 5.1* CHEGOU 25% MAIS BARATO", "logo": "claude",
            "moods": ["void_light", "studio_haze", "server_room"], "pick": "void_light"},
  "sfx": {"gain_db": -14},
  "quality": "high"
}

Estagios:
  prep     master (concat_parts) -> analyze -> subject -> transcribe -> fix_transcript ->
           anchor_overlays -> build_plan (rascunho) -> lista de blocos -> validate-only
  draft    render rascunho (crf 30) + frames de inspecao em draft_frames/
  render   build_plan alta -> brand_logos plan -> render (crf 14) -> compose logos (crf 18) ->
           (com job.shots: base limpa -> compose_shots -> logos -> sfx; ver SKILL.md 5b)
           sfx_mix -> validate_output -> av_sync_check (no arquivo com SFX)
  assets   capas (um mood por vez) + legenda do post
  deliver  promove o .partial validado e entrega a pasta no Desktop (--overwrite opcional)
  all      prep + render + assets + deliver (sem parar para olhar -- so quando ja conferido)

Uso:
  python3 pipeline.py --work "$WORK" prep
  python3 pipeline.py --work "$WORK" render
  python3 pipeline.py --work "$WORK" assets
  python3 pipeline.py --work "$WORK" deliver [--overwrite]
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)


def _find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    for cand in (os.path.expanduser("~/.local/tools/%s" % name), "/opt/homebrew/bin/%s" % name, "/usr/local/bin/%s" % name):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return name


FFMPEG = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")
os.environ["PATH"] = os.path.dirname(FFMPEG) + os.pathsep + os.environ.get("PATH", "")


def log(msg):
    sys.stderr.write("[pipeline] %s\n" % msg)


def sh(cmd, quiet_patterns=("RuntimeWarning", "mel_spec", "WARN:0@"), check=True, capture=False):
    """Roda um script mostrando a saida (menos avisos ruidosos)."""
    log("$ " + " ".join(os.path.basename(c) if i == 1 and c.endswith(".py") else c for i, c in enumerate(cmd))[:220])
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = p.stdout.decode("utf-8", "replace")
    for line in text.splitlines():
        if not any(q in line for q in quiet_patterns):
            sys.stderr.write("   " + line + "\n")
    if check and p.returncode != 0:
        raise SystemExit("falhou: %s (exit %d)" % (os.path.basename(cmd[1] if len(cmd) > 1 else cmd[0]), p.returncode))
    return text


def slug(name):
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_") or "video"


def script(name):
    return [sys.executable, os.path.join(HERE, name)]


def load_job(work):
    p = os.path.join(work, "job.json")
    if not os.path.isfile(p):
        raise SystemExit("job.json nao encontrado em %s" % work)
    job = json.load(open(p, encoding="utf-8"))
    job.setdefault("quality", "high")
    return job


def paths(work, job):
    base = slug(job["name"])
    return {
        "master": os.path.join(work, "master.mp4"),
        "dest": os.path.join(work, base + "_editclean.mp4"),
        "plan": os.path.join(work, "edit-plan.json"),
        "words_raw": os.path.join(work, "words_raw.json"),
        "words": os.path.join(work, "words.json"),
        "manifest": os.path.join(work, "manifest.json"),
        "ov": os.path.join(work, "ov.json"),
        "acc": os.path.join(work, "acc.json"),
        "logos": os.path.join(work, "brand-logos.json"),
        "shots": os.path.join(work, "shots.json"),            # v4: estilo dinamico
        "plan_sfx": os.path.join(work, "plan_sfx.json"),
        "subject": os.path.join(work, "subject.json"),
        "caption": os.path.join(work, base + "_LEGENDA.txt"),
        "capa_dir": os.path.join(work, "capa"),
        "base": base,
    }


# ------------------------------------------------------------------ estagios
def stage_prep(work, job):
    P = paths(work, job)
    src = job.get("source")
    if job.get("parts_dir"):
        pdir = job["parts_dir"] if os.path.isabs(job["parts_dir"]) else os.path.join(work, job["parts_dir"])
        ov_path = os.path.join(work, "partes_overrides.json")
        json.dump(job.get("overrides") or {}, open(ov_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        cmd = script("concat_parts.py") + ["--dir", pdir, "--pattern", job.get("parts_pattern", "parte*.mp4"),
                                            "--out", P["master"], "--scale", job.get("scale", "1080:1920"),
                                            "--report", os.path.join(work, "partes_report.json"), "--overrides", ov_path,
                                            "--last-tail-extra", str(job.get("last_tail_extra", 0.35)), "--overwrite"]
        sh(cmd)
        src = P["master"]
    if not src or not os.path.isfile(src):
        raise SystemExit("sem fonte: informe parts_dir ou source no job.json")
    job["_source"] = src
    json.dump(job, open(os.path.join(work, "job.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    dur = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                         stdout=subprocess.PIPE).stdout.decode().strip()
    log("fonte: %s (%s s)" % (os.path.basename(src), dur))
    shutil.rmtree(os.path.join(work, "frames"), ignore_errors=True)
    sh(script("analyze_video.py") + [src, "--outdir", work])
    sh(script("detect_subject.py") + ["--video", src, "--outdir", work])
    sh(script("transcribe.py") + [src, "--out", P["words_raw"], "--language", job.get("language", "pt")])
    fx = script("fix_transcript.py") + [P["words_raw"], P["manifest"], P["words"]]
    loc = os.path.join(work, "transcript-fixes.local.json")     # v3.1: erro de ouvido que so vale neste video
    if os.path.isfile(loc):
        fx += ["--fixes-local", loc]
    cop = job.get("copies")
    if cop:
        cop = cop if os.path.isabs(cop) else os.path.join(work, cop)
        if os.path.isfile(cop):
            fx += ["--copies", cop]
    sh(fx)
    sh(script("anchor_overlays.py") + ["--job", os.path.join(work, "job.json"), "--words", P["words"], "--manifest", P["manifest"],
                                       "--ov", P["ov"], "--acc", P["acc"]])
    build_plan(work, job, "draft")
    print_blocks(P["plan"])
    sh(script("render_edit.py") + ["--plan", P["plan"], "--validate-only"])
    if job.get("shots"):                                   # v4: estilo dinamico (b-roll + formas variadas)
        sh(script("shots_plan.py") + ["--job", os.path.join(work, "job.json"), "--words", P["words"], "--plan", P["plan"],
                                      "--out", P["shots"], "--plan-sfx", P["plan_sfx"]])
    log("prep OK -> olhe os blocos acima e as insercoes/shots; depois: render")


def build_plan(work, job, quality):
    P = paths(work, job)
    cmd = script("build_plan.py") + ["--work", work, "--source", job["_source"], "--dest", P["dest"], "--quality", quality]
    if os.path.isfile(P["ov"]) and json.load(open(P["ov"], encoding="utf-8")):
        cmd += ["--overlays", P["ov"]]
    if os.path.isfile(P["acc"]):
        cmd += ["--accent", P["acc"]]
    if job.get("no_push"):
        cmd.append("--no-push")
    sh(cmd)


def print_blocks(plan_path):
    p = json.load(open(plan_path, encoding="utf-8"))
    log("blocos de legenda:")
    for b in p["captions"]["blocks"]:
        txt = " ".join(("*%s*" % w["text"]) if w["style"] == "accent" else w["text"] for w in b["words"])
        sys.stderr.write("   %6.2f-%6.2f fs%3d L%d | %s\n" % (b["start"], b["end"], b["font_size_px"], b["lines"], txt))


def _render_shots(work, job, quality):
    """v4 (05/09/2026, aprovado 'nota 10' no GPT-6 Astra): base SEM legenda/insercao/push-down ->
    compose_shots (legenda como camada, shots de shots.json) -> logos -> SFX (plan_sfx) -> portoes -> validacao."""
    P = paths(work, job)
    if not os.path.isfile(P["shots"]):
        raise SystemExit("job tem 'shots' mas nao existe shots.json: rode 'prep' de novo")
    build_plan(work, job, quality)
    # logos: planejar com as JANELAS DOS SHOTS como push-down (plan_sfx.json), senao o logo pousa
    # na boca da pessoa dentro da tela dividida ou em cima da pagina (visto no GPT-6 Astra v4)
    sh(script("shots_plan.py") + ["--job", os.path.join(work, "job.json"), "--words", P["words"], "--plan", P["plan"],
                                  "--out", P["shots"], "--plan-sfx", P["plan_sfx"]])
    sh(script("brand_logos.py") + ["plan", "--work", work, "--plan", P["plan_sfx"]], check=False)
    plan = json.load(open(P["plan"], encoding="utf-8"))
    events = json.load(open(P["logos"], encoding="utf-8")).get("events", []) if os.path.isfile(P["logos"]) else []
    # legenda, insercoes e push-down saem da base: o compose_shots faz tudo isso por cima
    plan["captions"]["enabled"] = False; plan["overlays"] = []
    if isinstance(plan.get("push_down"), dict):
        plan["push_down"]["enabled"] = False; plan["push_down"]["windows"] = []
    plan["brand_logos"] = []
    plan["output"]["crf"] = 14 if quality == "high" else 24
    plan.setdefault("notes", []).append("pipeline v4: base limpa -> compose_shots -> logos -> sfx -> validate")
    base_plan = os.path.join(work, "plan_base.json"); json.dump(plan, open(base_plan, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sh(script("render_edit.py") + ["--plan", base_plan, "--validate-only"])
    base = os.path.join(work, "base_%s.mp4" % quality)
    import hashlib
    base_part = base + ".partial.mp4"
    plan_sig = hashlib.sha1(json.dumps({k: v for k, v in plan.items() if k not in ("notes",)}, sort_keys=True).encode("utf-8")).hexdigest()
    sig_file = base + ".plan.sha1"
    reuse = os.path.isfile(base_part) and os.path.isfile(sig_file) and open(sig_file).read().strip() == plan_sig
    for f in (P["dest"] + ".partial.mp4", os.path.join(work, P["base"] + "_semSFX.partial.mp4")):
        if os.path.exists(f): os.remove(f)
    if reuse:
        log("base reaproveitada (plano igual): %s" % base_part)
    else:
        if os.path.exists(base_part): os.remove(base_part)
        sh(script("render_edit.py") + ["--plan", base_plan, "--out", base, "--workdir", os.path.join(work, "render_base")])
        open(sig_file, "w").write(plan_sig)
    _assert_av_equal(base_part, "base A/V")
    ass = os.path.join(work, "render_base", "captions.ass")
    if not os.path.isfile(ass):
        # o render da base nao escreve o .ass (legenda desligada): gera a partir do plano original
        full_plan = json.load(open(P["plan"], encoding="utf-8"))
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import render_edit as RE
        RE.build_ass(full_plan, ass)
    comp = os.path.join(work, P["base"] + "_comp.partial.mp4")
    cmd = script("compose_shots.py") + ["--base", base_part, "--shots", P["shots"], "--ass", ass,
                                        "--fonts", os.path.join(SKILL_ROOT, "assets", "fonts"), "--subject", P["subject"], "--out", comp,
                                        "--crf", "14" if quality == "high" else "26", "--preset", "medium" if quality == "high" else "veryfast"]
    sh(cmd)
    cur = comp
    if events:
        shutil.rmtree(os.path.join(work, "logos_work"), ignore_errors=True)
        out = os.path.join(work, P["base"] + "_semSFX.partial.mp4")
        sh(script("brand_logos.py") + ["render", "--events", P["logos"], "--in", cur, "--out", out, "--workdir", os.path.join(work, "logos_work")])
        cur = out
    sfx = job.get("sfx", {})
    if sfx is not False and sfx.get("enabled", True):
        out = P["dest"] + ".partial.mp4"
        cmd = script("sfx_mix.py") + ["--plan", P["plan_sfx"], "--events", P["logos"], "--in", cur, "--out", out,
                                      "--gain-db", str(sfx.get("gain_db", -9)), "--report", os.path.join(work, "sfx-events.json"),
                                      "--workdir", os.path.join(work, "sfx_work")]
        if sfx.get("no_ducking"): cmd.append("--no-ducking")
        mus = sfx.get("music")
        if mus and mus.get("file"):
            mf = mus["file"] if os.path.isabs(mus["file"]) else os.path.join(work, mus["file"])
            cmd += ["--music", mf, "--music-db", str(mus.get("gain_db", -20)), "--music-fade-in", str(mus.get("fade_in", 1.5)), "--music-fade-out", str(mus.get("fade_out", 2.5))]
            if mus.get("duck") is False: cmd.append("--no-music-duck")
        sh(cmd)
        bus = os.path.join(work, "sfx_work", "sfx_bus.wav")
        if os.path.isfile(bus):
            t = subprocess.run([FFMPEG, "-v", "info", "-i", bus, "-af", "ebur128=peak=true", "-f", "null", "-"], stderr=subprocess.PIPE).stderr.decode()
            lines = [l.strip() for l in t.splitlines() if l.strip().startswith(("I:", "Peak:"))]
            log("bus SFX: %s" % " ".join(lines[-2:]))
        cur = out
    else:
        shutil.copyfile(cur, P["dest"] + ".partial.mp4"); cur = P["dest"] + ".partial.mp4"
    _assert_av_equal(cur, "final A/V")
    if quality != "high":
        fdir = os.path.join(work, "draft_frames"); os.makedirs(fdir, exist_ok=True)
        shots = json.load(open(P["shots"], encoding="utf-8"))["shots"]
        for s_ in shots:
            for t in (s_["start"] + 0.12, (s_["start"] + s_["end"]) / 2.0, s_["end"] - 0.12):
                subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "%.3f" % t, "-i", cur, "-frames:v", "1", os.path.join(fdir, "f_%06.2f.png" % t)])
        log("rascunho (estilo dinamico) em %s; frames dos shots em %s" % (cur, fdir)); return cur
    val = os.path.join(work, "validation.json")
    p = subprocess.run(script("validate_output.py") + [cur, "--plan", P["plan"], "--frames-dir", os.path.join(work, "validation"), "--json-only"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    open(val, "wb").write(p.stdout)
    try:
        d = json.loads(p.stdout.decode("utf-8", "replace"))
        log("validacao: %s | erros: %s | avisos: %s" % ("APROVADO" if not d.get("errors") else "REPROVADO", d.get("errors"), [w[:80] for w in d.get("warnings", [])]))
        if d.get("errors"):
            raise SystemExit("validacao reprovou; corrija e rode render de novo")
    except json.JSONDecodeError:
        raise SystemExit("validate_output sem JSON: %s" % p.stderr.decode("utf-8", "replace")[-500:])
    # sincronia: medida na BASE (o compose e quadro a quadro; o rastreador de boca se perde na tela dividida)
    master = plan.get("source", {}).get("path") or job.get("_source")
    q = subprocess.run(script("av_sync_check.py") + ["--final", base_part, "--master", master, "--plan", P["plan"], "--max", "0.12",
                                                      "--report", os.path.join(work, "av-sync.json")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for line in q.stdout.decode("utf-8", "replace").splitlines()[-3:]:
        log("   " + line)
    if q.returncode != 0:
        raise SystemExit("sincronia A/V reprovou na base (av_sync_check); nao entregue.")
    log("render OK (estilo dinamico) -> %s (ainda .partial; 'deliver' promove)" % cur)
    return cur


def stage_draft(work, job):
    P = paths(work, job)
    if job.get("shots"):
        return _render_shots(work, job, "draft")
    build_plan(work, job, "draft")
    out = os.path.join(work, "draft.mp4")
    shutil.rmtree(os.path.join(work, "render_draft"), ignore_errors=True)
    sh(script("render_edit.py") + ["--plan", P["plan"], "--out", out, "--workdir", os.path.join(work, "render_draft")])
    part = out + ".partial.mp4"
    fdir = os.path.join(work, "draft_frames"); os.makedirs(fdir, exist_ok=True)
    dur = float(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", part],
                               stdout=subprocess.PIPE).stdout.decode().strip() or 0)
    times = [0.15, 0.9, 1.6] + [round(dur * k / 10.0, 2) for k in range(1, 10)] + [max(0.2, dur - 0.5)]
    for t in times:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", str(t), "-i", part, "-frames:v", "1", os.path.join(fdir, "f_%06.2f.png" % t)])
    log("rascunho em %s; frames em %s (olhe antes do render alto)" % (part, fdir))


def _av_lengths(path):
    """v3.5: duracao do video (quadros/fps) e do audio DECODIFICADO (amostras). Duracao de container
    ou de pacote nao serve: o muxer esconde buraco esticando o pacote anterior."""
    o = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=nb_frames,r_frame_rate", "-of", "json", path], stdout=subprocess.PIPE).stdout
    st = (json.loads(o.decode() or "{}").get("streams") or [{}])[0]
    num, den = (st.get("r_frame_rate") or "24/1").split("/")
    vdur = int(st.get("nb_frames") or 0) / (float(num) / float(den or 1))
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    return vdur, len(raw) / 2.0 / 48000.0


def _assert_av_equal(path, label, tol=0.05):
    v, a = _av_lengths(path)
    log("%s: video %.3f s | audio decodificado %.3f s | diferenca %+.3f s" % (label, v, a, a - v))
    if abs(a - v) > tol:
        raise SystemExit("%s: audio e video com duracoes diferentes (%+.3f s). Isso e voz dessincronizada; "
                         "a fonte (master) ou a cadeia de audio perdeu amostras. Nao siga." % (label, a - v))


def stage_render(work, job):
    P = paths(work, job)
    if job.get("shots"):
        return _render_shots(work, job, "high")
    build_plan(work, job, job.get("quality", "high"))
    sh(script("brand_logos.py") + ["plan", "--work", work, "--plan", P["plan"]], check=False)
    plan = json.load(open(P["plan"], encoding="utf-8"))
    events = []
    if os.path.isfile(P["logos"]):
        events = json.load(open(P["logos"], encoding="utf-8")).get("events", [])
    plan["brand_logos"] = events
    if events:
        plan["output"]["crf"] = 14   # intermediario: brand_logos render grava o final em crf 18
    plan.setdefault("notes", []).append("pipeline v3.0: render -> logos -> sfx -> validate")
    json.dump(plan, open(P["plan"], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sh(script("render_edit.py") + ["--plan", P["plan"], "--validate-only"])
    inter = os.path.join(work, "render_hi.mp4")
    shutil.rmtree(os.path.join(work, "render_hi"), ignore_errors=True)
    for f in (inter + ".partial.mp4", P["dest"] + ".partial.mp4", os.path.join(work, P["base"] + "_semSFX.partial.mp4")):
        if os.path.exists(f):
            os.remove(f)
    sh(script("render_edit.py") + ["--plan", P["plan"], "--out", inter, "--workdir", os.path.join(work, "render_hi")])
    cur = inter + ".partial.mp4"
    _assert_av_equal(cur, "render_hi A/V")            # v3.5: portao 1 (regra 18/19)
    if events:
        shutil.rmtree(os.path.join(work, "logos_work"), ignore_errors=True)
        out = os.path.join(work, P["base"] + "_semSFX.partial.mp4")
        sh(script("brand_logos.py") + ["render", "--events", P["logos"], "--in", cur, "--out", out, "--workdir", os.path.join(work, "logos_work")])
        cur = out
    sfx = job.get("sfx", {})
    if sfx is not False and sfx.get("enabled", True):
        out = P["dest"] + ".partial.mp4"
        cmd = script("sfx_mix.py") + ["--plan", P["plan"], "--events", P["logos"], "--in", cur, "--out", out,
                                      "--gain-db", str(sfx.get("gain_db", -9)), "--report", os.path.join(work, "sfx-events.json"),
                                      "--workdir", os.path.join(work, "sfx_work")]
        if sfx.get("no_ducking"):
            cmd.append("--no-ducking")
        mus = sfx.get("music")                      # v3.1: trilha de fundo {"file", "gain_db", "fade_in", "fade_out", "duck"}
        if mus and mus.get("file"):
            mf = mus["file"] if os.path.isabs(mus["file"]) else os.path.join(work, mus["file"])
            cmd += ["--music", mf, "--music-db", str(mus.get("gain_db", -20)),
                    "--music-fade-in", str(mus.get("fade_in", 1.5)), "--music-fade-out", str(mus.get("fade_out", 2.5))]
            if mus.get("duck") is False:
                cmd.append("--no-music-duck")
        sh(cmd)
        for label, name in (("bus SFX", "sfx_bus.wav"), ("bus TRILHA (duckada)", "music_bus.wav")):
            bus = os.path.join(work, "sfx_work", name)
            if os.path.isfile(bus):
                t = subprocess.run([FFMPEG, "-v", "info", "-i", bus, "-af", "ebur128=peak=true", "-f", "null", "-"], stderr=subprocess.PIPE).stderr.decode()
                lines = [l.strip() for l in t.splitlines() if l.strip().startswith(("I:", "Peak:"))]
                log("%s: %s" % (label, " ".join(lines[-2:])))
        cur = out
    else:
        shutil.copyfile(cur, P["dest"] + ".partial.mp4"); cur = P["dest"] + ".partial.mp4"
    val = os.path.join(work, "validation.json")
    p = subprocess.run(script("validate_output.py") + [cur, "--plan", P["plan"], "--frames-dir", os.path.join(work, "validation"), "--json-only"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    open(val, "wb").write(p.stdout)
    try:
        d = json.loads(p.stdout.decode("utf-8", "replace"))
        log("validacao: %s | erros: %s | avisos: %s" % ("APROVADO" if not d.get("errors") else "REPROVADO", d.get("errors"), [w[:80] for w in d.get("warnings", [])]))
        if d.get("errors"):
            raise SystemExit("validacao reprovou; corrija o plano e rode render de novo")
    except json.JSONDecodeError:
        raise SystemExit("validate_output sem JSON: %s" % p.stderr.decode("utf-8", "replace")[-500:])
    # v3.5: portao 2 -- sincronia A/V medida no arquivo FINAL contra o master (regra 19). O
    # validate_output aprovou um video com +0,42 s de voz adiantada; so este mapa pega isso.
    _assert_av_equal(cur, "final A/V")
    master = plan.get("source", {}).get("path") or job.get("_source")
    q = subprocess.run(script("av_sync_check.py") + ["--final", cur, "--master", master, "--plan", P["plan"],
                                                      "--max", "0.12", "--report", os.path.join(work, "av-sync.json")],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for line in q.stdout.decode("utf-8", "replace").splitlines():
        log("   " + line)
    if q.returncode != 0:
        raise SystemExit("sincronia A/V reprovou (av_sync_check); nao entregue. Veja av-sync.json.")
    log("render OK -> %s (ainda .partial; 'deliver' promove)" % cur)


def influencer_ref(work, job):
    """Foto de referencia do influencer (job.influencer = nome ou id) via API do influencIA --
    plano B quando o projeto foi apagado do sistema (aconteceu 01/09: 404 no id do Fable)."""
    name = job.get("influencer")
    if not name:
        return None
    dest = os.path.join(work, "influencer_ref.jpg")
    if os.path.isfile(dest):
        return dest
    try:
        sys.path.insert(0, HERE)
        import influencia_fix_part as infl
        env = infl.load_env(); api = infl.Api(env)
        infs = api._req("GET", "/influencers")
        infs = infs.get("influencers", infs) if isinstance(infs, dict) else infs
        hit = [i for i in infs if i.get("id") == name or name.lower() in (i.get("name") or "").lower()]
        if not hit or not hit[0].get("referenceImageUrl"):
            return None
        infl.download(hit[0]["referenceImageUrl"], dest)
        job["_influencer_name"] = hit[0].get("name")
        return dest
    except BaseException as e:
        log("referencia do influencer indisponivel: %s" % str(e)[:120])
        return None


def project_alive(job):
    proj = job.get("influencia_project")
    if not proj:
        return False
    try:
        sys.path.insert(0, HERE)
        import influencia_fix_part as infl
        env = infl.load_env(); api = infl.Api(env)
        p = infl.find_project(api, proj)
        return bool(p and p.get("id"))
    except BaseException as e:
        log("projeto do influencIA indisponivel (%s) -> usando referencia do influencer e a transcricao" % str(e)[:100])
        return False


def stage_assets(work, job):
    P = paths(work, job)
    cov = job.get("cover") or {}
    os.makedirs(P["capa_dir"], exist_ok=True)
    proj = job.get("influencia_project") if project_alive(job) else None
    ref = cov.get("ref") or (None if proj else influencer_ref(work, job))
    for mood in cov.get("moods", ["studio_haze", "void_light"]):
        out = os.path.join(P["capa_dir"], "capa_%s.png" % mood)
        if os.path.exists(out):
            log("capa %s ja existe" % mood); continue
        cmd = script("make_cover.py") + ["--headline", cov.get("headline", job["name"]), "--mood", mood, "--out", out,
                                         "--keep-raw", os.path.join(P["capa_dir"], "sem_texto_%s.png" % mood)]
        if cov.get("logo"):
            cmd += ["--logo", cov["logo"]]
        if cov.get("accent_color"):                  # v3.5: override da cor da marca (#hex ou none)
            cmd += ["--accent-color", cov["accent_color"]]
        if proj:
            cmd += ["--project", proj]
        elif ref:
            cmd += ["--ref", ref, "--title", job["name"]]
        else:
            log("sem projeto no influencIA nem foto de referencia (cover.ref / influencer) -> capa pulada"); break
        sh(cmd, check=False)
    if not os.path.exists(P["caption"]):
        cmd = script("make_caption.py") + ["--out", P["caption"]]
        if proj:
            cmd += ["--project", proj]
        else:
            cmd += ["--title", job["name"], "--words", P["words"]]
            who = job.get("_influencer_name") or job.get("influencer")
            if who:
                cmd += ["--influencer", who]
            src = job.get("source_text")
            if src and os.path.isfile(os.path.join(work, src)):
                cmd += ["--source", os.path.join(work, src)]
        sh(cmd, check=False)
    if os.path.exists(P["caption"]):
        log("legenda: " + open(P["caption"], encoding="utf-8").read().strip().replace("\n", " / ")[:300])
    log("assets OK -> olhe as capas em %s e escolha (cover.pick no job.json)" % P["capa_dir"])


def stage_deliver(work, job, overwrite):
    P = paths(work, job)
    part = P["dest"] + ".partial.mp4"
    val = os.path.join(work, "validation.json")
    if os.path.exists(part):
        ok = False
        try:
            ok = not json.load(open(val, encoding="utf-8")).get("errors")
        except Exception:
            pass
        if not ok:
            raise SystemExit("sem validacao aprovada do .partial; rode 'render' antes")
        shutil.move(part, P["dest"])
    if not os.path.exists(P["dest"]):
        raise SystemExit("video final nao existe: %s" % P["dest"])
    cov = job.get("cover") or {}
    pick = cov.get("pick") or (cov.get("moods") or ["studio_haze"])[0]
    cover = os.path.join(P["capa_dir"], "capa_%s.png" % pick)
    cmd = script("deliver.py") + ["--name", job["name"], "--video", P["dest"], "--project-dir", work]
    if os.path.exists(cover):
        cmd += ["--cover", cover]
        for f in sorted(glob.glob(os.path.join(P["capa_dir"], "capa_*.png"))):
            if f != cover:
                cmd += ["--extra", f]
        raw = os.path.join(P["capa_dir"], "sem_texto_%s.png" % pick)
        if os.path.exists(raw):
            cmd += ["--extra", raw]
    if os.path.exists(P["caption"]):
        cmd += ["--caption", P["caption"]]
    if overwrite:
        cmd.append("--overwrite")
    sh(cmd)


def main():
    ap = argparse.ArgumentParser(description="EditClean: pipeline por estagios (job.json)")
    ap.add_argument("--work", required=True)
    ap.add_argument("stage", choices=["prep", "draft", "render", "assets", "deliver", "all"])
    ap.add_argument("--overwrite", action="store_true", help="deliver: sobrescrever a pasta no Desktop")
    args = ap.parse_args()
    work = os.path.abspath(args.work)
    job = load_job(work)
    if args.stage in ("draft", "render", "assets", "deliver") and not job.get("_source"):
        raise SystemExit("rode 'prep' primeiro")
    if args.stage == "prep":
        stage_prep(work, job)
    elif args.stage == "draft":
        stage_draft(work, job)
    elif args.stage == "render":
        stage_render(work, job)
    elif args.stage == "assets":
        stage_assets(work, job)
    elif args.stage == "deliver":
        stage_deliver(work, job, args.overwrite)
    elif args.stage == "all":
        stage_prep(work, job); job = load_job(work)
        stage_render(work, job); stage_assets(work, job); stage_deliver(work, job, args.overwrite)


if __name__ == "__main__":
    main()
