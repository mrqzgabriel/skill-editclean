---
name: editclean
description: Edita um vídeo aplicando o estilo do "Video referencia" — jump cuts dentro do mesmo enquadramento, legendas palavra a palavra com duas famílias tipográficas, zooms sutis, inserções gráficas, grading quente discreto, logo oficial animado quando a fala cita uma empresa (Claude, OpenAI, Google…) e, quando o vídeo chega em trechos/partes (clipes do Veo/influencIA, zip com parteN.mp4), corte do ar morto de cada parte antes de juntar; se uma parte do influencIA saiu com palavra pronunciada errada ou balbucio, entra no sistema, troca a cópia e regenera a parte na origem. Use quando pedirem para editar um vídeo nesse estilo, "editar as partes/trechos" ou corrigir pronúncia de um vídeo do influencIA.
---

# EditClean

Edita um vídeo aplicando o estilo definido em `references/style-profile.json` (v2) e
`references/style-spec.md`.

**O objetivo é entregar o MP4 editado.** Não pare depois de gerar o plano.

---

## 0. Antes de tudo

Leia, nesta ordem:

1. `references/style-profile.json` — todos os parâmetros (é a fonte operacional).
2. `references/style-spec.md` — como interpretar esses parâmetros.

O caminho da skill é `~/.claude/skills/editclean`. Daqui em diante, `$SKILL` refere-se a ele.

> **A seção `user_overrides` do perfil vale mais que o vídeo de referência.** São decisões que o
> Gabriel já tomou depois de ver o resultado. Não "corrija" de volta para o que a referência faz.

---

## 1. Interpretar os argumentos

O primeiro argumento é o caminho do vídeo de entrada. Caminhos vêm **entre aspas e podem conter
espaços** — preserve-os inteiros.

| Flag | Valores | Padrão |
|---|---|---|
| `--output` | caminho de destino | ao lado do original |
| `--aspect` | `keep` \| `9:16` \| `1:1` \| `16:9` | `keep` |
| `--captions` | `auto` \| `off` | `auto` |
| `--quality` | `draft` \| `high` | `high` |
| `--images` | `auto` \| `off` | `auto` |
| `--parts` | `auto` \| `off` | `auto` — vídeo que chega em trechos: corta o ar morto de cada parte antes (§1b) |
| `--logos` | `auto` \| `off` | `auto` — animação de logo quando a fala cita uma empresa (§7b) |
| `--overwrite` | (sem valor) | ausente |

Nome padrão de saída: `<nome-original>_editclean.mp4`.

Se a saída já existir e `--overwrite` **não** tiver sido passado, use `_editclean_v2.mp4`, depois
`_v3`, `_v4`… **Nunca sobrescreva o vídeo original nem outro arquivo existente em silêncio.**

## 1b. Vídeo em trechos (partes numeradas) — v2.7

Quando a entrada é um **conjunto de partes** (`parte1.mp4 … parte10.mp4`, clipes de ~8 s do Veo /
influencIA, um zip com elas), **não concatene cru**. Cada clipe gerado termina com ar morto (a fala
acaba e o vídeo continua 1–2 s) e às vezes começa com folga; junto de 10 partes isso vira 15–20 s
de silêncio que o `build_plan` só remove em parte e que deixa as emendas moles. O Gabriel pediu
(01/09) que fique **"cortadinho certinho, igual quando renderiza no influencIA"**.

```bash
python3 "$SKILL/scripts/concat_parts.py" --dir "<pasta>" --pattern "parte*.mp4" \
  --out "$WORK/master.mp4" --scale 1080:1920 --report "$WORK/partes_report.json" \
  [--overrides "$WORK/partes_overrides.json"]
```

É a **mesma regra** do `normalizeTrimConcat` do influencIA
(`artifacts/api-server/src/lib/remotion-renderer.ts`), por parte:

| Passo | Regra |
|---|---|
| medir | faster-whisper (palavras) + `silencedetect` −25 dB / 0,15 s |
| começo | silêncio que começa em < 0,05 s e termina até 0,2 s após a 1ª palavra → **fim do silêncio − 0,05**; senão **1ª palavra − 0,08** |
| fim | **última palavra + 0,15 s** — e, proteção nossa, se a energia ainda não caiu ali, anda até o próximo silêncio + 0,05 (máx. 0,6 s). Nunca decepa sílaba |
| sem fala | começo do silêncio final + 0,05; sem silêncio: duração − 0,5 |
| encode | cada parte re-encodada (crf 12, fade de 12 ms nas bordas contra clique) e concat sem re-encode |

