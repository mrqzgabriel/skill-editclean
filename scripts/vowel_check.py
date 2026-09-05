#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EditClean - vowel_check.py  (v3.3, 04/09/2026)

Acha palavra em que a voz do Veo/ElevenLabs abre uma vogal que deveria ser FECHADA:
"opinião" saindo "ópinião", "tokens" saindo "tókens", "anteriores" saindo "anterióres".

Por que existe: o `check` (whisper-1) passa liso -- transcritor normaliza a grafia e
nunca escreve "ópinião". O `pron` mede o IPA da PARTE INTEIRA e afoga a palavra no meio
de 8 s de fonemas. Aqui a janela e por PALAVRA, que e onde o erro aparece.

  python3 vowel_check.py partes/parte*.mp4 [--vowel o|e|both] [--report vogais.json]

Leitura do resultado (o script NAO decide, quem decide e voce):
  - `ɔ` numa palavra fora da lista de excecoes = candidato a "o aberto".
  - Confirme com janela larga (o wav2vec2 e MUITO sensivel a janela curta: a mesma
    palavra da `piniɔm` em [0.28-0.94] e `ɔpiniɔŋ` com padding). O padding daqui ja e
    o que funcionou nos testes.
  - Palavra com ó/é ABERTO de verdade em pt-BR esta em ABERTO_OK e nao e marcada.
    Faltando alguma, acrescente la -- e a lista que evita falso positivo.

Correcao: respelling de vogal fechada na copia do influencIA ("tôkens", "ôpinião") +
entrada no mapa DISPLAY do download_parts.py para a legenda manter a grafia certa.
Se reprovar em 2 takes, REESCREVA a frase sem a palavra (regra 15 do SKILL.md).
"""
import argparse
import json
import os
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FF = os.path.expanduser("~/.local/tools/ffmpeg")
PAD_BEFORE = 0.10        # medido: janela curta demais quebra o wav2vec2
PAD_AFTER = 0.12

# Palavras em que o ó/é ABERTO e o certo em pt-BR -- nao marcar.
ABERTO_OK_O = {
    "so", "no", "nos", "po", "avo", "loja", "lojas", "melhor", "melhores", "pior", "piores",
    "historia", "historias", "memoria", "memorias", "relatorio", "relatorios", "escritorio",
    "escritorios", "repositorio", "repositorios", "territorio", "laboratorio", "diretorio",
    "obvio", "proximo", "proxima", "proximos", "proximas", "otimo", "otima", "otimos", "otimas",
    "modico", "logica", "logico", "tecnologia", "tecnologias", "moda", "porta", "portas",
    "morte", "forte", "fortes", "sorte", "nota", "notas", "bola", "hora", "horas", "agora",
    "fora", "gostoso", "corpo", "morro", "erro", "erros", "sozinho", "novo", "nova", "novos",
    "novas", "posso", "poder", "pode", "podem", "sol", "gol", "dolar", "dolares", "apos",
    "atras", "tras", "ate", "voce", "voces", "e", "eh", "esta", "estao", "cafe", "ideia",
    "ideias", "cabecalho", "hipotese", "analise", "analises", "sintese", "problema",
    "problemas", "sistema", "sistemas", "tema", "temas", "ela", "ele", "eles", "elas",
    "aberto", "aberta", "abertos", "abertas", "certo", "certa", "oferta", "ofertas",
    "projeto", "projetos", "objeto", "objetos", "direto", "direta", "efeito", "efeitos",
    "generico", "generica", "genericos", "genericas", "experiencia", "experiencias",
}
ABERTO_OK_E = {
    "e", "eh", "ela", "ele", "eles", "elas", "esta", "estao", "cafe", "ate", "voce", "voces",
    "ideia", "ideias", "hipotese", "analise", "sintese", "problema", "sistema", "tema",
    "aberto", "certo", "oferta", "projeto", "objeto", "direto", "efeito", "generico",
    "generica", "genericas", "experiencia", "experiencias", "ferro", "guerra", "terra",
    "festa", "seta", "meta", "beta", "letra", "letras", "regra", "regras", "pedra",
}


def log(m):
    sys.stderr.write("[vogal] %s\n" % m)


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip(".,;:!?\"'()")


def main():
    ap = argparse.ArgumentParser(description="EditClean: vogal aberta onde deveria ser fechada")
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--vowel", choices=["o", "e", "both"], default="o")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--report", default=None)
    a = ap.parse_args()

    import phonemes as ph
    from faster_whisper import WhisperModel
    m = WhisperModel(a.model, device="cpu", compute_type="int8")

    quer_o = a.vowel in ("o", "both")
    quer_e = a.vowel in ("e", "both")
    achados = []
    for path in a.parts:
        if not os.path.isfile(path):
            log("%s: ausente" % path)
            continue
        wav = path + ".vc.wav"
        subprocess.run([FF, "-v", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", wav],
                       check=True)
        segs, _ = m.transcribe(wav, language="pt", word_timestamps=True, beam_size=5)
        words = [(w.start, w.end, w.word.strip()) for s in segs for w in s.words]
        os.remove(wav)
        base = os.path.basename(path)
        print("\n=== %s ===" % base)
        print("  %s" % " ".join(w[2] for w in words))
        for st, en, txt in words:
            nk = norm(txt)
            if len(nk) < 3:
                continue
            alvo_o = quer_o and "o" in nk and nk not in ABERTO_OK_O
            alvo_e = quer_e and "e" in nk and nk not in ABERTO_OK_E
            if not (alvo_o or alvo_e):
                continue
            ipa = ph.phonemes(path, max(0.0, st - PAD_BEFORE), en + PAD_AFTER)
            marcas = []
            if alvo_o and "ɔ" in ipa:
                marcas.append("O ABERTO")
            if alvo_e and "ɛ" in ipa:
                marcas.append("E ABERTO")
            if not marcas:
                continue
            print("  !! %-16s [%.2f-%.2f]  %s   <<< %s" % (txt, st, en, ipa, " + ".join(marcas)))
            achados.append({"file": base, "word": txt, "start": round(st, 3), "end": round(en, 3),
                            "ipa": ipa, "flags": marcas})

    print("\n########## SUSPEITOS ##########")
    if not achados:
        print("  nenhum")
    for x in achados:
        print("  %-14s %-16s %s" % (x["file"], x["word"], x["ipa"]))
    print("\nConfira um a um: palavra com ó/é aberto CERTO em pt-BR nao e erro (acrescente")
    print("em ABERTO_OK_O / ABERTO_OK_E). Erro de verdade -> respelling de vogal fechada")
    print("na copia (\"tôkens\", \"ôpinião\") + entrada no DISPLAY do download_parts.py.")
    if a.report:
        json.dump(achados, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log("relatorio: %s" % a.report)
    return 1 if achados else 0


if __name__ == "__main__":
    sys.exit(main())
