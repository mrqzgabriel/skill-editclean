---
name: editclean
description: Edita um vídeo aplicando o estilo do "Video referencia" — jump cuts dentro do mesmo enquadramento, legendas palavra a palavra com duas famílias tipográficas, zooms sutis, inserções gráficas reais, grading quente discreto, logo oficial animado quando a fala cita uma empresa (Claude, OpenAI, Google…), sound design nos eventos de motion e, quando o vídeo chega em trechos/partes (clipes do Veo/influencIA, zip com parteN.mp4), corte do ar morto de cada parte antes de juntar; se uma parte do influencIA saiu com palavra pronunciada errada, sotaque inglês ou balbucio, entra no sistema, troca a cópia e regenera a parte na origem. Use quando pedirem para editar um vídeo nesse estilo, "editar as partes/trechos", corrigir pronúncia de um vídeo do influencIA ou "atualizar a skill editclean".
---

# EditClean v3.0

Edita um vídeo aplicando o estilo definido em `references/style-profile.json` e
`references/style-spec.md`. **O objetivo é entregar a pasta completa no Desktop: vídeo + capa +
legenda + projeto/.** Não pare depois de gerar o plano, nem depois do MP4.

O caminho da skill é `~/.claude/skills/editclean` (`$SKILL`). Diretório de trabalho da execução:
o scratchpad da sessão (`$WORK`), nunca `/tmp`.

## Entrega padrão (aprovada pelo Gabriel em 01/09/2026 nos dois vídeos do Fable 5.1)

| # | Etapa | Como | Seção |
|---|---|---|---|
| 0 | vídeo do influencIA: baixar as partes ATUAIS, conferir cópia × áudio (whisper-1), **fonemas** (sotaque inglês, número engolido) e regenerar o que precisar | `influencia_fix_part.py check` / `pron` / `fix` | §1c |
| 1 | `job.json` no `$WORK` (nome, partes, overrides, cópias, inserções por âncora, ênfases, capa) | modelo em §11 | §11 |
| 2 | `prep`: master (ar morto cortado por parte, backups ignorados) → análise → rosto → transcrição → correção guiada pela cópia → âncoras → plano rascunho → **lista de blocos** | `pipeline.py prep` | §1b, §3–6 |
| 3 | imagens REAIS para as inserções (~4/min): prints de páginas oficiais (`shot_page.py`) ou Apify, curadas uma a uma | §5 | §5 |
| 4 | `draft`: render rascunho e frames — olhar composição antes do render alto | `pipeline.py draft` | §7 |
| 5 | `render`: plano alta → logos oficiais → render crf 14 → composição crf 18 → **SFX** → validação com fontes reais | `pipeline.py render` | §7–8 |
| 6 | `assets`: capa cinema (2–3 moods, escolher olhando) + legenda do post (sem travessão) | `pipeline.py assets` | §7d–7e |
| 7 | `deliver`: promove o `.partial` aprovado e cria a pasta no Desktop | `pipeline.py deliver` | §9b |
| 8 | relatório honesto (o que mudou nas partes, imagens e origem, logos, SFX, validação, limitações) | — | §10 |

Cada estágio pode ser repetido: regenerou uma parte → `prep` de novo (âncoras recalculam os
tempos) → `render`. O Claude **olha** entre os estágios; o script não decide relevância de
imagem, palavra de ênfase nem se a voz está certa.

---

## 0. Antes de tudo

Leia `references/style-profile.json` (parâmetros) e `references/style-spec.md` (como
interpretar). **A seção `user_overrides` do perfil vale mais que o vídeo de referência.** São
decisões que o Gabriel já tomou depois de ver o resultado. Não "corrija" de volta.

Regras de comunicação com o Gabriel (aprendidas): ele mexe no influencIA **em paralelo** — reler
o projeto na API antes de agir; conferir pronúncia **transcrevendo e por fonemas**, nunca por
suposição; contar exatamente qual palavra trocou e por quê; sem travessão em copy.

## 1. Interpretar os argumentos

O argumento é o caminho do vídeo, uma pasta/zip com `parteN.mp4`, ou `/video/<id> no sistema
InfluencIA` (busca o projeto pela API e baixa as partes).

