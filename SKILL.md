---
name: editclean
description: Edita um vídeo aplicando o estilo do "Video referencia" — jump cuts dentro do mesmo enquadramento, legendas palavra a palavra com duas famílias tipográficas, zooms sutis, inserções gráficas reais, grading quente discreto, logo oficial animado quando a fala cita uma empresa (Claude, OpenAI, Google…), sound design nos eventos de motion e, quando o vídeo chega em trechos/partes (clipes do Veo/influencIA, zip com parteN.mp4), corte do ar morto de cada parte antes de juntar; se uma parte do influencIA saiu com palavra pronunciada errada, sotaque inglês ou balbucio, entra no sistema, troca a cópia e regenera a parte na origem. Use quando pedirem para editar um vídeo nesse estilo, "editar as partes/trechos", corrigir pronúncia de um vídeo do influencIA ou "atualizar a skill editclean".
---

# EditClean v3.5

v3.5 (04/09/2026, "tá muito desincronizado, resolva na raiz"): **a raiz é um salto falso de
timestamp no áudio de cada parte do influencIA.** Cada clipe traz 372 pacotes AAC = 7,915 s de
amostras **contínuas**, carimbadas num fluxo de 8,016 s: um pacote a ~5,1 s ganha duração de
0,102 s (o muxer "estica" o pacote em vez de deixar vazio, então `ffprobe` de duração não vê).
Medido com lipsync por metade nas partes: áudio corrido por amostras casa com a boca (−0,04/−0,04);
honrar o timestamp (silêncio no salto) desalinha a 2ª metade (até −0,42 s). O `concat_parts`
antigo cortava por timestamp (`-ss/-t`) e juntava por cópia, preservando o salto; o `atrim` do
render também corta por timestamp e perdia ~80 ms por parte; o `concat` do render é por amostra,
então o áudio encurtava e a voz adiantava em degraus (+0,42 s no fim). O `sfx_mix -shortest`
ainda cortou o vídeo para o tamanho do áudio e mascarou tudo; 19 checagens do `validate_output`
aprovaram. Correção em três camadas, todas na skill: (1) `concat_parts._build_master` corta no
**grid de quadros**, **recarimba o áudio como contínuo** (`asetpts=N/SR/TB` antes do `atrim`),
completa com silêncio só no fim (`apad`) e junta numa passagem pelo filtro `concat`, um encode;
`_verify_master` **recusa** master cujo áudio decodificado difira do vídeo ou tenha pacote
esticado (regra 18). (2) `pipeline render` tem dois portões: `_assert_av_equal` (duração do
áudio decodificado = vídeo) no `render_hi` e no final. (3) `av_sync_check.py`: mapa boca × áudio
do vídeo FINAL contra o master, por segmento do plano; reprova se o desync variar mais que 0,12 s
ou passar de 0,20 s (§8b, regra 19). **Não** usar `aresample=async` nem inserir silêncio no
salto: testado, erra. Também v3.5: **proibido regenerar só o áudio** de uma parte (§1c, regras
16 e 17) — o `audio` do `influencia_fix_part.py` foi desativado; e o take de entrega passa no
teste cego E no `lipsync_check.py` (que agora mede o total e as duas metades).

v3.4 (04/09/2026, "no 00:27 o áudio não tá sincronizado"): `lipsync_check.py` mede sincronia
labial com a ROI **ancorada nos cantos da boca** (§1c). **Medido e encerrado: a voz do ElevenLabs
JÁ é feita a partir do áudio do Veo e fica colada nele** (+0,025 s, correlação 0,83–0,91 nas 10
partes) — trocar o áudio não muda nada. O que resta medir é a qualidade da boca do Veo, que varia
por take.

v3.3 (04/09/2026, revisão do Gabriel no "Fable 5.1 Enterra o AI Slop", quatro pedidos de uma
vez): `vowel_check.py` para vogal aberta onde devia ser fechada (§1c), número por extenso vira
**dígito** na legenda (§4), corte do ar morto do começo pelo silêncio medido + falso começo
(§1b), cauda da última parte e fade travados na parte muda (§1b, §7c).