**Leia a transcrição que o script imprime de cada parte.** Voz gerada às vezes vira **balbucio**
(no Fable 5.1 a parte 9 tinha 6,4 s de "Oristote Paracosfinete…" que os três modelos Whisper
transcrevem como palavras) — o corte automático **não pega** isso, nem o `avg_logprob`. Quando
achar, use `--overrides` com tempos **locais** da parte, igual ao `ClipTrimOverride` do influencIA:

```json
{"parte9.mp4": {"end": 1.58}, "parte10.mp4": {"start": 0.62}, "parte3.mp4": {"skip": true}}
```

O rabo do balbucio costuma vazar para o **começo da parte seguinte** (a regra do início exige
silêncio desde 0,05 s, e o rabo impede) — confira as duas partes vizinhas, não só a defeituosa.

**Fade de encerramento (v2.8, padrão):** a última parte precisa sobrar depois da última palavra,
senão o fade apaga a fala — passe `--last-tail-extra 1.4` (o `build_plan` estende a cauda em
`audio_fade_s` sozinho, mas só se o master tiver esse material).

Depois disso o master é a entrada normal da skill (§2 em diante). O `--scale` já sobe para
1080×1920 no mesmo encode; entregue nessa resolução (nativa do Reels e os prints inseridos ficam
legíveis). Registre no relatório final quanto cada parte perdeu e os overrides usados.

## 1c. Vídeo do influencIA: pronúncia errada → corrigir NA ORIGEM — v2.9

Se as partes vieram do influencIA (clipes do Veo com a voz trocada pelo ElevenLabs), a voz
gerada às vezes **pronuncia uma palavra errado** ("derrubar" → "derrugar") ou **balbucia**. Isso
não se conserta na edição: a legenda até esconde, mas o áudio continua errado. Pedido do Gabriel
(01/09): *"quando identificar algum problema assim, entrar no sistema influencIA e regenerar,
podendo até mesmo mudar a copy pra pronúncia ficar certa"*. Fluxo, sempre nesta ordem:

**1. Detectar** — antes do `concat_parts.py`, e sempre que a transcrição do §4 mostrar palavra
que não existe:

```bash
python3 "$SKILL/scripts/influencia_fix_part.py" check --project "<trecho do título>" \
  --parts-dir "<pasta das partes>" --report "$WORK/influencia_check.json"
```

Transcreve cada parte com o **whisper-1 da OpenAI** (o mesmo transcritor do sistema, `lib/whisper.ts`)
e compara token a token com a **cópia** daquela parte no influencIA. Número por extenso vs dígito
não conta. Classes: `OK`, `PRONUNCIA` (1–3 palavras trocadas), `BALBUCIO` (fala continua muito
além da cópia), `DIVERGE` (outra coisa; olhar).

**2. Decidir a palavra nova** — decisão editorial sua, não do script:
- Prefira uma palavra que **a mesma voz já pronunciou bem no mesmo vídeo** (no Fable, "derrubar"
  virou **"quebrar"**, que ela já dizia certo na parte 1 e ecoa o título).
- Mesmo sentido, mesma força; frase igual no resto. **Não** faça respelling fonético ("derru-bar",
  "derrubá") — em português não há padrão e o TTS lê letra por letra ou pausa.
- Diga ao usuário o que trocou. Não mude número, nome próprio nem dado.
- `BALBUCIO` = cópia curta demais para os 8 s (o prompt do Veo obriga a boca a mexer o tempo
  todo). Regenerar com o mesmo texto repete. Padrão: **cortar no `--overrides` do §1b** e avisar;
  só encher a frase se o usuário topar o texto novo.

**3. Regenerar só a parte, pela produção:**

```bash
python3 "$SKILL/scripts/influencia_fix_part.py" fix --project "<título>" --part 2 \
  --text "A promessa é simples e pesada, tocar projetos longos sem quebrar tudo por um erro pequeno." \
  --parts-dir "<pasta das partes>" --tag derrugar
```

Faz `PUT /copy-parts/:id` (texto), `POST /copy-parts/:id/generate-video`, espera o poller da
produção (Veo Lite ~2–4 min + troca de voz), **reconfere com o whisper-1** e só então baixa o
vídeo novo para a pasta, guardando o antigo como `parteN_vK_<tag>.mp4`. Se ainda sair errado,
regenera de novo (`--retries`, padrão 2). Usa a produção de propósito: local e produção dividem a
mesma fila e o poller de lá pode marcar como falha o que o local iniciou.

