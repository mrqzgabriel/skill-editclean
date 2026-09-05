#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Baixa as partes atuais de um projeto do influencIA para uma pasta local + project_meta.json."""
import json
import os
import sys

SKILL_SCRIPTS = "/Users/gabriel/.claude/skills/editclean/scripts"
sys.path.insert(0, SKILL_SCRIPTS)
import influencia_fix_part as ifp  # reaproveita Api, load_env, find_project, download

PROJECT = sys.argv[1]
PARTS_DIR = sys.argv[2]
os.makedirs(PARTS_DIR, exist_ok=True)

# respelling fonetico na copy do sistema (pedido do Gabriel 03/09: "escreva Open-ai...") -> a
# legenda continua com a grafia certa: project_meta.json e a "verdade" do fix_transcript.py
DISPLAY = [("Antrópic", "Anthropic"), ("Antrop", "Anthropic"),
           # v3.4 (04/09, GPT-6 Astra): "St" inicial saia "Sp" -> vogal de apoio;
           # "noventa e dois" saia "noventa do dois" -> funde a conjuncao
           ("Estárgueit", "Stargate"), ("novêntai", "noventa e"),
           # v3.3: vogal fechada (o "o" saia como "ó" aberto)
           ("anteriôres", "anteriores"), ("tôkens", "tokens"), ("ôpinião", "opinião"),
           ("funciônais", "funcionais"), ("prôjetos", "projetos"), ("môdelo", "modelo"),
           ("jôgo", "jogo"), ("fôram", "foram"), ("prômpt", "prompt"), ("Open-ai", "OpenAI"), ("Cúrrsor", "Cursor"), ("Cúr-sor", "Cursor"), ("Cúrsor", "Cursor"),
           ("gigabaites", "gigabytes"), ("terabaite", "terabyte"), ("i-á", "IA"), ("tôquen", "token"),
           ("quinhêntos", "quinhentos"), ("duzêntos", "duzentos"), ("setênta", "setenta"), ("trezêntos", "trezentos"),
           ("Spêis Écs", "SpaceX"), ("dôze", "doze")]


def display_text(t):
    for a, b in DISPLAY:
        t = t.replace(a, b)
    return t


DOWNLOAD = "--no-download" not in sys.argv

env = ifp.load_env()
api = ifp.Api(env)
proj = ifp.find_project(api, PROJECT)
ifp.log("projeto: %s | id: %s | influencer: %s" % (proj.get("title"), proj.get("id"), (proj.get("influencer") or {}).get("name")))

meta_parts = []
for cp in sorted(proj.get("copyParts", []), key=lambda c: c["partNumber"]):
    n = cp["partNumber"]
    vp = cp.get("videoPart") or {}
    url = vp.get("finalVideoUrl")
    entry = {
        "partNumber": n,
        "text": display_text(cp["text"]),
        "text_spoken": cp["text"],
        "copy_part_id": cp["id"],
        "video_part_id": vp.get("id"),
        "status": vp.get("status"),
    }
    if not url:
        ifp.log("parte %d: SEM VIDEO FINAL (status=%s)" % (n, vp.get("status")))
        meta_parts.append(entry)
        continue
    dest = os.path.join(PARTS_DIR, "parte%d.mp4" % n)
    if not DOWNLOAD:
        entry["file"] = os.path.basename(dest)
        meta_parts.append(entry)
        continue
    ifp.download(url, dest)
    size = os.path.getsize(dest)
    ifp.log("parte %d: baixada (%d bytes) -> %s" % (n, size, dest))
    entry["file"] = os.path.basename(dest)
    entry["bytes"] = size
    meta_parts.append(entry)

out = {
    "project_id": proj["id"],
    "title": proj.get("title"),
    "influencer": (proj.get("influencer") or {}).get("name"),
    "parts": meta_parts,
}
meta_path = os.path.join(os.path.dirname(PARTS_DIR.rstrip("/")), "project_meta.json")
json.dump(out, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
ifp.log("project_meta.json em %s" % meta_path)
print(json.dumps({"project_id": proj["id"], "title": proj.get("title"), "parts": len(meta_parts)}))