| Flag | Valores | Padrão |
|---|---|---|
| `--output` | caminho de destino | ao lado do original |
| `--aspect` | `keep` \| `9:16` \| `1:1` \| `16:9` | `keep` |
| `--captions` | `auto` \| `off` | `auto` |
| `--quality` | `draft` \| `high` | `high` |
| `--images` | `auto` \| `off` | `auto` |
| `--parts` | `auto` \| `off` | `auto` — vídeo em trechos: corta o ar morto de cada parte (§1b) |
| `--logos` | `auto` \| `off` | `auto` — logo animado nas menções de marca (§7b) |
| `--sfx` | `auto` \| `off` | `auto` — sound design nos eventos (§7f) |
| `--overwrite` | (sem valor) | ausente |

Nome padrão de saída: `<nome>_editclean.mp4`. Nunca sobrescrever arquivo existente em silêncio
(`_v2`, `_v3`…).

## 1b. Vídeo em trechos (partes numeradas)

Clipe gerado (Veo/influencIA) tem ~8 s fixos: a fala acaba e o vídeo continua 1–2 s. **Não
concatene cru.** O `concat_parts.py` (regra do `normalizeTrimConcat` do influencIA + proteção
contra decepar sílaba) corta por parte e junta sem re-encode:

```bash
python3 "$SKILL/scripts/concat_parts.py" --dir "<pasta>" --pattern "parte*.mp4" \
  --out "$WORK/master.mp4" --scale 1080:1920 --last-tail-extra 1.4 \
  --report "$WORK/partes_report.json" --overrides "$WORK/partes_overrides.json"
```

| Passo | Regra |
|---|---|
| medir | faster-whisper (palavras) + `silencedetect` −25 dB / 0,15 s |
| começo | silêncio que começa em < 0,05 s e termina até 0,2 s após a 1ª palavra → fim do silêncio − 0,05; senão 1ª palavra − 0,08 |
| fim | última palavra + 0,15 s; se a energia ainda não caiu, anda até o próximo silêncio + 0,05 (máx. 0,6 s) |
| última parte | `--last-tail-extra 1.4` para o fade de encerramento não comer a frase |
| backups | `parteN_v1_<tag>.mp4` na mesma pasta são **ignorados** (v3.0); número repetido aborta |

