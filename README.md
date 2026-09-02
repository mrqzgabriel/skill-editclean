# skill-editclean

Skill do Claude Code que edita um vídeo aplicando o estilo do "Video referencia":
jump cuts dentro do mesmo enquadramento, legendas palavra a palavra com duas famílias
tipográficas, zooms sutis, inserções gráficas reais, logo oficial animado quando a fala cita
uma empresa, sound design nos eventos de motion e grading quente discreto.

Feita para vídeo vertical falado (VSL, Reels, TikTok), inclusive vídeo que chega em trechos
(clipes do Veo/influencIA) — com correção de pronúncia na origem.

**v3.0 (01/09/2026)** — pipeline por estágios, transcrição guiada pela cópia, legenda com
dinheiro em dígitos, fonemas para conferir pronúncia, prints via Playwright, biblioteca de SFX
dentro da skill (45 efeitos Mixkit, licença livre) e validador com fontes reais.

---

## Instalar em outro PC

```bash
git clone https://github.com/mrqzgabriel/skill-editclean.git ~/.claude/skills/editclean
```

A skill fica disponível como `/editclean` no Claude Code.

### Dependências

| O quê | Como instalar | Para quê |
|---|---|---|
| ffmpeg + ffprobe | `brew install ffmpeg` (ou binários em `~/.local/tools/`) | tudo |
| faster-whisper | `pip3 install --user faster-whisper` | legendas com timestamp por palavra; corte das partes |
| Pillow | `pip3 install --user Pillow` | medir largura das legendas, capa, perfis de SFX |
| opencv-python-headless | `pip3 install --user opencv-python-headless` | localizar o rosto (altura da legenda, capa) |
| torch + transformers *(opcional)* | `pip3 install --user torch transformers` | fonemas IPA (`phonemes.py`, `check_pron.py`, `influencia_fix_part.py pron`); baixa ~1,2 GB de modelo na 1ª vez |
| Node ≥ 18 + Playwright em algum projeto *(opcional)* | `playwright_dir` no `.credentials.json` | prints reais de páginas (`shot_page.py`); usa o Chrome do sistema |
| Google Chrome | — | rasterizar logotipos oficiais; fallback de prints |
| scipy *(opcional)* | `pip3 install --user scipy` | só para reanalisar o vídeo de referência |

### Credenciais

O arquivo `.credentials.json` **não está no repositório** (é ignorado de propósito).
Crie-o na raiz da skill:

```bash
cat > ~/.claude/skills/editclean/.credentials.json <<'EOF'
{
  "OPENAI_API_KEY": "sk-...",
  "apify_token": "apify_api_...",
  "influencia_env": "/caminho/para/influencIA/.env",
  "influencia_api": "https://.../api",
  "playwright_dir": "/caminho/para/um/projeto/com/node_modules/playwright"
}
EOF
chmod 600 ~/.claude/skills/editclean/.credentials.json
```

- `OPENAI_API_KEY` — whisper-1 (conferência de pronúncia por parte), gpt-5.5 (legenda do post)
  e último recurso de transcrição. Com o faster-whisper instalado, a transcrição não precisa dela.
- `apify_token` — busca de imagens (Google Images via Apify). Plano FREE estoura fácil; o plano B
  são prints reais de páginas oficiais com `shot_page.py`.
- `influencia_env` / `influencia_api` — para o `influencia_fix_part.py` (LOGIN/SENHA do `.env`).
- `playwright_dir` — pasta de um projeto que tenha `node_modules/playwright` (não precisa baixar
  navegador: usa o Chrome instalado).

Também funciona por variável de ambiente: `OPENAI_API_KEY`, `APIFY_TOKEN`, `INFLUENCIA_ENV`,
`INFLUENCIA_API`, `PLAYWRIGHT_DIR`.

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
/editclean /video/<id> no sistema InfluencIA
```

Flags: `--output`, `--aspect keep|9:16|1:1|16:9`, `--captions auto|off`,
`--quality draft|high`, `--images auto|off`, `--parts auto|off`, `--logos auto|off`,
`--sfx auto|off`, `--overwrite`.

### Pipeline (v3.0)

```
job.json ─► pipeline.py prep     concat_parts (ignora backups) → analyze → subject → transcribe
                                  → fix_transcript (cópias como verdade) → anchor_overlays
                                  → build_plan rascunho → lista de blocos → validate-only
           pipeline.py draft    render crf 30 + frames para olhar
           pipeline.py render   build_plan alta → brand_logos plan → render crf 14 → logos crf 18
                                  → sfx_mix (bus medido) → validate_output (fontes reais)
           pipeline.py assets   make_cover (moods) + make_caption
           pipeline.py deliver  mv do .partial aprovado + pasta no Desktop com projeto/
