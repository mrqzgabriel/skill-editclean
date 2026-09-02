#!/usr/bin/env python3
"""Fonemas (IPA) de palavras especificas de uma parte: acha a palavra com faster-whisper (medium),
recorta a janela e roda o wav2vec2 de fonemas. Uso:
   python3 check_pron.py partes/parte7.mp4 cibersegurança Mythos
   python3 check_pron.py partes/parte5.mp4 --span 3.0 6.8   (janela fixa)
"""
import sys, os, json, subprocess, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phonemes as ph

FF = os.path.expanduser("~/.local/tools/ffmpeg")


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not c.isspace() and not unicodedata.combining(c)).strip(".,;:!?")


def words_of(path):
    from faster_whisper import WhisperModel
    wav = path + ".16k.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", wav], check=True)
    m = WhisperModel("medium", device="cpu", compute_type="int8")
    segs, _ = m.transcribe(wav, language="pt", word_timestamps=True, beam_size=5)
    out = [(w.start, w.end, w.word.strip()) for s in segs for w in s.words]
    os.remove(wav)
    return out


def main():
    path = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] == "--span":
        a, b = float(sys.argv[3]), float(sys.argv[4])
        print("%s [%.2f-%.2f] -> %s" % (os.path.basename(path), a, b, ph.phonemes(path, a, b)))
        return
    targets = [norm(t) for t in sys.argv[2:]]
    ws = words_of(path)
    print("transcricao:", " ".join(w[2] for w in ws))
    for t in targets:
        hits = [(i, w) for i, w in enumerate(ws) if norm(w[2]).startswith(t[:6])]
        if not hits:
            print("  %s: nao achei na transcricao" % t)
            continue
        for i, (a, b, txt) in hits:
            a0 = max(0.0, a - 0.12); b0 = b + 0.15
            print("  %-16s [%.2f-%.2f] -> %s" % (txt, a0, b0, ph.phonemes(path, a0, b0)))
    print("  frase inteira ->", ph.phonemes(path))


if __name__ == "__main__":
    main()
