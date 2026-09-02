#!/usr/bin/env python3
"""Reconhecimento de FONEMAS (IPA) com wav2vec2 multilingue (facebook/wav2vec2-lv-60-espeak-cv-ft).
Serve para ouvir "como foi dito" sem o transcritor corrigir a pronuncia: 'saibersegurança' vs
'sibersegurança', numeros lidos errado etc.

Uso: python3 phonemes.py <audio.wav|mp4> [inicio fim]  -> imprime a sequencia IPA
     python3 phonemes.py --all partes/parte*.mp4         -> uma linha por arquivo
"""
import sys, os, subprocess, json
import numpy as np

FF = os.path.expanduser("~/.local/tools/ffmpeg")
MODEL = os.environ.get("PHONEME_MODEL", "facebook/wav2vec2-lv-60-espeak-cv-ft")

_model = None
_proc = None


_vocab = None


def load():
    """Sem o tokenizador de fonemas (exige phonemizer/espeak): decodifica o CTC pelo vocab.json."""
    global _model, _proc, _vocab
    if _model is None:
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2FeatureExtractor
        from huggingface_hub import hf_hub_download
        _proc = Wav2Vec2FeatureExtractor.from_pretrained(MODEL)
        _model = Wav2Vec2ForCTC.from_pretrained(MODEL)
        _model.eval()
        vocab = json.load(open(hf_hub_download(MODEL, "vocab.json")))
        _vocab = {v: k for k, v in vocab.items()}
    return _model, _proc


def ctc_decode(ids):
    out, prev = [], None
    for i in ids:
        if i != prev and i in _vocab:
            tok = _vocab[i]
            if tok not in ("<pad>", "<s>", "</s>", "<unk>"):
                out.append(" " if tok == "|" else tok)
        prev = i
    return "".join(out).replace("  ", " ").strip()


def audio16k(path, start=None, end=None):
    cmd = [FF, "-v", "error"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if end is not None and start is not None:
        cmd += ["-t", str(float(end) - float(start))]
    cmd += ["-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def phonemes(path, start=None, end=None):
    import torch
    model, proc = load()
    x = audio16k(path, start, end)
    inputs = proc(x, sampling_rate=16000, return_tensors="pt")
    with torch.no_grad():
        logits = model(inputs.input_values).logits
    ids = torch.argmax(logits, dim=-1)[0].tolist()
    return ctc_decode(ids)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--all":
        for p in args[1:]:
            print(os.path.basename(p), "->", phonemes(p))
    else:
        p = args[0]
        s = float(args[1]) if len(args) > 1 else None
        e = float(args[2]) if len(args) > 2 else None
        print(phonemes(p, s, e))
