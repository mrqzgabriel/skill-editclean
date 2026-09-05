#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - regen_gate.py (v3.1, 03/09)

Regenera uma parte do influencIA ate os FONEMAS passarem num portao, porque os transcritores
normalizam a pronuncia ("quinhetos e dóze" vira "512" no whisper) e so o IPA mostra o erro.

  python3 regen_gate.py --project <id> --part 1 --text "..." --parts-dir "$WORK/partes" \
      --require "doz" --require "ki.{0,4}[ɲŋn]" --reject "(saɪ|seɪ)[sʃ]?(saɪ|seɪ)" --reject "d[ɔɑa]z" \
      --accept gigabaites,gigabytes,gb --tries 3 --tag num

Cada tentativa: influencia_fix_part.py fix (--retries 0) -> IPA da parte inteira (phonemes.py)
-> burned_text_check -> regras. Sai 0 no primeiro take aprovado; 2 se nenhum passou (a ultima
tentativa fica em parteN.mp4; os anteriores em parteN_vK_<tag>.mp4).
"""
import argparse, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def ipa_of(path):
    import phonemes as ph
    return ph.phonemes(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--part", type=int, required=True)
    ap.add_argument("--text", default=None)
    ap.add_argument("--parts-dir", required=True)
    ap.add_argument("--require", action="append", default=[], help="regex que o IPA da parte PRECISA ter")
    ap.add_argument("--reject", action="append", default=[], help="regex que o IPA NAO pode ter")
    ap.add_argument("--accept", default="")
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--tag", default="gate")
    a = ap.parse_args()
    dest = os.path.join(a.parts_dir, "parte%d.mp4" % a.part)
    for k in range(1, a.tries + 1):
        cmd = [sys.executable, os.path.join(HERE, "influencia_fix_part.py"), "fix", "--project", a.project,
               "--part", str(a.part), "--parts-dir", a.parts_dir, "--tag", "%s%d" % (a.tag, k), "--retries", "0"]
        if a.text and k == 1:
            cmd += ["--text", a.text]
        if a.accept:
            cmd += ["--accept", a.accept]
        print("=== tentativa %d ===" % k, flush=True)
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = r.stdout.decode("utf-8", "replace")
        print("\n".join(l for l in out.splitlines() if re.search(r"reconferencia|ouviu|continua errada|terminou como|nova parte", l)), flush=True)
        if not os.path.isfile(dest):
            print("sem parte local; abortando"); return 2
        burned = subprocess.run([sys.executable, os.path.join(HERE, "burned_text_check.py"), dest],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        burned_ok = burned.returncode == 0
        ipa = ipa_of(dest)
        print("ipa: %s" % ipa, flush=True)
        missing = [rx for rx in a.require if not re.search(rx, ipa)]
        hit = [rx for rx in a.reject if re.search(rx, ipa)]
        print("burned=%s faltou=%s rejeitou=%s" % ("ok" if burned_ok else "SUSPEITO", missing, hit), flush=True)
        if burned_ok and not missing and not hit:
            print("GATE_OK parte %d tentativa %d" % (a.part, k), flush=True)
            return 0
    print("GATE_FAIL parte %d depois de %d tentativa(s)" % (a.part, a.tries), flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main())