v3.2 (04/09/2026, vídeo "Fable 5.1 Enterra o AI Slop"): nome de marca truncado herdado da
transcrição da fonte (§1c), par de logos cai para a 1ª marca sozinha (§7b), espaço de palavra
proporcional ao maior vizinho (§6), último frame da validação pela duração do stream de vídeo (§8).

v3.1 (03/09/2026, vídeo "A OpenAI cortou o Cursor"): par de logos lado a lado (§7b), glow menor
e por marca, cartão central com a legenda colada na imagem (§5), `"skip": true` por parte (§1b),
`burned_text_check.py` para texto queimado pelo Veo (§1c), respelling fonético na copy (§1c).

Edita um vídeo aplicando o estilo definido em `references/style-profile.json` e
`references/style-spec.md`. **O objetivo é entregar a pasta completa no Desktop: vídeo + capa +
legenda + projeto/.** Não pare depois de gerar o plano, nem depois do MP4.

O caminho da skill é `~/.claude/skills/editclean` (`$SKILL`). Diretório de trabalho da execução:
o scratchpad da sessão (`$WORK`), nunca `/tmp`.

## Entrega padrão (aprovada pelo Gabriel em 01/09/2026 nos dois vídeos do Fable 5.1)

| # | Etapa | Como | Seção |
|---|---|---|---|
| 0 | vídeo do influencIA: baixar as partes ATUAIS, conferir cópia × áudio (whisper-1), **fonemas**, **vogal aberta** (`vowel_check.py`), **sincronia labial** (`lipsync_check.py`) e regenerar o que precisar | `influencia_fix_part.py check` / `pron` / `vowel_check.py` / `lipsync_check.py` / `fix` | §1c |
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
| medir | faster-whisper (palavras) + `silencedetect` −25 dB / 0,15 s; **silêncios separados por < 0,08 s viram um só** (v3.3: um clique de 11 ms entre dois silêncios escondia 0,7 s de ar morto) |
| começo | **v3.3**: silêncio medido que começa antes de 0,20 s e passa da 1ª palavra → fim dele − 0,05. O whisper crava a 1ª palavra em 0,00 mesmo quando a fala só começa depois, então quem manda é o silêncio, não o timestamp |
| falso começo | **v3.3**: sílaba solta de < 0,25 s seguida de pausa de ≥ 0,35 s = falso começo, corta até o fim da pausa. Desliga com `--no-false-start` |
| fim | última palavra + 0,15 s; se a energia ainda não caiu, anda até o próximo silêncio + 0,05 (máx. 0,6 s) |
| trava do fim | **v3.3**: o timestamp da última palavra estica até 0,5 s além do áudio real. Nunca deixar mais que 0,28 s de vídeo depois que a energia cai (`TAIL_CLAMP`) |
| última parte | `--last-tail-extra` **0,35** (era 1,4). Ver §7c: 1,4 deixava ~1 s de boca mexendo em silêncio digital |
| backups | `parteN_v1_<tag>.mp4` na mesma pasta são **ignorados** (v3.0); número repetido aborta |
| descartar | `{"parte19.mp4": {"skip": true}}` tira a parte inteira (v3.1: "remova o 'valeu por ficar até o final'") |

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
python3 "$SKILL/scripts/vowel_check.py" "$WORK/partes"/parte*.mp4 --report "$WORK/vogais.json"   # v3.3
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
- `vowel_check.py` (v3.3, 04/09, pedido do Gabriel "tem palavras que tem a letra o pronunciando
  como se fosse ó"): **vogal ABERTA onde devia ser FECHADA**. Nenhuma das duas camadas acima
  pega isso: o `check` não pega porque o transcritor nunca escreve "ópinião", e o `pron` não pega
  porque mede o IPA da PARTE INTEIRA e a palavra afoga em 8 s de fonemas. O `vowel_check` mede
  **por palavra** (janela `−0,10 / +0,12` s, que é a que funciona) e marca `ɔ` fora da lista
  `ABERTO_OK_O` de palavras em que o ó aberto é o certo em pt-BR ("só", "loja", "melhor",
  "relatórios", "repositório", "projetos"…). Sem essa lista o script marcaria meia frase.
- **A janela decide o resultado**: a mesma "opinião" dá `piniɔm` numa janela apertada e
  `ɔpiniɔŋ` com padding. Meça com padding e desconfie de janela curta.
- `lipsync_check.py` (v3.4, 04/09, "no 00:27 o áudio não tá sincronizado"): **sincronia labial**.
  Correlaciona a abertura da boca com o envelope RMS do áudio. Nenhuma camada acima vê isso —
  texto bate, fonema bate, e o `validate_output` só compara comprimento de stream.
  **A ROI TEM que rastrear a boca** (marcos 3 e 4 do YuNet, os cantos). Com ROI fixa o movimento
  de cabeça entra no sinal como ruído e o resultado é lixo: na primeira medição do vídeo do Fable
  a ROI fixa acusou as partes 1, 4 e 5 com 0,3–0,5 s de desvio, eu regenerei três partes à toa, e
  com a ROI rastreada **todas as 10 partes ficaram entre −0,04 e −0,08 s**.
  **Rode nas PARTES DE ORIGEM, não no vídeo editado**: zoom, push-down e o desfoque do cartão
  central estragam o rastreio (a janela do cartão chegou a dar sinal invertido).
  **Medir o clipe inteiro esconde erro local** (v3.5, 04/09): no GPT-6 Astra a parte 5 deu
  −0,04 s no total e **−0,29 s na segunda metade**, que foi o que o Gabriel ouviu ("no segundo 27
  em diante ficou ruim"). O script agora mede o total **e as duas metades** quando você não passa
  `--from/--to/--win`; **reprova o take se qualquer janela passar de 0,10 s**. Compare sempre
  janelas do mesmo tamanho: correlação de meia janela não se compara com a do clipe inteiro.
  Leitura: |atraso| ≤ 0,10 s é bom. **A correlação é o sinal de QUALIDADE**, não o atraso:
  parte boa dá 0,41–0,52; a parte 4 deu 0,20–0,31 em **4 takes diferentes**, com atraso ≈ 0. Isso
  é boca que se mexe na hora certa mas não desenha os fonemas — limitação da geração do Veo
  naquele clipe. Regenerar é loteria: meça os takes e fique com o de maior correlação (guarde
  cada take na hora, o `final.mp4` do MinIO é sobrescrito a cada tentativa).
- **A voz não é o problema, e isso está medido**: o ElevenLabs faz Speech-to-Speech em cima do
  áudio do Veo e fica colado nele — envelope com +0,025 s e correlação 0,83–0,91 nas 10 partes,
  e os inícios de palavra ficam a ≤ 0,08 s. **Não troque o áudio do final pelo do Veo**: é o
  mesmo tempo, só com a voz errada. Cuidado ao comparar: se você baixou o `videoUrl` antes de
  regenerar a parte, está comparando TAKES DIFERENTES e vai achar 0,3 s de desvio que não existe.
- **Para provar que a EDIÇÃO não dessincroniza**: correlacione o áudio de saída com o do master
  usando o mapa `out_start`→`src_start` do plano. Tem que dar 0,000 s em todos os pontos (deu, no
  vídeo do Fable, com correlação 0,93–1,00), inclusive atravessando as três transições.
- Olhar os relatórios lado a lado; decidir por parte.

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
- **Respelling fonético na cópia** (v3.1, pedido do Gabriel em 03/09: "escreva Open-ai, tem que
  escrever de um jeito que o Veo pronuncie direito"): `OpenAI` → `Open-ai`, `Cursor` → `Cúrsor`
  (tônica na 1ª sílaba; sem o acento saía "cursór"), `SpaceX` → `Spêis Écs` (saía "spacséc"),
  `doze` → `dôze` (saía "dózé"). **"Cúrsor" não basta**: o Gabriel ouviu "Cúsor" (r antes do s
  mudo; fonemas `kuːsoɾ`/`usoɾ`). Teste 03/09: **`Cúrrsor`** → `kulsoɾ` (o wav2vec2 marca o r
  retroflexo como "l" = consoante audível entre u e s) ✔; `Cúr-sor` → `kuːsə` ✘. Regra: coda r
  antes de consoante em nome estrangeiro = dobrar o r. O whisper-1 lê "Cursor" nos dois casos, só
  o fonema mostra a diferença — sempre `check_pron` e procure consoante entre a vogal e o s. A legenda **não** herda o respelling: `download_parts.py` grava
  `text` com a grafia certa e `text_spoken` com a fonética (o `fix_transcript` usa `text`).
  Na reconferência passe `--accept openai,open,ai` / `spacex,speis,ecs` (o diff é por token).
- **Vídeo Apple (03/09), mais respellings medidos**: `gigabytes` → Veo diz "gigabits" → `gigabaites` ✔;
  `terabyte` já sai certo. `IA` varia por take (`iaːl` ✔, `jiɑ`/`ja` = "iá" ✘); `i-á` ainda dá glide
  → escrever **"inteligência artificial"** por extenso. `token` → "tóque/TOC" (n mudo) em 2 takes e
  `tôquen` não ajuda → **trocar a palavra** ("não paga por uso"). Números por extenso saem certos.
  **Teste cego decide**: `ffmpeg -ss X -t 2 … .wav` + whisper-1 + faster-whisper medium + small SEM
  roteiro; se os três erram, a voz está errada mesmo (o fonema sozinho confunde em "setenta"/"perfil").
  Mapa `DISPLAY` do `download_parts.py` (respelling → grafia da legenda) precisa da entrada nova.
- **Portão por fonema (`regen_gate.py`, 03/09)**: regenera a parte até o IPA da frase inteira
  passar em `--require`/`--reject` (+ texto queimado). Vídeo Apple: "vinte e seis" saía
  `viŋsaɪsaɪ` (seis-seis), "doze" `dɔz/dɑz` (dózé), "setenta" `sɨsɨpteɪŋtɐ` (se-se-ptenta), "três"
  repetido, "artificial" `fos` (artifocial). Regras que funcionaram: require `doz`, `k[ie]ɪ?[ɲŋn]`
  (quinhêntos), `f[iɪ]s`; reject `(saɪ|seɪ)[sʃ]?(saɪ|seɪ)`, `d[ɔɑa]z`, `f[ouʊɔ]s`, `sɨsɨ|sese`,
  `tɹeɪ.{0,4}tɹeɪ`. **Cuidado com regra larga**: `s[ɨeɛi]s[ɨeɛi]` rejeitava "duzento**s e s**etenta"
  (fim de palavra + "e"); olhe o IPA dos takes rejeitados antes de aceitar o veredito. O script
  deixa o ÚLTIMO take em `parteN.mp4` mesmo reprovado — restaure o aprovado dos `parteN_vK_*.mp4`.
  Números por extenso com acento fechado (`quinhêntos e dôze`, `duzêntos e setênta`) ajudam.
  **"dois mil e vinte e seis" falhou em 5 de 5 takes** ("vinte-ce-seis", IPA `viŋtɨsesseɪʃ`): número ou
  ano que reprova em 2 takes com portão → **reescrever sem o número** ("Este ano, a Apple lançou…")
  e avisar o Gabriel; insistir em respelling só queima tempo e paciência.
- **Nível por parte (`parts_levels.py`, 04/09)**: a voz do ElevenLabs sai com nível diferente por
  take — no vídeo Apple a parte 4 veio 5,7 dB mais alta que as outras e com pico +4,2 dBFS
  ("estourado no segundo 23"). Rode `parts_levels.py partes/parte*.mp4` depois de baixar/regenerar
  (marca |LUFS − mediana| > 2,5 dB ou pico > −1 dBFS) e `--fix` iguala ao LUFS mediano com limitador
  em −1,9 dBTP (vídeo em stream copy; original em `parteN_vK_nivel.mp4`). Fazer ANTES do `prep`.
- **NUNCA regenerar só o áudio** (v3.5, 04/09/2026 — pedido do Gabriel: "eu nao quero que
  regenere apenas o audio, e pra regenerar o trecho. pois se so regenerar o audio vai ficar com a
  voz desincronizada"). O `POST /video-parts/:id/generate-audio` troca a voz mantendo o **vídeo do
  take antigo**: a boca continua desenhando os fonemas da fala velha e a nova não encaixa. O
  subcomando `influencia_fix_part.py audio` foi **desativado** e sai com erro. Voz esquisita,
  palavra trocada, número engolido, vogal aberta: tudo se conserta regenerando a **parte inteira**
  (`fix` ou `regen_gate.py`), que refaz vídeo e voz juntos. Ver a regra 16.
- **Texto queimado pelo Veo** (aleatório por take): rode `burned_text_check.py partes/parte*.mp4`
  em TODO take novo (pixels quase brancos no rodapé; 0,0000 = limpo, ≥ 0,004 = suspeito, olhe o
  frame). Take com texto → regenerar com a mesma cópia (`fix --part N --retries 0`) e checar de novo.
- **Nome de marca truncado vem da FONTE, não do Veo** (v3.2, 04/09): a cópia da parte 1 dizia
  "A Antrop lançou…" e o `originalText` do projeto (transcrição do vídeo do YouTube de origem)
  também dizia "Antrop" — o modelo de copy copiou o erro do transcritor da fonte, e a dica de
  pronúncia do sistema (`PRONUNCIATION_GUIDE`, regex `\bAnthropic\b`) nunca disparou. **Confira o
  `originalText` quando um nome próprio sair estranho**; o `check` passa (whisper-1 "corrige"
  sozinho) e só o teste cego pega. Respelling que resolveu: **`Antrópic`** → IPA `tɹɑpki`, o k
  vira sílaba ("Antróp-que") — pronúncia que já foi entregue e aceita antes, e que o
  `transcript-fixes.json` já mapeia (`antropi que` → Anthropic). Grafias novas registradas lá:
  `anthrop que`, `antropica`, `antropite`, `anthrope`. Original ("Antrop", sem k nenhum) era pior.
- **Vogal aberta → respelling de vogal FECHADA na cópia** (v3.3): `tokens` → **`tôkens`**
  (IPA `tɔkeɪŋʃ` virou `to̞kiː` ✔), `opinião` → **`ôpinião`** (`ɔpiniɔŋ` → `əpine̞m` ✔). Entrada
  nova obrigatória no mapa `DISPLAY` do `download_parts.py`, senão a legenda escreve o
  respelling. **Mas o respelling não resolve sempre**: `anteriores` → `anteriôres` continuou
  `nteɾɔɾis`, e `funcionais` → `funciônais` continuou `sjɔnaɪs`. Nesses dois a saída foi
  **reescrever a frase sem a palavra** ("melhor que **nos testes** com GLM 5.3…", "entrega
  experiências **que funcionam**") — mesmo sentido, e resolveu de primeira. Regra 15 vale para
  vogal também: reprovou em 2 takes, reescreve e avisa; insistir só queima tempo.
- Não mude número, nome nem dado sem dizer.

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

**Número por extenso vira DÍGITO na legenda** (v3.3, pedido do Gabriel 04/09: "os números eu
quero que nas captions seja escrito em número mesmo e não em texto"). A cópia do influencIA é
guardada **por extenso** desde 03/09 ("criou seis projetos"), o whisper transcreve a palavra, e a
legenda mostrava "seis". `build_plan.normalize_tokens` converte agora, **antes** da regra de
dinheiro:

| Fala | Legenda | Observação |
|---|---|---|
| "seis projetos" | **6** projetos | cardinal solto ≥ 2 |
| "cento e vinte e oito milhões" | **128** milhões | compostos com "e" juntam num token; escala fica por extenso |
| "vinte e cinco por cento" | **25%** | "por cento" vira `%` |
| "dois mil e vinte e seis" | **2026** | `<n> mil e <n>` vira inteiro (ano) |
| "cinco mil reais" | **5 mil** reais | `<n> mil` sozinho fica "N mil" |
| "**um** pedido aberto" | **um** pedido aberto | "um"/"uma" sozinho é ARTIGO, nunca vira 1 |
| "quatro dólares e cinquenta e três" | **US$ 4,53** | por rodar antes do dinheiro, a regra de moeda voltou a pegar cópia por extenso |

Cuidado registrado: "cento" só conta como 100 dentro de composto ("cento e vinte"); em "por
cento" não. E `accent_words` é comparado contra o token JÁ normalizado — ênfase em "seis" não
casa mais, tem que ser **"6"**.

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
central. **Cartão central (v3.1)**: a imagem cabe numa caixa (largura máx. 86% × 58% da altura)
mantendo a proporção, e a altura REAL exibida é a que entra no centro vertical e na âncora da
legenda (gap 34 px) — imagem + legenda são um componente só, centrado. Antes usava a altura
fixa e a legenda ficava ~300 px abaixo de uma imagem mais larga que alta. Legibilidade no celular: texto do print ≥ ~16 px depois de escalado — se a tabela
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

**Espaço na troca de fonte (v3.2, 04/09):** `word_space_scale` 0,55 aperta o espaço entre
palavras, mas ele era medido sempre no corpo — na fronteira corpo → serifada (1,55×) sumia e
"A Anthropic" saía "AAnthropic". Agora o espaço acompanha o **maior dos dois vizinhos**, em
`build_plan.width` **e** no `render_edit` (os dois juntos, senão a garantia de largura da legenda
quebra). Efeito colateral esperado: os blocos re-quebram (42 → 44 neste vídeo).

`render_edit.py --validate-only` antes de renderizar. Corrija todos os erros.

**Palavra que some da legenda (v3.1, 03/09):** o fim do bloco é limitado pelo segmento onde a
última palavra **termina** (antes era onde ela começa — um corte de zoom 12 ms depois do início
de "SpaceX" fechava o bloco e a palavra nunca aparecia). Se uma palavra sumir de novo, confira
`blk end` × `word start` no `edit-plan.json` e o `src_end` do segmento (`seg_of`). A voz refeita
pelo ElevenLabs (`audio`) também varia por take: reconferência `[PRONUNCIA]` ("saem" → "SciEnv")
= rodar de novo até `[OK]` (script `audio_p1_retry.sh` como modelo: 4 tentativas).

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

**v3.1 (03/09):**
- **Par de logos**: duas marcas citadas em até 2,6 s ("A OpenAI … Cursor") viram UM conjunto
  lado a lado, centrado (gap 5,5% da largura, o par cabe em 90%): a 1ª sobe na palavra dela no
  slot esquerdo, a 2ª sobe na palavra dela no slot direito, flutuam juntas e saem juntas
  (`tiles[]` no evento; documento v2.7 continua lendo). Se o par cai em push-down/cartão, a 2ª
  marca tenta sozinha.
**v3.2 (04/09):** o par ocupa a tela ~1,1 s a mais que um logo só. Quando o par não cabe, o
`brand_logos` agora tenta a **1ª marca sozinha** antes de passar a vez (antes só a 2ª era
tentada). Na abertura "A Anthropic lançou o Fable 5.1" o rabo do par entrava 0,85 s dentro do
push-down da inserção seguinte e o vídeo ficava sem nenhum logo na abertura; sozinho, o logo da
Anthropic termina em 3,40 s e cabe. Lembre: a janela do push-down começa no **início da fala**,
não na âncora da inserção — adiar a âncora não abre espaço.

- **Distância da legenda e tamanho** (03/09, "o logo tá muito perto do texto, diminua se quiser"):
  `CAPTION_GAP_PCT` 0,030 (58 px entre o fim da faixa da legenda e o topo do logo; era 0,004) e
  `SIZE_W_FRAC` 0,23 (248 px máx.; era 288). Com a faixa menor os marks saem ~225–248 px.
- **Glow**: ~20% menor que a v2.8 (`GLOW` bloom 0,49 / halo 0,58 / hot 0,55) e **por marca** com
  `"glow": 0.7` no registro (OpenAI: mark de linha fina estourava). "Um pouco mais forte/fraco" =
  esse campo, sem re-render do vídeo (só a composição dos logos).
- **Asset SÓ o símbolo, fundo transparente**: favicon/app icon vem com badge chapado (Cursor:
  quadrado escuro; CodeRabbit: círculo laranja) e o bloom ilumina o badge inteiro — vira um
  blob liso. Extraia o `<path>` do mark do SVG inline do site oficial (nav/header) para
  `references/logo-sources/<marca>-icon.svg` (viewBox justo) e aponte `file://` no registro.
  Teste: `opaque` ≈ 40–55% do canvas; 90%+ = badge.

### 7c. Encerramento

`closing: fade_out` — preferência do Gabriel; a referência termina seco, **não corrija de volta**.

**v3.3 (04/09, "tem áudio dessincronizado com o vídeo no final")**: não era dessincronia, era
**1,0 s de boca mexendo em silêncio digital**. Três causas somadas: (1) `--last-tail-extra 1.4`
punha 1,4 s de vídeo depois da fala; (2) o timestamp da última palavra esticava 0,5 s além do
áudio real; (3) o fade era fixo em 1,0 s. Agora: cauda 0,35 s, trava do fim pelo silêncio medido
(§1b), e **`_closing_fade` limita o fade à cauda muda que existe de verdade** (piso 0,45 s para
continuar sendo fade, áudio até +0,30 s). Medido no vídeo do Fable: fade 1,0 → **0,757 s**, cauda
muda 1,07 → **0,4 s**. Se o vídeo terminar seco demais, suba `last_tail_extra` no `job.json`.

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

**Trilha de fundo (v3.1, pedido do Gabriel 03/09 "trilha que faça sentido, abaixo da voz")**: no
`job.json`, `"sfx": {"music": {"file": "music/<faixa>.mp3", "gain_db": -16, "fade_in": 1.5,
"fade_out": 2.5, "duck": true}}` → `sfx_mix.py --music`: loop até o fim do vídeo, fade in/out,
ganho e ducking pela voz (`sidechaincompress` limiar 0,09, ratio 2,5, release 900 ms — com fala
contínua o ducking agressivo derrubava a trilha para −45 LUFS). Medido: fonte −10 LUFS, −16 dB →
bus duckado **−30,6 LUFS** contra voz −13,5 (≈17 dB abaixo; −13 dB dá −27,6). Fonte: Mixkit
(`https://assets.mixkit.co/music/<id>/<id>.mp3`, Mixkit License, comercial ok, sem atribuição);
escolher pelos números: bed estável (rms-std ≤ 3 dB, LRA ≤ 4), duração ≥ vídeo (sem loop),
timbre médio. "Minimal Emotion" #160 (120 s) e "Digital Clouds" #175 (101 s) são bons beds. Nunca
trilha sem pedido explícito (regra 7). O `pipeline` imprime `bus TRILHA (duckada)`.

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

**v3.2 (04/09):** o último frame de inspeção sai da duração do **stream de vídeo**, não do
container: o fade de encerramento deixa o áudio ~0,15 s mais longo que o vídeo (§7c), e
`duração do container − 0,10` caía depois do último frame — o ffmpeg não escrevia nada e a
checagem `frames_inspecao` **reprovava um vídeo correto**. Há também uma escadinha para trás
(0,15/0,35/0,60 s) caso o último frame não decodifique.

`validate_output.py <com SFX>.partial.mp4 --plan edit-plan.json --frames-dir validation` — 19
checagens; a largura das legendas é **medida com as fontes reais** (v3.0; antes o aviso
`legendas_dentro_do_canvas` era falso positivo). Inspecione os frames. **Nunca declare sucesso
com validação reprovada.**

## 8b. Sincronia A/V do vídeo final (v3.5)

```bash
python3 "$SKILL/scripts/av_sync_check.py" --final "<comSFX>.partial.mp4" --master "$WORK/master.mp4" \
  --plan "$WORK/edit-plan.json" --max 0.12 --report "$WORK/av-sync.json"
```

Por segmento do plano (≥ 2 s): `lag_v` = onde a boca do final está no master menos onde o plano
manda; `lag_a` = idem para o envelope do áudio; `desync = lag_v − lag_a`. Leitura: `lag_v` e
`lag_a` **constantes e iguais** (≈ −0,05, viés do rastreio) é o normal; `lag_a` **crescendo** em
degraus é áudio perdendo amostras (salto de timestamp na fonte cortado por `atrim`); `lag_v`
crescendo é vídeo perdendo/duplicando quadro (`setpts`/`fps`). O `pipeline render` já roda isto e reprova. Não use
`-shortest` para "igualar" durações: ele esconde exatamente esse defeito (o `sfx_mix` ainda o
tem, mas só depois de o portão ter aprovado durações iguais).

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
    depois de reconferida (whisper-1 **e** fonemas **e** `vowel_check.py`).
13b. **Número na legenda é dígito**, nunca palavra (§4). "um/uma" sozinho é artigo e não vira 1.
13c. Nunca entregar parte com **vogal aberta** onde o pt-BR pede fechada; se o respelling reprovar
    em 2 takes, reescreve a frase sem a palavra e avisa (§1c).
13d. Sincronia labial ruim é do **vídeo do Veo**, não da voz (a voz é STS em cima do próprio
    áudio do Veo). Não troque o áudio: meça com `lipsync_check.py` nas partes de origem, com ROI
    rastreada, e escolha o take pela CORRELAÇÃO (§1c).
14. Cópia de vídeo do influencIA fica em **dígitos** (US$ 4,53, 25%, 5.1); por extenso só ao falar.
15. Não regenerar de novo, por detalhe pequeno, uma parte que o Gabriel acabou de regenerar —
    reportar.
16. **Nunca regenerar só o áudio de uma parte.** Sempre o trecho inteiro (vídeo + voz), senão a
    boca fica dessincronizada da fala nova. `influencia_fix_part.py audio` está desativado (§1c).
17. Take escolhido para entrega passa nos DOIS: teste cego (3 transcritores) **e**
    `lipsync_check.py` (|atraso| ≤ 0,10 s e correlação na faixa das outras partes). Correlação
    alta com fala errada, ou fala certa com boca fora, não entra — regenera de novo.
18. **Master com áudio contínuo e igual ao vídeo.** As partes do influencIA trazem um salto falso
    de timestamp a ~5,1 s; o `concat_parts` recarimba o áudio como contínuo, corta no grid de
    quadros e junta pelo filtro `concat`; a `_verify_master` aborta se o áudio decodificado
    diferir do vídeo em > 0,05 s ou houver pacote esticado. Nunca `-f concat -c copy`, nunca
    `-ss/-t` em tempo livre, nunca `aresample=async`/silêncio no salto (testado: desalinha).
    Se o erro aparecer, o problema é da fonte — não "arrume" mudando a tolerância.
19. **Nenhum vídeo é entregue sem `av_sync_check.py` aprovado** (pior desync ≤ 0,12 s). O
    `validate_output` não mede sincronia; o `pipeline render` roda o checador no arquivo com
    SFX e reprova sozinho. Vídeo de fonte única (não em partes) passa pelo mesmo portão.

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
- O wav2vec2 de fonemas é **muito sensível à janela**: a mesma palavra dá `piniɔm` numa janela
  justa e `ɔpiniɔŋ` com padding. Meça com `−0,10 / +0,12` s (é o que o `vowel_check.py` usa) e
  nunca conclua nada de janela apertada.
- Aviso genérico de "fonética inglesa" do `pron` aparece em TODAS as partes (o modelo marca nasal
  e tepe do pt-BR como inglês). Não é veredito; veredito é palavra a palavra.
- `build_plan.py` sem `--dest` sai com erro de argumento. Se a chamada estiver com
  `>/dev/null 2>&1`, isso passa em silêncio e o `brand_logos` segue lendo o `edit-plan.json`
  VELHO. Rode sempre pelo `pipeline.py`.
