#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - shots_plan.py (v4.0, 05/09/2026)

Resolve os SHOTS do job.json (estilo dinamico) em tempos de SAIDA e escreve:
  shots.json     -> lido pelo compose_shots.py (caminhos absolutos, modos, rampas)
  plan_sfx.json  -> copia do plano com uma janela de push + overlay por shot, so para o sfx_mix
                    (whoosh na entrada, impacto no pouso, whoosh na saida; shot 'chain' = corte seco
                    com 'click')

Cada shot no job.json:
  {"id":"C_aerea","mode":"fullpan|split|clip|highlight","path":"...", "from":"palavra","to":"palavra",
   ["from_occurrence":2], ["pad_end":0.3], ["chain":true],   # chain: comeca onde o anterior acaba (corte seco)
   ["start":s,"end":s] (tempos de SAIDA explicitos, em vez de from/to),
   clip: "clip_in", "anchor_x", "zoom":[1,1.06], "fit":"width", "band_cy"
   fullpan: "pan":"lr|rl", "zoom":[1.04,1.10]
   highlight: "marks":[[x0,y0,x1,y1]...] (fracoes da pagina), "focus":[...], "zoom_to":1.4, "band_cy"}
Regras: modos permitidos = split/fullpan/clip/highlight (nada na frente do rosto, regra 20); pelo menos
um split (regra 21); shots nao se sobrepoem (o seguinte e empurrado 0,1 s depois do anterior).
"""
import argparse, copy, json, os, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ALLOWED = ("split", "fullpan", "clip", "highlight")


def log(m): sys.stderr.write("[shots] %s\n" % m)


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip(".,;:!?\"'")


def find(words, phrase, occurrence=1):
    toks = [norm(t) for t in str(phrase).split()]
    n = 0
    for i in range(len(words) - len(toks) + 1):
        if all(norm(words[i + j]["text"]) == toks[j] for j in range(len(toks))):
            n += 1
            if n == occurrence:
                return i, i + len(toks) - 1
    return None


def src_to_out(plan, t):
    """tempo do master -> tempo de saida pelo mapa de segmentos do plano (fora de segmento: o mais proximo)."""
    best = None
    for s in plan["segments"]:
        if s["src_start"] - 1e-6 <= t <= s["src_end"] + 1e-6:
            return s["out_start"] + (t - s["src_start"])
        d = min(abs(t - s["src_start"]), abs(t - s["src_end"]))
        if best is None or d < best[0]:
            best = (d, s)
    s = best[1]
    return s["out_start"] if t < s["src_start"] else s["out_start"] + (s["src_end"] - s["src_start"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True); ap.add_argument("--words", required=True)
    ap.add_argument("--plan", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--plan-sfx", required=True); ap.add_argument("--allow-no-split", action="store_true")
    a = ap.parse_args()
    job = json.load(open(a.job, encoding="utf-8")); words = json.load(open(a.words, encoding="utf-8"))["words"]
    plan = json.load(open(a.plan, encoding="utf-8")); base = os.path.dirname(os.path.abspath(a.job))
    total = float(plan["segments"][-1]["out_start"] + plan["segments"][-1]["src_end"] - plan["segments"][-1]["src_start"])
    out, prev = [], None
    for s in job.get("shots", []):
        s = dict(s); sid = s.get("id", "S%d" % (len(out) + 1)); s["id"] = sid
        if s.get("mode") not in ALLOWED:
            raise SystemExit("shot %s: modo %r proibido/inexistente (regra 20). Use %s" % (sid, s.get("mode"), "/".join(ALLOWED)))
        path = s["path"] if os.path.isabs(s["path"]) else os.path.join(base, s["path"])
        if not os.path.isfile(path):
            raise SystemExit("shot %s: arquivo nao existe: %s" % (sid, path))
        s["path"] = path
        if s.get("chain") and prev is not None:
            st = prev["end"]; s.setdefault("ramp_in", 0.0); prev["ramp_out"] = 0.0
        elif "start" in s:
            st = float(s["start"])
        else:
            f = find(words, s["from"], int(s.get("from_occurrence", 1)))
            if not f: raise SystemExit("shot %s: ancora 'from' nao achada: %r" % (sid, s["from"]))
            st = src_to_out(plan, words[f[0]]["start"]) - float(s.get("lead", 0.0))
        if "end" in s and not s.get("to"):
            en = float(s["end"])
        else:
            g = find(words, s["to"], int(s.get("to_occurrence", 1)))
            if not g: raise SystemExit("shot %s: ancora 'to' nao achada: %r" % (sid, s["to"]))
            en = src_to_out(plan, words[g[1]]["end"]) + float(s.get("pad_end", 0.0))
        if prev is not None and st < prev["end"] + 0.1 and not s.get("chain"):
            log("%s comecava em %.2f, antes do fim de %s (%.2f): empurrado" % (sid, st, prev["id"], prev["end"]))
            st = prev["end"] + 0.1
        en = min(en, total - 0.05)
        if en - st < 1.0:
            raise SystemExit("shot %s: janela curta demais (%.2f s)" % (sid, en - st))
        s["start"], s["end"] = round(st, 3), round(en, 3)
        for k in ("from", "to", "from_occurrence", "to_occurrence", "pad_end", "lead"):
            s.pop(k, None)
        out.append(s); prev = s
        log("%-14s %-9s %6.2f-%6.2f  %s" % (sid, s["mode"], st, en, os.path.basename(path)))
    if out and not any(s["mode"] == "split" for s in out) and not a.allow_no_split:
        raise SystemExit("nenhum shot 'split' (regra 21: pelo menos uma tela dividida por video). Use --allow-no-split para forcar.")
    json.dump({"shots": out}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    q = copy.deepcopy(plan); q.setdefault("push_down", {})["windows"] = []; q["overlays"] = []
    for s in out:
        chain = s.get("ramp_in", 1) == 0.0 and q["overlays"]
        if chain:
            q["overlays"][-1]["end"] = s["start"]          # colado -> sfx_mix da 'click'
            q["overlays"].append({"id": s["id"], "type": "image", "start": s["start"], "end": s["end"] - 0.2,
                                  "params": {"mode": "hard_cut", "entry_ms": 0, "path": s["path"] if s["mode"] != "clip" else os.path.join(HERE, "..", "assets", "logos", "openai.png")}})
            continue
        q["push_down"]["windows"].append({"down_start": s["start"], "up_end": s["end"]})
        q["overlays"].append({"id": s["id"], "type": "image", "start": s["start"] + 0.25, "end": s["end"] - 0.2,
                              "params": {"mode": "push_down", "entry_ms": 250,
                                         "path": s["path"] if s["mode"] != "clip" else os.path.join(HERE, "..", "assets", "logos", "openai.png")}})
    json.dump(q, open(a.plan_sfx, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"shots": len(out), "split": sum(1 for s in out if s["mode"] == "split"),
                      "clips": sum(1 for s in out if s["mode"] == "clip")}))


if __name__ == "__main__":
    main()