**4. Continuar** do §1b com as partes já corrigidas. Registre no relatório: palavra, cópia antiga →
nova, nº de tentativas.

Credenciais (login, senha, chave OpenAI) vêm do `.env` do influencIA, cujo caminho está em
`.credentials.json` (`influencia_env`, `influencia_api`) — nunca imprima.

## 2. Validar entrada e dependências

```bash
test -r "<input>" || exit
```

Confira `python3`, `ffmpeg` e `ffprobe`. Os scripts procuram em `PATH`, `~/.local/tools/`,
`/opt/homebrew/bin` e `/usr/local/bin`. Nesta máquina o ffmpeg/ffprobe estão em `~/.local/tools/`.

Para legendas é necessário `faster-whisper`:

```bash
python3 -c "import faster_whisper" || pip3 install --user faster-whisper
python3 -c "import cv2"            || pip3 install --user opencv-python-headless
```

O OpenCV é usado para localizar o rosto (§3) e definir a altura da legenda.

Se faltar algo essencial: diga **exatamente** o que falta, dê o comando de instalação para macOS
(`brew install ffmpeg`), **peça autorização antes de qualquer instalação global** e só prossiga
depois que estiver disponível.

Confirme com `ffprobe` que o arquivo é um vídeo decodificável. **O arquivo original é somente
leitura em todas as etapas.**

Crie o diretório de trabalho desta execução (use o scratchpad da sessão, não `/tmp`).

## 3. Analisar

```bash
python3 "$SKILL/scripts/analyze_video.py" "<input>" --outdir "$WORK"
```

Produz `$WORK/manifest.json` (metadados, cenas, silêncios, `speech_spans`, transientes, movimento,
nitidez, frames pretos, congelamentos, heurística de legenda queimada) e frames em `$WORK/frames/`.

### Onde está o sujeito

```bash
python3 "$SKILL/scripts/detect_subject.py" --video "<input>" --outdir "$WORK"
```

Roda em ~5 s (YuNet) e grava `subject.json` com **onde o rosto está neste vídeo**: queixo, topo da
cabeça, altura e centro da face. Dele saem, automaticamente:

| Derivado | Serve para |
|---|---|
| `caption_anchor_pct` | altura da legenda — abaixo do queixo |
| `overlay_bottom_limit_pct` | até onde uma inserção no topo pode descer |
| `face_center_y_pct` | âncora do punch-in |

O `build_plan.py` chama isso sozinho se o arquivo não existir. **Não escolha essas alturas na mão** —
elas dependem do enquadramento e um valor de outro vídeo erra. Sem rosto detectado (voz sobre
imagem, animação, pessoa de costas) ele cai nos valores do perfil e avisa.

**Inspecione visualmente os frames** assim mesmo, para confirmar se já existe **legenda queimada**
(a heurística do manifesto é indício, não prova).

## 4. Transcrever (se `--captions auto`)

```bash
python3 "$SKILL/scripts/transcribe.py" "<input>" --out "$WORK/words.json" --language pt
```

Ordem de backends: **faster-whisper** → whisper local → API da OpenAI.

> **Use faster-whisper.** A API `whisper-1` devolve timestamps colapsados (várias palavras com o
> mesmo `start`, duração 0) que **dessincronizam a legenda** — foi um problema real. O
> faster-whisper faz alinhamento por palavra de verdade.

Depois **confira a transcrição** contra o áudio. Corrija só o que o modelo **errou ao ouvir**:

- grafia de número falado por extenso → `30%`, `100%`;
- palavra mal reconhecida (`"maia"` → `"IA"`, `"voas"` → `"boas"`).

**Nunca invente palavra que não esteja no áudio, nunca altere o sentido da fala.** Se corrigir algo,
registre em `limitations`.

Modelo `small` erra o suficiente para atrapalhar. **Confira rodando `medium` sobre o mesmo áudio** e
compare frase a frase — o `small` é quem dá os timestamps por palavra, o `medium` só confirma o
texto. No IMG_1169 isso pegou `assistir→assiste`, `no 20 semana→no fim de semana`,
`remião→reunião`, `relatam o→relatam um`, `esfria→esfrie`. Para um trecho duvidoso, recorte a fatia
e rode com `initial_prompt` do contexto. **Não use `atempo` para "ouvir devagar"** — distorce e a
transcrição piora.