```

Antes do `prep`, se o vídeo veio do influencIA:

```
influencia_fix_part.py check   whisper-1 × cópia (números ignorados; pra/para tolerado)
influencia_fix_part.py pron    fonemas IPA por parte: sotaque inglês, número engolido
influencia_fix_part.py fix     troca a cópia, regenera na produção, reconfere, baixa
```

Só depois de aprovado o `.partial.mp4` vira o arquivo final.

---

## Estrutura

```
SKILL.md                      instruções que o Claude segue
references/
  style-profile.json          todos os parâmetros (fonte operacional)
  style-spec.md               como interpretar os parâmetros (§1–24)
  edit-plan.schema.json       schema do plano de edição
  brand-logos.json            registro de marcas: aliases, fonte OFICIAL do logo, cor
  transcript-fixes.json       grafias que o Whisper erra (cache, Mythos, Anthropic, token…)
  sfx-conventions.json        pesquisa de sound design (níveis, timing) + candidatos
scripts/
  pipeline.py                 orquestrador por estágios (job.json)
  concat_parts.py             vídeo em trechos: corta o ar morto de cada parte e junta
  influencia_fix_part.py      influencIA: check / pron / fix (regenera a parte pela API)
  phonemes.py, check_pron.py  fonemas IPA (wav2vec2) — ouvir sem depender do transcritor
  analyze_video.py            análise de sinal do vídeo
  detect_subject.py           rosto (YuNet) → alturas seguras
  transcribe.py               transcrição com timestamp por palavra
  fix_transcript.py           grafia + tempos da transcrição (cópias como verdade)
  anchor_overlays.py          inserções e ênfases por frases-âncora (sobrevive a regeneração)
  shot_page.py / .cjs         prints reais de páginas (Playwright + Chrome)
  fetch_images_apify.py       busca imagens (Google Images via Apify)
  build_plan.py               monta o plano (blocos fecham no ponto; dinheiro em dígitos)
  render_edit.py              renderiza (ffmpeg)
  brand_logos.py              logo de marca animado (plan / render / fetch)
  sfx_mix.py                  sound design nos eventos do plano, mix abaixo da voz
  profile_sfx.py              perfil acústico de um SFX (para escolher alternativas)
  validate_output.py          checagens no arquivo final (largura de legenda com fontes reais)
  make_cover.py, cover_gemini.cjs   capa cinema
  make_caption.py             legenda do post (gpt-5.5, sem travessão)
  deliver.py                  pasta no Desktop com vídeo + capa + legenda + projeto/
assets/
  fonts/                      Playfair Display (OFL)
  models/                     YuNet (MIT)
  logos/                      logotipos oficiais rasterizados (com .json de origem)
  sfx/                        manifest.json (efeito padrão por categoria) + library/ (45 Mixkit)
_backup_v1/                   estado anterior à v2, só para referência
```

---

## Sobre o perfil de estilo

`references/style-profile.json` é a fonte da verdade. Tem duas camadas:

1. **Medições** do vídeo de referência (294 frames), cada valor com `*_origin`.
2. **`user_overrides`** — decisões do Gabriel depois de ver o resultado. **Prevalecem** e não
   devem ser "corrigidas" de volta.

Overrides atuais: legendas sempre centralizadas e em posição vertical única; nunca cortar
enquanto a pessoa fala; efeitos mais suaves; imagens obrigatórias e só reais; vídeo em trechos
cortado por parte; logo oficial animado no peito (flutuando, glow suave); fade de áudio e tela
preta no fim; sound design nos eventos; dinheiro na legenda em dígitos.

---

## Armadilhas já resolvidas

Estão corrigidas no código e documentadas no `SKILL.md`. Não reintroduza:

- `fps` logo depois de `zoompan` **multiplica os frames**.
- Zoom sutil **treme** sem superamostragem.
- `\fad` no evento inteiro faz **o bloco de legenda piscar**.
- Crossfade sobre fronteira sem silêncio **come fala**.
- `-loop 1` no input de overlay **trava o render**.
- Backup `parteN_v1_*.mp4` na pasta das partes **duplica trechos** (v3.0: ignorado).
- WAV do Mixkit traz **capítulo** que virava stream de texto no mp4 (v2.16: `-map_chapters -1`).
- Transcritor **corrige a pronúncia** sozinho: "saibersegurança" vira "cibersegurança" no
  texto. Só fonema ou ouvido pegam.

---

## Licenças

Uso pessoal. Playfair Display: [OFL](assets/licenses/OFL-PlayfairDisplay.txt). Efeitos sonoros em
`assets/sfx/`: Mixkit Sound Effects Free License (uso comercial permitido, sem atribuição), origem
e URL de cada um em `assets/sfx/library.json`.

> **Aviso sobre imagens:** o `fetch_images_apify.py` busca no Google Images e o `shot_page.py`
> captura páginas de terceiros. Nada disso é Creative Commons. Confira, recorte marcas alheias e
> prefira material próprio em uso comercial.
