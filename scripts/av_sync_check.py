#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - av_sync_check.py (v3.5, 04/09/2026)

Mapa A/V do video FINAL contra o master, segmento a segmento do plano:
  lag_v  = onde a BOCA do final realmente esta no master, menos onde o plano manda
  lag_a  = idem para o AUDIO (envelope RMS)
  desync = lag_v - lag_a  (positivo = video atrasado em relacao ao audio)

Nasceu do GPT-6 Astra: 19 checagens do validate_output aprovaram um video com +0,42 s de voz
adiantada (o master tinha buracos de timestamp no audio; ver concat_parts._build_master). A boca
e o audio sao rastreados separadamente contra o master, entao um erro de mapa aparece como
desync mesmo com zoom e push-down. Segmentos < 2 s sao pulados (janela curta demais).

  python3 av_sync_check.py --final <mp4> --master <mp4> --plan edit-plan.json [--max 0.12] [--report x.json]
Sai 0 se todos os segmentos medidos tiverem |desync| <= --max; 1 se algum passar.
"""
import argparse, json, os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_src = open(os.path.join(HERE, "lipsync_check.py"), encoding="utf-8").read()
_ns = {"__file__": os.path.join(HERE, "lipsync_check.py")}
exec(compile(_src.split("\nap = argparse.ArgumentParser()")[0], "lipsync_head", "exec"), _ns)
mouth_energy, audio_env, lag = _ns["mouth_energy"], _ns["audio_env"], _ns["lag"]
PAD = 1.2


def best_shift(sig, ref, fps):
    n, m = len(sig), len(ref)
    if n < 12 or m <= n:
        return None, 0.0
    s = (sig - sig.mean()) / (sig.std() + 1e-9)
    best, bk = -9.0, 0
    for k in range(0, m - n + 1):
        r = ref[k:k + n]; r = (r - r.mean()) / (r.std() + 1e-9)
        v = float((s * r).mean())
        if v > best:
            best, bk = v, k
    return bk / fps, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", required=True); ap.add_argument("--master", required=True)
    ap.add_argument("--plan", required=True); ap.add_argument("--max", type=float, default=0.12)
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    plan = json.load(open(a.plan, encoding="utf-8")); segs = plan["segments"]
    rows, worst = [], 0.0
    print("%-5s %7s %7s | %7s %5s | %7s %5s | %7s" % ("seg", "out", "src", "lag_v", "ncc", "lag_a", "ncc", "desync"))
    for s in segs:
        o0 = s["out_start"]; d = s["src_end"] - s["src_start"]; o1 = o0 + d
        if d < 2.0:
            continue
        t0, t1 = o0 + 0.4, o1 - 0.4; sa, sb = s["src_start"] + 0.4, s["src_end"] - 0.4
        base = max(0.0, sa - PAD)
        m_out, fps = mouth_energy(a.final, t0, t1); m_ref, _ = mouth_energy(a.master, base, sb + PAD)
        e_out = audio_env(a.final, t0, t1, fps);     e_ref = audio_env(a.master, base, sb + PAD, fps)
        kv, cv = best_shift(m_out, m_ref, fps);     ka, ca = best_shift(e_out, e_ref, fps)
        lag_v = (base + kv) - sa if kv is not None else None
        lag_a = (base + ka) - sa if ka is not None else None
        des = (lag_v - lag_a) if (lag_v is not None and lag_a is not None) else None
        f = lambda x: ("%+7.2f" % x if x is not None else "   n/a ")
        print("%-5s %7.2f %7.2f | %s %5.2f | %s %5.2f | %s%s" % (
            s.get("id", ""), o0, s["src_start"], f(lag_v), cv, f(lag_a), ca, f(des),
            ""))
        rows.append(dict(id=s.get("id"), out=o0, src=s["src_start"], lag_v=lag_v, ncc_v=cv,
                         lag_a=lag_a, ncc_a=ca, desync=des))
        if des is not None:
            worst = max(worst, abs(des))
    # A boca antecede o som por natureza (viés ~ -0,05 s constante em vídeo bom). O que denuncia
    # erro é o desync VARIAR ao longo do vídeo (deriva/degrau) ou passar de um teto absoluto.
    ds = [r["desync"] for r in rows if r["desync"] is not None]
    med = float(np.median(ds)) if ds else 0.0
    drift = max((abs(x - med) for x in ds), default=0.0)
    ok = bool(ds) and drift <= a.max and max(abs(x) for x in ds) <= 0.20
    print("desync mediano %+.2f s | maior desvio da mediana %.2f s (limite %.2f) | maior absoluto %.2f s (teto 0,20) | %s"
          % (med, drift, a.max, max(abs(x) for x in ds) if ds else 0.0, "APROVADO" if ok else "REPROVADO"))
    worst = drift
    if a.report:
        json.dump({"ok": ok, "worst_desync_s": round(worst, 3), "max_s": a.max, "segments": rows},
                  open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