### O alinhador estica artigo para dentro do silêncio

`sanitize_times()` no `build_plan.py` redistribui tokens cujos **inícios ficam a menos de 80 ms** um
do outro. Palavra funcional curta (`o`, `a`, `de`) costuma vir do Whisper com 60–80 ms e dispara
isso, empurrando a **palavra seguinte** em até ~330 ms — ela acende atrasada na legenda.

Confira antes de montar o plano:

```python
toks = bp.sanitize_times(bp.normalize_tokens(raw["words"]), spans)
[(i, w[i]["text"]) for i in range(len(w)) if abs(w[i]["start"] - toks[i]["start"]) > 0.05]
```

Onde acusar, **redistribua os tempos dentro da própria frase** dando ≥ 0,10 s de espaçamento entre
os inícios. Isso muda só **quando a palavra acende**, nunca o que é dito — mas registre em
`limitations`. Cuidado com float: `17.08 - 17.00` dá `0.0799…`, que cai abaixo do limite.

Caso à parte: quando o Whisper estica uma palavra **para dentro de um silêncio detectado** (o `A` de
"A Segia" ocupando 24,96→25,52 com silêncio medido em 24,88→25,44), o certo é encolher a palavra
para junto da seguinte. Compare `words.json` com `manifest.analysis.silences`.

Se nenhum backend estiver disponível: informe o bloqueio **antes de renderizar**, siga com
`captions.enabled: false` e registre em `limitations`.

## 5. Imagens pertinentes (se `--images auto`)

O estilo prevê inserções acompanhando o assunto da fala (~3,9/min).

**Acervo Creative Commons quase nunca serve** para nicho comercial — só devolve foto documental e
clipart, e os PNGs "transparentes" do Openverse vêm com o xadrez **pintado** na imagem. Use o Apify:

```bash
python3 "$SKILL/scripts/fetch_images_apify.py" --outdir "$WORK/img" \
  --query "termo um" --query "termo dois" --per-query 30
```

O token está em `$SKILL/.credentials.json` (`apify_token`).

> **O acervo é muito sujo.** Medido em 217 candidatas de 24 consultas: **86 eram a página de
> bloqueio de hotlink**, 48 mockup/render 3D/composição, e só **33 print ou foto real**. Conte com
> descartar ~85% e peça **30 por consulta**. O script agora barra a página de bloqueio no pixel e
> guarda o que descartou em `<outdir>/rejeitadas/`. Detalhes em `style-spec.md` §9.
>
> **Consulta abstrata atrai o spam.** "gráfico de conversão", "ampulheta", "dinheiro na mesa"
> voltaram 100% bloqueio; termo concreto ("whatsapp", "excel line chart") voltou resultado real. Se
> uma consulta só devolve bloqueio, troque o termo — não insista.

Regras:

1. **Abra e olhe cada imagem.** Relevância é decisão sua, não do script.
2. **Só print de tela ou fotografia real.** Mockup vetorial, render 3D de celular, arte de IA e
   composição de Photoshop estão **proibidos** — o Gabriel rejeitou explicitamente
   (`user_overrides.images_must_be_real`). Sinal de mockup: "Lorem ipsum", balões uniformes,
   avatar como círculo chapado, 09:41 repetido em todos os painéis, "template"/"PSD"/"IMAGE NOT
   INCLUDED". O detector do script **não** pega isso — só o olho pega.
3. **Descarte print que exponha nome + foto de pessoa privada identificável.** Risco num vídeo
   comercial. Print com nome borrado pelo blog também sai: fica com cara de censura.
4. **Recorte marcas de terceiros** — e principalmente de **concorrentes do usuário** (seria péssimo
   mostrar concorrente no VSL dele). Recortar a região útil quase sempre resolve.
