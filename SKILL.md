---
name: editclean
description: Edita um vídeo aplicando o estilo do "Video referencia" — jump cuts dentro do mesmo enquadramento, legendas palavra a palavra com duas famílias tipográficas, zooms sutis, inserções gráficas e grading quente discreto. Use quando pedirem para editar um vídeo nesse estilo.
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
| `--overwrite` | (sem valor) | ausente |

Nome padrão de saída: `<nome-original>_editclean.mp4`.

Se a saída já existir e `--overwrite` **não** tiver sido passado, use `_editclean_v2.mp4`, depois
`_v3`, `_v4`… **Nunca sobrescreva o vídeo original nem outro arquivo existente em silêncio.**

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
5. **Proporção: entregue a imagem próxima de 2:1 e não pré-recorte em panorâmica.** Com o
   push-down (padrão, ver §6) a faixa útil cresce ~2×; o renderer faz *cover* na caixa (~0,825 da
   largura × faixa) e corta só o excesso centrado. Uma 16:9 perde ~10% da altura; uma 5:1 pré-
   recortada perderia mais da metade da largura à toa. Print de celular **em pé** continua fora
   (recorte uma faixa horizontal, ou foto do aparelho na mão/na mesa); o mínimo continua ≥ ~1,15:1.
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
  avisa e cai sozinho no top_band clássico. Confira no relatório a linha `push-down`.

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

Informe: caminho do vídeo final; duração antes → depois e quanto foi removido; nº de cortes,
transições, zooms e blocos de legenda; imagens inseridas **com a origem e o aviso de direitos**;
resultado da validação; limitações reais.

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
9. Credencial só de `OPENAI_API_KEY`/`APIFY_TOKEN` no ambiente ou de `$SKILL/.credentials.json`.
   Nunca vasculhar outros projetos, nunca imprimir a chave.
10. Nunca declarar sucesso sem `validate_output.py` aprovar.

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
