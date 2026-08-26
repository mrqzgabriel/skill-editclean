# skill-editclean

Skill do Claude Code que edita um vídeo aplicando o estilo do "Video referencia":
jump cuts dentro do mesmo enquadramento, legendas palavra a palavra com duas famílias
tipográficas, zooms sutis, inserções gráficas e grading quente discreto.

Feita para vídeo vertical falado (VSL, Reels, TikTok).

---

## Instalar em outro PC

```bash
git clone https://github.com/mrqzgabriel/skill-editclean.git ~/.claude/skills/editclean
```

A skill fica disponível como `/editclean` no Claude Code.

### Dependências

| O quê | Como instalar | Para quê |
|---|---|---|
| ffmpeg + ffprobe | `brew install ffmpeg` | tudo |
| faster-whisper | `pip3 install --user faster-whisper` | legendas com timestamp por palavra |
| Pillow | `pip3 install --user Pillow` | medir largura de linha das legendas |
| scipy *(opcional)* | `pip3 install --user scipy` | só para reanalisar o vídeo de referência |

### Credenciais

O arquivo `.credentials.json` **não está no repositório** (é ignorado de propósito).
Crie-o na raiz da skill:

```bash
cat > ~/.claude/skills/editclean/.credentials.json <<'EOF'
{
  "OPENAI_API_KEY": "sk-...",
  "apify_token": "apify_api_..."
}
EOF
chmod 600 ~/.claude/skills/editclean/.credentials.json
```

- `OPENAI_API_KEY` — só é usada como **último recurso** de transcrição. Com o
  faster-whisper instalado, não é necessária.
- `apify_token` — busca de imagens para as inserções
  ([apify.com](https://apify.com), actor `hooli/google-images-scraper`).

Também funciona por variável de ambiente: `OPENAI_API_KEY`, `APIFY_TOKEN`.

### Fontes

- **Helvetica Neue** vem do macOS (`/System/Library/Fonts/HelveticaNeue.ttc`).
  Em Linux/Windows, ajuste `path_hint` em `references/style-profile.json` ou instale
  uma equivalente (Inter, Arimo, Liberation Sans).
- **Playfair Display Italic** já vem no repositório (`assets/fonts/`, licença OFL).

---

## Como usar

No Claude Code:

```
/editclean "/caminho/do/video.mp4"
```

Flags: `--output`, `--aspect keep|9:16|1:1|16:9`, `--captions auto|off`,
`--quality draft|high`, `--images auto|off`, `--overwrite`.

### Pipeline

```
analyze_video.py    → manifest.json (silêncios, speech_spans, cenas, frames)
transcribe.py       → words.json    (faster-whisper, timestamp por palavra)
build_plan.py       → edit-plan.json (cortes, zooms, legendas, timeline)
render_edit.py      → saída.partial.mp4
validate_output.py  → aprova ou reprova
```

Só depois de aprovado o `.partial.mp4` vira o arquivo final.

---

## Estrutura

```
SKILL.md                      instruções que o Claude segue
references/
  style-profile.json          todos os parâmetros (fonte operacional)
  style-spec.md               como interpretar os parâmetros
  edit-plan.schema.json       schema do plano de edição
scripts/
  analyze_video.py            análise de sinal do vídeo
  transcribe.py               transcrição com timestamp por palavra
  build_plan.py               monta o plano inteiro automaticamente
  render_edit.py              renderiza (ffmpeg)
  validate_output.py          19 checagens no arquivo final
  fetch_images_apify.py       busca imagens (Google Images via Apify)
  fetch_images.py             busca imagens (Creative Commons)
assets/fonts/                 Playfair Display (OFL)
_backup_v1/                   estado anterior à v2, só para referência
```

---

## Sobre o perfil de estilo

`references/style-profile.json` é a fonte da verdade. A v2 tem duas camadas:

1. **Medições** do vídeo de referência — várias feitas frame a frame (294 frames),
   substituindo estimativas erradas do relatório original. Cada valor medido traz o
   campo `*_origin` dizendo de onde veio.
2. **`user_overrides`** — decisões tomadas depois de ver o resultado real.
   **Prevalecem sobre o vídeo de referência** e não devem ser "corrigidas" de volta.

Overrides atuais: legendas sempre centralizadas e em posição vertical única; nunca
cortar enquanto a pessoa fala; efeitos mais suaves; imagens obrigatórias.

---

## Armadilhas já resolvidas

Estão corrigidas no código e documentadas no `SKILL.md`. Não reintroduza:

- `fps` logo depois de `zoompan` **multiplica os frames** (2 s viram 40 s) — o zoompan
  emite PTS na timebase da entrada mas declara `1/fps` na saída.
- Zoom sutil **treme** sem superamostragem: o zoompan arredonda para pixel inteiro.
- `\fad` no evento inteiro faz **o bloco de legenda piscar** a cada palavra.
- Crossfade sobre fronteira sem silêncio **come fala**.
- `-loop 1` no input de overlay **trava o render** para sempre.

---

## Licença

Uso pessoal. A fonte Playfair Display está sob [OFL](assets/licenses/OFL-PlayfairDisplay.txt).

> **Aviso sobre imagens:** o `fetch_images_apify.py` busca no Google Images. O que vem
> de lá **não é Creative Commons** e provavelmente tem direitos autorais. Confira,
> recorte marcas de terceiros e prefira material próprio em uso comercial.