5. **Proporção: não pré-recorte em panorâmica — a caixa agora é dimensionada por janela (v2.6).**
   O `build_plan.py` mede a folga REAL acima da cabeça no trecho de cada inserção
   (`per_window_headroom`: YuNet dentro da janela, imagem até 26 px antes da testa) e prefere a
   imagem **inteira**: uma 16:9 entra sem corte nenhum onde há folga (caixa tipo 928×522), e só
   cai no *cover* quando a inteira ficaria estreita demais. **Confira as caixas impressas no
   relatório** (`insercoes: OVn caixa WxH`); se quiser controlar o enquadramento, recorte a imagem
   no aspecto exato da caixa impressa e rode de novo. Uma 5:1 pré-recortada continua desperdiçando
   altura à toa.
   **Imagem VERTICAL (aspecto < ~1,15) não vai para a faixa** — o `build_plan` a transforma
   sozinho em **cartão central** (v2.6, aprovado 26/08): imagem grande (~58% da altura) no centro,
   vídeo inteiro desfocado atrás (gblur σ26), e a legenda reancorada logo abaixo — imagem+legenda
   viram um componente único centrado na vertical. Janelas alinhadas a fronteira de bloco (tudo
   muda no mesmo frame), cartões vizinhos dividem um desfoque e trocam por corte seco, entrada e
   saída SECAS (fade em cartão cheio deixa a pessoa "fantasma"). Se houver push logo depois, o
   cartão termina exatamente no início da descida. Print de celular em pé, santinho e fachada em
   retrato são os casos típicos.
   Margens conforme `graphics_overlays.safe_margins`: 3,5% de respiro no topo, largura ≤ 86% — e no
   modo clássico (`--no-push`) a **base fica acima da cabeça**, limite do `subject.json`.
6. Se nada pertinente aparecer, **omita a inserção** e registre em `limitations`. Nunca use asset
   genérico de preenchimento.
7. **Avise o usuário no resumo final** que essas imagens têm direitos autorais. E quando o assunto
   for o produto dele, **peça um print do próprio celular/sistema** — é real, em português, no
   contexto certo, sem direitos de terceiros e sem expor ninguém. Vale mais que qualquer busca.

Passe as escolhas para o `build_plan.py` num JSON:

```json
[{"id":"OV1","path":"/…/01.jpg","src_start":2.0,"src_end":4.4,"why":"métricas de tráfego pago"}]
```

## 6. Montar o plano de edição

```bash
python3 "$SKILL/scripts/build_plan.py" --work "$WORK" \
  --source "<input>" --dest "<destino>" --quality high \
  [--overlays "$WORK/ov.json"] [--accent "$WORK/acc.json"]
```

O script já aplica **todas** as regras do perfil e imprime um relatório conferindo contra ele:

- fronteiras que **preservam a fala** (§ *Regras invioláveis* 5);
- curva de ritmo por terços escalada pela duração;
- escalas de zoom com salto garantido em cada corte, mais os **padrões dinâmicos** (punch-in cut
  com volta suave, punch com reabertura por corte, push lento no respiro — ver spec §5);