**Leia a transcrição impressa de cada parte** (regra 12): balbucio de voz gerada ("Oristote
Paracosfinete…") passa pelo Whisper como fala e o corte automático não pega. Override em segundos
locais da parte: `{"parte9.mp4": {"end": 2.28}, "parte10.mp4": {"start": 0.62}}`. Confira as
duas vizinhas (o rabo vaza para o começo da seguinte). Quando o Whisper small "perde" a última
palavra (parte 5: "dólares"), a proteção do fim resolve; se o aviso `sem silencio apos a ultima
palavra` aparecer, confira com `medium` e use override.

## 1c. Vídeo do influencIA: pronúncia se corrige NA ORIGEM

A voz do Veo (com timbre trocado pelo ElevenLabs STS, que **preserva a pronúncia**) erra de três
jeitos: palavra trocada ("derrubar" → "derrugar", "token" → "toque em"), **sotaque inglês** em
palavra ambígua ("cibersegurança" → "saiber", "Mythos" → "mito", nasais "eɪŋ") e **balbucio**
(cópia curta demais para 8 s). Nada disso se conserta na edição. Fluxo, sempre nesta ordem:

**1. Estado real.** `GET /projects/:id` de novo (o Gabriel regenera partes por conta própria):
baixe as partes atuais para `$WORK/partes/`, compare md5 com o que você tinha, grave
`project_meta.json` (cópias por parte — vira a verdade da transcrição em §4).

**2. Detectar, três camadas:**

```bash
python3 "$SKILL/scripts/influencia_fix_part.py" check --project "<id ou título>" --parts-dir "$WORK/partes" --report "$WORK/influencia_check.json"
python3 "$SKILL/scripts/influencia_fix_part.py" pron  --project "<id>" --parts-dir "$WORK/partes" --report "$WORK/influencia_pron.json"
python3 "$SKILL/scripts/check_pron.py" "$WORK/partes/parte7.mp4" cibersegurança Mythos   # IPA de palavras específicas
```

- `check`: whisper-1 (o transcritor do sistema) × cópia, token a token. Números, dinheiro e
  palavras funcionais (do/de/e/pra-para) ficam **fora** — davam falso PRONUNCIA. Classes: `OK`,
  `PRONUNCIA`, `BALBUCIO`, `DIVERGE`.
- `pron`: fonemas IPA (wav2vec2). **Transcritores corrigem a pronúncia sozinhos** —
  "saibersegurança" vira "cibersegurança" no texto; só o fonema pega. Sinais: `saɪb`, `eɪŋ`,
  `ɹ` retroflexo = fonética inglesa; "Mythos" como `mitʊ` sem `s`; "quatro **e** cinquenta" sem o
  `i`. Modelos de chat com áudio (`gpt-audio`) são instáveis (respondem "envie o áudio") — não
  dependa deles. Teste cego útil: clipe de 2 s da palavra em 3–4 transcritores sem dar o roteiro.
- Olhar os dois relatórios lado a lado; decidir por parte.

**3. Decidir a correção** (editorial, sua):
- Palavra trocada → outra palavra de mesmo sentido que **a mesma voz já pronunciou bem** no vídeo
  (Fable: "derrubar" → "quebrar"; "token queimado" → "gastando menos", ecoando "gasto").
- Sotaque inglês em "ciber…" → **"segurança digital"** (o guia de pronúncia do Veo não bastou em 3
  gerações; a troca por português resolveu). No influencIA isso já é automático
  (`SPEAKABLE_TERMS`, memória `influencia-veo-pronuncia-ptbr`); para outro termo novo, acrescente
  lá e regenere.
- Número lido estranho → cópia com o dinheiro completo ("quatro dólares e cinquenta e três" em vez
  de "quatro e cinquenta e três"). A cópia guardada no sistema fica em **dígitos** (US$ 4,53); o
  sistema converte por extenso só ao falar.
- "Mythos" → o Veo diz "mito" em 7 de 7 takes, com dica e com respelling "Mítos". Aceite o take em
  que o whisper-1 leu "Mythos" (`--accept mito,mytho`) e avise.
- Expressão esquisita ("espuma de marketing", "fora do gráfico") → reescrever direto ("não só
  marketing", "na prática"). O prompt de copy do influencIA e o prompt do Gabriel já proíbem.
- `BALBUCIO` → cortar no `--overrides` (regenerar com o mesmo texto repete). Só encher a frase se o
  usuário topar.
- **Não** faça respelling fonético na cópia ("derru-bar"); não mude número, nome nem dado sem dizer.

**4. Regenerar só a parte, pela produção:**

```bash
python3 "$SKILL/scripts/influencia_fix_part.py" fix --project "<id>" --part 7 \
  --text "O Mythos 5.1 entra como versão mais permissiva, mas só para programas verificados de segurança digital e ciências da vida." \
  --parts-dir "$WORK/partes" --tag ciber --retries 1 --accept mito,mytho
```

`PUT /copy-parts/:id` → `POST generate-video` → poll (Veo Lite 2–4 min + troca de voz) →
reconferência whisper-1 → baixa para `parteN.mp4` e guarda a antiga como `parteN_vK_<tag>.mp4`.
**Cada tentativa sobrescreve `final.mp4` no MinIO**: o take bom só existe se foi baixado na hora.
Duas partes podem regenerar em paralelo (dois processos). Depois de `fix`, mova os
`parteN_v*` para `partes_backup/` (o concat os ignora, mas a pasta fica limpa) e **rode `pron`
de novo** na parte nova. Se mexeu no código do influencIA, faça o deploy antes de regenerar e
confirme pelo marcador (`GET /api/version` autenticado); não regenere durante o deploy.

**5. Registrar** no relatório: parte, cópia antiga → nova, tentativas, o que ficou como está e por
quê. Credenciais vêm do `.env` do influencIA via `.credentials.json` — nunca imprima.

## 2. Validar entrada e dependências

Confira `python3`, `ffmpeg`/`ffprobe` (procurados em `PATH`, `~/.local/tools/`, `/opt/homebrew/bin`,
`/usr/local/bin`), `faster_whisper`, `cv2`, `PIL`. Fonemas pedem `torch`+`transformers`
(`pip3 install --user`, modelo de ~1,2 GB na 1ª vez). Prints de página pedem Node e um projeto
com Playwright (`playwright_dir` no `.credentials.json`). Falta algo essencial → diga exatamente
o quê e o comando; **peça autorização antes de instalação global**. O original é somente leitura.

## 3. Analisar

`analyze_video.py` → `manifest.json` (silêncios, `speech_spans`, cenas, transientes, frames);
`detect_subject.py` → `subject.json` (queixo, topo da cabeça, centro do rosto → altura da
legenda, limite das inserções, âncora do punch). **Não escolha alturas na mão.** Inspecione
frames para legenda queimada.

## 4. Transcrever e corrigir

```bash
python3 "$SKILL/scripts/transcribe.py" "$WORK/master.mp4" --out "$WORK/words_raw.json" --language pt
python3 "$SKILL/scripts/fix_transcript.py" "$WORK/words_raw.json" "$WORK/manifest.json" "$WORK/words.json" --copies "$WORK/project_meta.json"
```

faster-whisper (timestamps reais por palavra; a API `whisper-1` colapsa tempos). O
`fix_transcript.py` corrige **só o que o modelo errou ao ouvir**: junções (`5`+`.1`, `50`+`%`),
grafias de `references/transcript-fixes.json` ("Antropi que" → Anthropic, "cash" → cache, "mito"
→ Mythos, "toque em" → token — acrescente o que descobrir), e as **cópias como verdade**: palavra
fora do vocabulário das cópias e parecida (≥ 0,80) vira a grafia da cópia; "para" → "pra" quando
as cópias só usam "pra"; primeira palavra (não funcional) de cada parte fecha a frase anterior
com ponto. Acento **nunca** vem da cópia ("é" ≠ "e"). Tempos: palavra esticada para dentro de
silêncio medido encolhe; inícios a < 0,10 s são reespaçados (senão o `sanitize_times` do
`build_plan` atrasa a palavra seguinte). Leia a lista de correções impressa; **nunca invente
palavra que não está no áudio**. Sem cópias, confira com `medium` frase a frase.

**Dinheiro na legenda em dígitos** (pedido do Gabriel): a voz diz "dez dólares", "quatro dólares e
cinquenta e três"; a legenda mostra **US$ 10**, **US$ 4,53** (`build_plan.normalize_tokens` junta
`N dólares [e NN]`, `N e NN dólares` e o segundo valor de uma comparação "contra 5 e 41"). 50% e
5.1 já vêm em dígitos.

## 5. Imagens reais para as inserções (~4/min)

Só **print de tela real ou fotografia**: nada de mockup, render 3D, arte de IA, composição.
Descarte print com nome + foto de pessoa privada; recorte marcas de terceiros e concorrentes.

**Fonte 1 — página oficial do assunto** (anúncio da empresa, tabela de preços, gráfico de
benchmark). É real, é a fonte, e o Apify FREE estoura o plano (403 "monthly usage hard limit"):

```bash
python3 "$SKILL/scripts/shot_page.py" "https://www.anthropic.com/..." --outdir "$WORK/shots" --stem anuncio          # figuras por elemento
python3 "$SKILL/scripts/shot_page.py" "https://docs.../pricing" --outdir "$WORK/shots" --stem tabela --mode element --selector table --width 760 --dpr 3
```

Rola a página inteira (gráficos que só aparecem no scroll), captura **por elemento** (recorte de
fullPage desloca em página longa), tabela em viewport 760 (texto ~35% maior na caixa). Depois
recorte com PIL (cookie banner, nota de rodapé) e **olhe cada imagem**.

**Fonte 2 — Apify** (`fetch_images_apify.py --per-query 30`, ~85% de descarte; termo concreto).

**Fonte 3 — o próprio usuário**: quando o assunto é o produto dele, peça print do sistema.

Proporção: não pré-recorte em panorâmica; a caixa é dimensionada por janela (16:9 entra
inteira, ~810×570 no push-down; tabela larga 928×400). Imagem vertical (< 1,15) vira cartão
central. Legibilidade no celular: texto do print ≥ ~16 px depois de escalado — se a tabela
ficar miúda, capture em layout mobile. Registre a origem no relatório e o aviso de direitos.

As inserções entram no `job.json` por **frases-âncora** (`anchor_overlays.py`), não por
segundos: `{"id":"OV1","path":"ov/cost_chart.png","from":"menos","to":"preço","why":"…"}`. Regra
de posicionamento: a imagem acompanha o que está sendo dito; evite colidir com o logo animado
(a menção dentro de push-down é pulada pelo `brand_logos`), e não deixe o vídeo "descido" mais
que ~12 s seguidos.

## 6. Plano de edição

`build_plan.py` aplica o perfil e imprime um relatório: fronteiras que preservam a fala (160 ms
de folga, remoção mínima 100 ms, transição dentro do silêncio), ritmo por terços, escalas de zoom
com salto por corte e padrões (punch com volta, punch seguro, push lento), blocos de legenda
(**fecham no ponto**; repartição prefere vírgula e larguras equilibradas; ênfase serifada 18%,
evite palavra > 12 letras — "cibersegurança" não cabe no corpo mínimo), push-down por janela,
cartão central para imagem vertical, fade de encerramento. **Confira a lista de blocos** que o
`prep` imprime e o relatório contra o perfil. Ênfases por texto em `accent_words` do `job.json`
(números, produto, verbo forte, ~18% dos tokens).

`render_edit.py --validate-only` antes de renderizar. Corrija todos os erros.

## 7. Renderizar

`draft` primeiro (crf 30, frames em `draft_frames/`) — pega problema de composição barato.
Depois `render`: `build_plan --quality high` → `brand_logos.py plan` (eventos entram no plano;
`output.crf` 14 no intermediário) → `render_edit.py` → `brand_logos.py render` (crf 18, `-t` igual
ao vídeo) → `sfx_mix.py` → `validate_output.py` **no arquivo com SFX**.

### 7b. Logo de marca em motion design

Menção a empresa/modelo registrado em `references/brand-logos.json` (aliases: claude, fable,
mythos, opus…, openai, chatgpt, google, gemini, meta, microsoft, deepseek, mistral, perplexity)
→ logotipo **oficial** (fonte registrada; sem asset, sem animação, regra 11) sobe de baixo com
overshoot (0,66 s), acende com bloom/halo na cor da marca, flutua ~1 s e sai para cima (0,54 s).
Entra 0,32 s depois da palavra, ≥ 10 s entre animações, pula menção em push-down/cartão/desfoque.
Posição derivada da legenda (faixa 0,74–0,885, `cy` ≈ 0,81, 288 px). Marca nova: acrescente ao
registro com fonte oficial e rode `brand_logos.py fetch <marca>`.

### 7c. Encerramento

`closing: fade_out` (vídeo 1,0 s, áudio 1,3 s) — preferência do Gabriel; a referência termina
seco, **não corrija de volta**. Em trechos, `--last-tail-extra 1.4`.

### 7d. Capa (cinema)

`make_cover.py --project <id> --headline "O *Fable 5.1* CHEGOU 25% MAIS BARATO" --logo claude
--mood <void_light|studio_haze|server_room|city_window>`: imagem sem texto pelo
`gemini-3-pro-image` (pessoa calma, sem cara de bravo, logo oficial aceso na cena) + tipografia
da legenda composta pelo script (Helvetica Neue Bold + Playfair 1,55× na ênfase, na cor do logo),
título **dentro da zona segura do Reels** (queixo → y 1500, largura ≤ 78%). Gere 2–3 moods e
escolha olhando: rosto idêntico e calmo (eliminatório), logo fiel, título legível. Headline no
formato aprovado: frase curta em caixa-alta + produto em Playfair.

### 7e. Legenda do post

`make_caption.py --project <id>` (gpt-5.5, prompt do influencIA, 100–200 caracteres, CTA, ≤ 5
hashtags, **sem travessão**). Leia antes de entregar.

### 7f. Sound design (SFX) — biblioteca dentro da skill

```bash
python3 "$SKILL/scripts/sfx_mix.py" --plan "$WORK/edit-plan.json" --events "$WORK/brand-logos.json" \
  --in "<semSFX>.partial.mp4" --out "<destino>.partial.mp4" --gain-db -14 --report "$WORK/sfx-events.json"
```

Eventos derivados do plano (spec §20, pesquisa em `references/sfx-conventions.json`):

| Momento | SFX (categoria) | Quando | Nível rel. voz |
|---|---|---|---|
| abertura (desfoque resolve) | `riser` curto, pico no assentar | t=0 | −14 |
| logo sobe | `whoosh_in` crescente, pico no topo da subida | 0,4 s antes | −12…−18 |
| logo pousa | `logo_land` (hit macio) + `shimmer` baixo | t_settle | −9 / −20 |
| logo sai | `whoosh_out` (sweep curto) | t_out | −17 |
| vídeo desce (push-down) | `slide` grave, pico no fim da rampa | 0,1 s antes | −17 |
| imagem chega a 100% | `pop` leve | fim do fade | −14 |
| troca seca entre imagens | `click` | no corte | −14 |
| vídeo volta | `slide_back` bem baixo | 0,1 s antes | −21 |
| punch-in | `bass_hit` sutil | no corte | −12…−16 |
| jump cuts comuns / fade final | **nada** | — | — |

Voz manda (sidechain leve); `-c:v copy`; `-map_chapters -1` (WAV traz capítulo). **Biblioteca em
`assets/sfx/`**: `manifest.json` = efeito padrão por categoria (arquivo, ganho, lead, origem,
**licença Mixkit** — uso comercial livre, sem atribuição) e `library/` + `library.json` = 45
efeitos com perfil acústico (duração útil, pico, centro de massa, cauda, bandas) para trocar por
categoria sem baixar nada. Para trocar: edite `manifest.json.default.<categoria>.file` (ou passe
`--library`). Para escolher entre candidatos novos: `profile_sfx.py <arquivos>` — whoosh de entrada
= energia subindo (`energy_cm` > 0,5); pop/click = curto e ataque no começo; bass hit = grave
dominante. O mixer grava `sfx_work/sfx_bus.wav` só com efeitos: **meça** (`ebur128`): bus ≈ −28
LUFS contra −14 da voz, picos −12…−19 dBFS. Se o Gabriel achar alto/baixo, é ganho por categoria
no manifesto e remix em segundos (não re-renderiza).

## 8. Validar

`validate_output.py <com SFX>.partial.mp4 --plan edit-plan.json --frames-dir validation` — 19
checagens; a largura das legendas é **medida com as fontes reais** (v3.0; antes o aviso
`legendas_dentro_do_canvas` era falso positivo). Inspecione os frames. **Nunca declare sucesso
com validação reprovada.**

## 9. Promover, 9b. Entregar

`mv <destino>.partial.mp4 <destino>.mp4` só depois da aprovação. Entrega **sempre** em pasta no
Desktop (`deliver.py` / `pipeline.py deliver`): `<Nome>.mp4`, `<Nome>_CAPA.png`,
`<Nome>_LEGENDA.txt`, capas alternativas, `projeto/` (plano, palavras, overrides, eventos de
logo e SFX, `insercoes/`, `sfx-manifest.json`, `.capa.json`, `.legenda.json`, `job.json`).
Pasta existente vira `(2)` a menos que `--overwrite` (use-o na versão corrigida do mesmo vídeo).
Abra o vídeo para o Gabriel (`open`) quando ele pedir para ver.

## 10. Relatar

Caminho da pasta; duração antes → depois; por parte: o que foi regenerado (cópia antiga → nova,
tentativas, o que ficou como está e por quê); cortes/transições/zooms/blocos; imagens com origem
e aviso de direitos; logos (marca, instante); SFX (quantos, níveis medidos); validação;
limitações honestas (você não ouve: níveis e pronúncia foram medidos, a confirmação final é dele).

## 11. `job.json` (orquestrador)

```json
{
 "name": "Fable 5.1 Chegou 25% Mais Barato",
 "parts_dir": "partes",
 "overrides": {"parte9.mp4": {"end": 2.28}},
 "influencia_project": "59a7affc-3fb9-4623-a5b8-d9e711fe1541",
 "copies": "project_meta.json",
 "overlays": [
  {"id": "OV1", "path": "ov/cost_chart.png", "from": "menos", "to": "preço", "why": "gráfico oficial de custo"},
  {"id": "OV2", "path": "ov/tabela.png", "from": "A sacada", "to": "guardadas", "why": "tabela oficial de preços"}
 ],
 "accent_words": ["5.1", "50%", "gasto", "Anthropic", "US$ 4,53", "Mythos", "IA"],
 "accent_max": 28,
 "cover": {"headline": "O *Fable 5.1* CHEGOU 25% MAIS BARATO", "logo": "claude", "moods": ["void_light", "studio_haze"], "pick": "void_light"},
 "sfx": {"gain_db": -14},
 "quality": "high"
}
```

```bash
python3 "$SKILL/scripts/pipeline.py" --work "$WORK" prep      # olhe blocos e insercoes
python3 "$SKILL/scripts/pipeline.py" --work "$WORK" draft     # olhe draft_frames/
python3 "$SKILL/scripts/pipeline.py" --work "$WORK" render    # ~10 min; validacao no fim
python3 "$SKILL/scripts/pipeline.py" --work "$WORK" assets    # capas + legenda; escolha 'pick'
python3 "$SKILL/scripts/pipeline.py" --work "$WORK" deliver [--overwrite]
```

Vídeo único (não em trechos): `"source": "/caminho/video.mp4"` no lugar de `parts_dir`. Ponha
também `"influencer": "Gabriel Marquez"`: se o projeto for apagado do influencIA no meio do
trabalho (aconteceu em 01/09), `assets` cai sozinho na foto de referência do influencer e na
transcrição para gerar capa e legenda.

---

## Regras invioláveis

1. O vídeo de entrada é **somente leitura**.
2. Escrita atômica: `.partial.mp4` → validar → `mv`.
3. Nunca sobrescrever arquivo existente sem `--overwrite`.
4. Nunca esticar a imagem.
5. **Nunca cortar enquanto a pessoa fala** (160 ms de folga; remoção mínima 100 ms; transição
   dentro do silêncio).
6. Nunca inventar dados, logotipos ou marcas.
7. Nunca adicionar música sem arquivo do usuário. SFX só da biblioteca licenciada (ou arquivo dele).
8. Nunca alterar o sentido das falas.
9. Credenciais só de `.credentials.json`/ambiente e do `.env` do influencIA (§1c). Nunca imprimir.
10. Nunca declarar sucesso sem `validate_output.py` aprovar.
11. Logo só de fonte oficial registrada; nunca redesenhar.
12. Vídeo em trechos: ler a transcrição de cada parte antes de aceitar o corte automático.
13. Pronúncia errada em parte do influencIA se corrige **na origem**; a parte regenerada só entra
    depois de reconferida (whisper-1 **e** fonemas).
14. Cópia de vídeo do influencIA fica em **dígitos** (US$ 4,53, 25%, 5.1); por extenso só ao falar.
15. Não regenerar de novo, por detalhe pequeno, uma parte que o Gabriel acabou de regenerar —
    reportar.

## Notas de implementação (armadilhas já resolvidas — não reintroduza)

- Zoom usa `zoompan`, não `crop`; `fps` depois de `zoompan` multiplica frames
  (`settb=AVTB,setpts=N/fps/TB`); superamostragem 2,5–6× contra tremida; `xfade` exige
  `settb=AVTB`; overlay de imagem sem `-loop 1`; zoom nunca se move em cima do corte.
- Fade da legenda é por palavra (`\alpha` só na palavra nova); `\fad` no evento pisca.
- `setpts` junto com `select` renumera o tempo nas análises.
- Backups `parteN_v*.mp4` na pasta das partes duplicam trechos → ignorados pelo concat.
- WAV do Mixkit traz capítulo → `-map_chapters -1` no mix (senão stream de texto no mp4).
- `gpt-audio` (chat) não serve para julgar pronúncia; transcritores corrigem sozinhos; fonemas sim.
- Apify FREE: 403 "monthly usage hard limit" → `shot_page.py`.
- Chrome headless `--screenshot` não rola a página: conteúdo revelado no scroll fica em branco →
  Playwright.
- Fontes: Helvetica Neue do sistema; Playfair Display em `assets/fonts/` (`fontsdir` no libass).