- blocos de legenda com quebra automática, corpo por bloco e **posição única centralizada**;
- timeline já descontando o encurtamento do `xfade`;
- **push-down nas inserções (padrão desde a v2.5, pedido do Gabriel 26/08 — "arrastar o vídeo pra
  baixo e mostrar a imagem melhor")**: o vídeo desliza ~13% para baixo (rampa smoothstep de 0,35 s),
  abre palco preto no topo e a imagem aparece ~2× maior; as legendas **descem junto** porque o
  efeito é aplicado depois delas no filtergraph — nunca trocam de âncora. O script calcula a
  distância pelo fundo real da legenda + reserva de 11,5% para a UI do Reels, alinha as janelas a
  fronteiras de bloco de legenda, foge de transições, e a imagem só acende **depois** da descida
  completa (senão cruza a cabeça em movimento). `--no-push` desliga; sem folga vertical o script
  avisa e cai sozinho no top_band clássico. Confira no relatório a linha `push-down`;
- **caixa por janela + cartão central (v2.6, pedidos do Gabriel 26/08)**: a altura da caixa vem da
  folga MEDIDA no trecho de cada inserção (não do pior caso global) e prioriza a imagem inteira;
  inserções vizinhas na mesma janela de push trocam por corte seco (fade cruzado = dupla
  exposição); imagem vertical vira cartão central com desfoque de fundo e legenda ancorada abaixo
  (âncora `footer` recalculada). Confira no relatório as linhas por inserção (`push_down` /
  `center_card` / `desfoque de fundo`) e a nota `[plan] folga por janela indisponivel` — se ela
  aparecer, o dimensionamento voltou ao limite global.

**Confira o relatório contra o perfil.** Se algum número destoar muito, ajuste e rode de novo.

O que continua sendo **decisão sua** e entra por arquivo:

- `--accent` — quais palavras levam a ênfase serifada (`{"accent":[12,40],"strong":[8]}`, índices do
  token). Sem isso o script usa heurística (evita palavra funcional, prefere substantivo/número).
- `--overlays` — quais imagens e quando.

Valide antes de renderizar:

```bash
python3 "$SKILL/scripts/render_edit.py" --plan "$WORK/edit-plan.json" --validate-only
```

**Corrija todos os erros antes de seguir.**

## 7. Renderizar

Faça **primeiro um rascunho** (`crf 30`, `preset ultrafast`) e inspecione frames — é rápido e pega
problema de composição antes de gastar o render alto.

```bash
python3 "$SKILL/scripts/render_edit.py" \
  --plan "$WORK/edit-plan.json" --out "<destino>" --workdir "$WORK/render"
```

Escreve em `<destino>.partial.mp4`. **Ainda não é o arquivo final.**

## 7b. Logo de marca em motion design (se `--logos auto`) — v2.7

Quando a fala **cita uma empresa/modelo** (Claude/Fable/Anthropic, OpenAI/ChatGPT, Google/Gemini,
Meta, Microsoft, DeepSeek, Mistral, Perplexity…), o logotipo **oficial** aparece no peito da
pessoa: **sobe de baixo** com ease-out e leve overshoot (0,66 s), acende com bloom + halo + núcleo
quente na cor da marca, segura ~1 s com o brilho respirando e **sai para cima** acelerando
enquanto apaga (0,54 s). Pedido do Gabriel 01/09 ("logo com efeito de entrada de baixo pra cima e
depois saindo no estilo motion design… cinematográfico e bonito"), aprovado no Fable 5.1.

```bash
python3 "$SKILL/scripts/brand_logos.py" plan   --work "$WORK" --plan "$WORK/edit-plan.json"
python3 "$SKILL/scripts/brand_logos.py" render --events "$WORK/brand-logos.json" \
  --in "<render>.partial.mp4" --out "<destino>.partial.mp4"
```

Como funciona (detalhes em `style-spec.md` §17):

- **Registro** em `references/brand-logos.json`: aliases por marca, **fonte oficial** do logotipo
  (site da empresa ou o SVG oficial na Wikimedia Commons) e cor-base. O `fetch` baixa, rasteriza
  em 2048 px (Chrome headless no Mac) e guarda em `assets/logos/<marca>.png` com um `.json` de
  procedência. **Marca sem fonte oficial (xAI hoje) é pulada, nunca desenhada** — regra 6.
- O `plan` acha as menções no `words.json`, mapeia para a timeline de saída pelos segmentos do
  plano, entra **0,32 s depois de a palavra acender**, exige **≥ 10 s** entre animações e **pula**
  menção que caia em push-down, cartão central, desfoque ou trecho removido (o quadro está
  deslocado/desfocado — o logo flutuaria). Grava `brand-logos.json`; copie-o para
  `edit-plan.json` em `brand_logos` (procedência).
- **Posição é derivada, não chutada**: o topo da faixa é o fundo da legenda de 2 linhas no maior
  corpo do plano (+ halo), o fundo é a reserva de UI do Reels (11,5%). Mark quadrado: 26,7% da
  largura (288 px em 1080), encostado no topo da faixa. Wordmark largo: até 60% da largura,
  centrado na faixa. No Fable 5.1 isso deu `cy 0,811`, sem tocar a linha "saiu" da legenda.
- **v2.8 (01/09)**: o logo **flutua** enquanto está na tela (seno de ±8,6 px em y e ±2 px em x
  em 1080×1920, ganho suave durante a subida) e o glow ficou **15% mais fraco e ~20% mais
  aberto** (bloom σ74/0,61, halo σ22/0,72, núcleo 0,68). Pedido: "como se tivesse flutuando, com
  uma margem curta de movimento… o glow 15% mais fraco e um pouco maior o range".
- **Render em duas passagens**: o `render_edit.py` sai em crf 14 para um intermediário, e o
  `brand_logos.py render` compõe a sequência RGBA (transparente fora dos eventos, começa em t=0,
  `overlay … eof_action=pass`) e grava o `.partial.mp4` final em crf 18 copiando o áudio, com `-t`
  igual à duração do vídeo — o AAC do render sai ~67 ms mais longo e isso derruba a checagem
  `frames_inspecao` do validador.

O `validate_output.py` roda **no arquivo composto**, não no intermediário.

## 7c. Encerramento — fade (v2.8, preferência do Gabriel)

Desde a v2.8 o plano sai com `closing: fade_out` (vídeo escurece em 1,0 s, áudio apaga em 1,3 s)
— pedido de 01/09: *"no final do vídeo coloque fade out no áudio e a tela ficando preta"*. A
referência termina seco; **não "corrija" de volta**. O `build_plan` já estende a cauda depois da
última palavra para o fade não comer a frase; confira no relatório a duração de saída e, em vídeo
em trechos, o `--last-tail-extra` do §1b.

## 7d. Capa (thumbnail) do vídeo — v2.11

Depois do vídeo aprovado, gere a **capa** — padrão `--style cinema` (pedido do Gabriel 01/09: *"algo
mais cinematográfico com a mesma fonte de legenda do vídeo, estilo cinema mesmo, e não quero cara
de bravo na pessoa"*):

```bash
python3 "$SKILL/scripts/make_cover.py" --project "<título>" \
  --headline "ANTHROPIC LANÇOU O *Fable 5.1*" --logo claude --mood studio_haze \
  --keep-raw "$WORK/capa_sem_texto.png" --out "<pasta>/<nome>_CAPA.png"
```

Como o `cinema` funciona (spec §19):

1. **Imagem sem texto** pelo `gemini-3-pro-image` (mesma credencial e rota do thumbnail do
   influencIA, foto de referência do influencer baixada do projeto): frame de filme, pessoa do
   peito para cima **calma e confiante** (o prompt proíbe cara de bravo, cenho franzido, boca
   tensa), câmera de cinema anamórfica (pouca profundidade, flare discreto, grão fino), key
   quente + rim frio, grading contido, fundo escuro do `--mood` (`studio_haze`, `void_light`,
   `server_room`, `city_window` ou texto livre), **logo oficial** como emblema aceso na cena,
   terço inferior calmo para o título. **Nenhum texto** na imagem.
2. **Tipografia da legenda** composta pelo script com as fontes reais: Helvetica Neue Bold nas
   palavras corridas, Playfair Display Italic **1,55×** na ênfase (marque com `*asteriscos*` no
   `--headline`), cor `#FCF8F6`, halo escuro difuso, glow claro no serifado e degradê escuro no
   rodapé. **O título nunca fica embaixo da interface do Reels** (v2.13, pedido 01/09 "pesquise
   os ranges das coisas no Reels; o texto nunca deve ficar embaixo dessas coisas"): a faixa útil
   vai do **queixo** (YuNet na própria imagem, +2%) até **y = 1500 px** (rodapé de ~420 px com
   usuário/legenda/áudio **e** o recorte 1:1 da grade do perfil, que só mostra 420–1500), com
   largura ≤ 78% e ≥ 120 px de cada lado (coluna de ícones à direita). O corpo se ajusta à faixa
   (auto-fit) e o bloco fica centrado nela (`--text-center` força; `--safe ads` usa o guia da
   Meta, rodapé de 35% = y ≤ 1248; `--show-safe` grava `<out>.zonas.png` com as zonas desenhadas
   para conferir). Números e fontes na spec §19. A ênfase serifada sai **na cor do logo**
   (`--accent-color auto` lê o laranja com que o logo foi renderizado na própria imagem; `#hex`
   fixa; `none` = branco) com glow quente da mesma cor — pedido 01/09: "texto mais no centro e o
   Fable 5.1 laranja na mesma cor do logo". `--text-only --ref <imagem>` recompõe só o texto
   (iterar sem gastar crédito).

Gere **mais de uma variante** (moods diferentes) e escolha olhando: rosto idêntico à referência e
sem cara de bravo são eliminatórios; logo reproduzido uma vez, sem redesenho; título legível e
bonito. `--style influencia` mantém o thumbnail do sistema como ele é (texto vermelho/amarelo
gerado pelo modelo, pessoa "intensa") para quando pedirem esse padrão.

Sem projeto no influencIA: `--ref <foto> --title "..."`. Cada saída grava um `.capa.json` ao
lado (prompt, modelo, mood, tipografia). Salve a capa junto do vídeo (Desktop). Versão do produto
vem do vídeo, não do pedido ("Fable 4.1 sei lá" → 5.1).

## 8. Validar a saída

```bash
python3 "$SKILL/scripts/validate_output.py" "<destino>.partial.mp4" \
  --plan "$WORK/edit-plan.json" --frames-dir "$WORK/validation"
```

Sai com 0 se aprovado. **Inspecione os frames em `$WORK/validation/`** antes de concluir.

> O aviso `legendas_dentro_do_canvas` é frequentemente **falso positivo**: o validador estima largura
> por caractere e não conhece o `accent_size_ratio`. Confira o bloco citado em frame renderizado
> antes de mexer.

Se reprovar: corrija o plano e volte ao passo 7. **Nunca declare sucesso com validação reprovada.**

## 9. Promover e limpar

Só depois da aprovação:

```bash
mv "<destino>.partial.mp4" "<destino>"
```

Guarde uma cópia do `edit-plan.json` fora do diretório temporário (permite reajustar sem refazer
tudo) e só então remova os temporários **desta execução**.

## 10. Relatar

Informe: caminho do vídeo final; duração antes → depois e quanto foi removido (se veio em
trechos, quanto cada parte perdeu e os overrides); nº de cortes, transições, zooms e blocos de
legenda; imagens inseridas **com a origem e o aviso de direitos**; logos animados (marca, instante,
fonte oficial); resultado da validação; limitações reais.

---

## Regras invioláveis

1. O vídeo de entrada é **somente leitura**.
2. Escrita atômica: `.partial.mp4` → validar → `mv`. Nunca escrever direto no destino.
3. Nunca sobrescrever arquivo existente sem `--overwrite`.
4. Nunca esticar a imagem.
5. **Nunca cortar enquanto a pessoa fala.** Folga de 160 ms nas bordas; pausa cuja remoção renderia
   menos de 100 ms vira corte seco sem remoção; nas transições o silêncio é **mantido** e o corte
   cai no meio dele.
6. Nunca inventar dados, logotipos ou marcas.
7. Nunca adicionar música sem arquivo fornecido pelo usuário.
8. Nunca alterar o sentido das falas.
9. Credencial só de `OPENAI_API_KEY`/`APIFY_TOKEN` no ambiente ou de `$SKILL/.credentials.json`
   — mais o `.env` do influencIA apontado por `influencia_env` (só para o §1c). Nunca vasculhar
   outros projetos, nunca imprimir chave nem senha.
10. Nunca declarar sucesso sem `validate_output.py` aprovar.
11. Logo de marca só de **fonte oficial** registrada em `brand-logos.json`; sem asset, sem
    animação. Nunca redesenhar, nunca "parecido".
12. Vídeo em trechos: **ler a transcrição de cada parte** antes de aceitar o corte automático —
    balbucio de voz gerada passa pelo Whisper como se fosse fala.
13. Pronúncia errada em parte do influencIA se corrige **na origem** (§1c), nunca só na legenda;
    e a parte regenerada só entra depois de **reconferida** pelo whisper-1.

## Notas de implementação (armadilhas já resolvidas)

Estão corrigidas no `render_edit.py`. **Não reintroduza:**

- **Zoom usa `zoompan`, não `crop`.** O `crop` avalia `w`/`h` na configuração, onde `t` não existe.
- **`fps` depois de `zoompan` multiplica os frames.** O zoompan emite PTS na timebase da *entrada*
  mas declara `1/fps` na saída; um `fps` adiante lê errado e 2 s viram 40 s. Corrigido com
  `settb=AVTB,setpts=N/fps/TB`.
- **Zoom sutil treme sem superamostragem.** O zoompan arredonda x/y para pixel inteiro; com 2-3% de
  variação o passo por frame é ~1 px e o arredondamento vira tremida. Ampliar 2,5× antes e reduzir
  depois.
- **`xfade` exige timebase idêntico** nos dois lados → `settb=AVTB` antes.
- **Overlay de imagem não usa `-loop 1`.** Cria stream infinito e o render trava; a imagem entra como
  frame único e o filtro `loop` replica pela contagem exata.
- **Zoom nunca se move em cima do corte.** `start_offset` + `ease_in_out` em tudo; supersampling
  adaptativo (2,5–6×) para movimento lento; renormalização desloca o settle inteiro. A abertura é
  gaussiano frame a frame — degraus largos pulsam e crossfade nítido+desfocado vira dupla exposição.
- **Fade da legenda é por palavra.** `\fad` no evento inteiro faz o bloco piscar a cada palavra,
  porque cada estado do karaokê é um evento ASS novo. Usar
  `\alpha&HFF&\t(0,ms,\alpha&H00&)` só na palavra nova.
- **Não usar `setpts` junto com `select`** nas cadeias de análise: renumera o tempo.
- Fontes: Helvetica Neue vem do sistema (`/System/Library/Fonts/HelveticaNeue.ttc`); Playfair Display
  está em `$SKILL/assets/fonts/` (OFL) e é passada ao libass via `fontsdir`.
