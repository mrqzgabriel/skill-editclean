# EditClean — especificação técnica do estilo

Conteúdo técnico extraído de `ANALISE_TECNICA_EDICAO_VIDEO_REFERENCIA.md`, reduzido ao que é
necessário para **executar** uma edição. Material descritivo, timestamps absolutos do vídeo de
referência e seções de auditoria foram removidos — o que importa aqui são as regras aplicáveis a
qualquer vídeo.

Os valores numéricos operacionais vivem em `style-profile.json`. Este documento explica **como
interpretá-los**.

> **v2 — o que mudou.** As seções de legenda, cortes, transições, zoom, abertura e imagens foram
> reescritas a partir de **medição direta de 294 frames do próprio vídeo de referência** (feita na
> edição do IMG_1171, 26/08/2026), não do relatório. Onde a medição contradiz o relatório, a medição
> vence. As decisões marcadas **[preferência do Gabriel]** valem mais que a referência: são escolhas
> que ele tomou depois de ver o resultado, e não devem ser "corrigidas" de volta.

---

## 1. Identidade do estilo em uma frase

Vídeo vertical falado, cortado quase inteiramente com **jump cuts secos dentro do mesmo
enquadramento**, legendas brancas reveladas palavra a palavra com **duas famílias tipográficas
alternadas para dar ênfase**, zooms digitais muito sutis, transições raras e pontuais, grading quente
discreto, abertura com desfoque que se resolve e **encerramento seco, sem fade**.

---

## 2. Ritmo

- Cadência média de **~26 eventos de fronteira por minuto** (cortes + transições).
- Duração de plano: mediana **~1,3 s**, quartis 0,7 s / 2,2 s — mas atenção: essa distribuição vem
  dos **88 planos brutos** do detector. Com os 67 planos reais a média sobe para ~2,3 s. Use a taxa
  de fronteiras como fonte de cadência; a distribuição serve só para a **forma** (mediana bem abaixo
  da média, poucos planos muito longos).
- A cadência **não é uniforme**. Curva observada:
  - primeiro terço: mais rápido;
  - terço central: desacelera bastante, tipicamente por causa de **um único plano-respiro longo**
    (5–12 s);
  - terço final: reacelera parcialmente, **sem** voltar ao pico inicial.

  Reproduza a **razão** entre os terços — **1 : 0,46 : 0,76** — aplicada sobre a taxa de 26/min.
  (Os números 46/21/35 por minuto que aparecem no relatório são do detector bruto e não fecham com
  os 26/min reconciliados.)
- Ao adaptar para outra duração, **escale a contagem de eventos**, nunca copie posições absolutas.
- **Só ~1/3 dos cortes cai em transiente de áudio.** A montagem é guiada por fala e gesto, não por
  batida. Não force corte "no beat". A taxa varia por terço: ~36% no primeiro, **~61% no respiro
  central**, ~13% no fecho — corte mais "na batida" no miolo, menos no final.

## 3. Cortes

- ~86% das fronteiras são **corte seco de 1 frame**. Quatro desses cortes (~7%) são na verdade
  mini-transições de ~1 frame com blur/dissolve aplicado — somadas às 9 transições, o vídeo tem
  3 blur e 3 dissolve no total.
- **Motion blur visível em ~1/3 dos cortes** (19 de 57), consequência de cortar no meio do gesto.
- O corte dominante é **jump cut**: mesma cena, mesmo enquadramento, o que muda é a pose/gesto de
  quem fala. Isso é a assinatura do estilo — não substitua por transições.
- Corte preferencialmente em **fronteira de fala** (fim de frase, fim de respiração).

### Preservar a fala é regra dura **[preferência do Gabriel]**

Três mecanismos, todos já implementados no `build_plan.py`:

| Regra | Valor | Por quê |
|---|---|---|
| Folga nas bordas | **160 ms** | 90 ms cortava o fim das frases |
| Remoção mínima | **100 ms** | Se remover a pausa renderia menos que isso, faça **corte seco sem remover**: ganho nulo, risco de decepar |
| Transição | silêncio **mantido**, corte no meio dele | `xfade`/`acrossfade` consomem o fim de A e o começo de B. Se a pausa foi removida, a transição **come fala** |

O terceiro é o mais traiçoeiro: é invisível no plano e só aparece assistindo. Uma transição de
300 ms sobre uma fronteira sem silêncio engole 300 ms de fala.

Três tipos de fronteira:

- `gap` — remove a pausa (silêncio ≥ 450 ms), com folga nas duas bordas;
- `pausa` — corte seco **no meio** de uma pausa curta, sem remover nada;
- `scale` — corte seco em fronteira de palavra; a visibilidade vem do salto de escala.

## 4. Transições

- Raras: ~3,5/min, no máximo ~15% das fronteiras.
- Duração: **260–367 ms**, típico **300 ms**. **[preferência do Gabriel]** — o relatório mede
  mediana 167 ms; ele pediu transições mais suaves.
- Distribuição observada: wipe (1/3), whip pan (2/9), e um caso cada de blur, fade-in, fade-out e
  dissolve.
- Easing observado nas 9 transições reais: `ease_out` (5), `linear` (2), indeterminado (2). Não há
  `ease_in_out` entre elas.
- Regra prática: use transição para marcar **mudança de assunto ou de bloco**, nunca como padrão
  recorrente entre planos.

## 5. Zooms e movimento

- ~24 eventos/min, mas **97% duram ≤ 333 ms** e a variação média de escala é de apenas
  **~2,2 pontos percentuais**.
- São reenquadramentos digitais discretos, não zooms ópticos dramáticos. Faixa útil:
  1,00 → 1,03/1,08.
- **O estilo recua mais do que aproxima:** ~62% são `zoom_out` contra ~34% `zoom_in`. Chamar tudo de
  "punch-in" é errado.
- Easing dominante é **`linear`** (~56%), não `ease_out` (~21%).
- Duas ancoragens, correlacionadas com o tipo: `center` (54%, ligada a zoom_out contínuo e linear) e
  `subject_face` (46%, ligada a punch-in/zoom_in).
- Pans/tilts são raros (~2/min) e majoritariamente tremulação natural, não movimento editorial.
- Câmera de base **estática**.

### Tremida — superamostragem é obrigatória

O `zoompan` arredonda a posição do recorte para **pixel inteiro** a cada frame. Num zoom de 2-3% o
passo por frame é ~1 px, então o arredondamento vira **tremida visível**.

Solução: ampliar **2,5×** antes do zoompan e reduzir depois. O erro de arredondamento cai para
~0,4 px na saída. Verificado por correlação de fase: passos suaves de 0,29 → 0 px, variação máxima
de 0,08 px entre passos consecutivos.

### Duração **[preferência do Gabriel]**

O relatório mede ≤ 333 ms. O Gabriel pediu efeitos mais suaves: use **~550 ms** com `ease_out`.

### Padrões dinâmicos — punch-in cut, volta e push lento **[v2.3, pesquisado]**

Pesquisa (premiumbeat, howtofilmschool, firecut, air.io, 26/08): o punch-in profissional é um
**corte seco para ~+10–15% de escala no momento de ênfase** — a dica principal, o número, a oferta.
Nunca aleatório: "se o corte aparece num momento qualquer, o espectador nota a edição em vez do
ponto". Depois o punch **volta ao aberto** — e a volta lenta é o que lê como cinematográfico
("slow = cinematic, fast = cheap"). Ritmo geral: estimular → acalmar → re-engajar.

Três padrões, aplicados pelo `build_plan.py` por cima da base (config em `zooms.patterns`):

| Padrão | O que faz | Onde entra |
|---|---|---|
| `punch_release` | corta para +10–14% no rosto e o zoom **volta suave** (1,4–2,6 s, ease_out) até o repouso | momento de virada/revelação |
| `punch_hold` | corta para +10–14%, **segura** fechado; o corte seguinte reabre o plano (o vizinho é forçado a repouso baixo para a reabertura ser visível) | a oferta, o número |
| `creep_in` / `creep_out` | push lento de 5–6% em 2–7 s, ease_in_out, no rosto | o plano-respiro (segmento mais longo) |

Colocação automática por conteúdo: pontua os segmentos (número = +3, palavra longa = +1) e escolhe
os picos, com teto de **3/min**, espaçamento ≥ 6 s, nunca no primeiro segmento nem colado em
transição, nunca dois vizinhos. No IMG_1171 caíram em "Foi aí que eu **descobri**"
(punch_release), na lista de benefícios (creep_in de 8,5 s) e em "conteúdo **100%** online
gratuito" (punch_hold) — exatamente os picos do roteiro.

### Salto de escala entre segmentos

Para o corte seco ficar visível **sem transição**, a escala de repouso precisa diferir entre
segmentos vizinhos: ≥ 0,026 em corte `scale`, ≥ 0,016 em corte com remoção (onde a pose já muda).
O `build_plan.py` resolve isso por busca.

Implementação: use `zoompan` (o filtro `crop` avalia `w`/`h` só na configuração e falha com
expressão temporal).

## 6. Desfoques

- ~2/min, gaussiano, quadro inteiro, **100 ms típico** (4 de 5 eventos; o quinto tem 333 ms),
  função estética pontual.
- Também aparece como **mecanismo de transição** (ver abertura).

## 7. Enquadramento e reenquadramento

- Predominante: **medium shot frontal, centralizado**, eye-level — 94% dos planos são `medium_shot`.
- Headroom não é uniforme: ~75% adequado, mas **~15% tem o topo da cabeça cortado de propósito**.
  Não "conserte" isso ao reenquadrar.
- Há um padrão de **composição em tela dividida** em ~18% dos planos (faixa escura sólida ocupando
  10–13% do topo ou da base, com captura de tela de um lado e a pessoa do outro). **Isso é
  composição, não letterbox** — não remova ao reenquadrar.
- **Nunca esticar a imagem.** Ao mudar a proporção:
  - se o recorte descartar ≤ ~20% da área útil → `smart_crop` centrado no sujeito;
  - caso contrário → **fundo desfocado** (`blurred_background`): cópia da imagem escalada para cobrir
    o canvas, com `gblur` forte, levemente escurecida e dessaturada, e o vídeo original encaixado por
    inteiro por cima.

## 8. Legendas — o elemento mais característico

> Esta seção foi **medida frame a frame** (306 linhas de texto isoladas por componentes conectados
> em 294 frames). Os números do relatório estavam bem errados no tamanho.

### Sistema
Revelação **palavra a palavra** ("pop-on" / karaokê): a primeira linha fica fixa e o bloco cresce
para baixo conforme novas palavras entram. Saída por substituição seca, sem fade-out.

**O fade de entrada vale só para a palavra nova.** Cada estado do karaokê é um evento ASS novo com
todo o texto acumulado; um `\fad` no evento inteiro faz **o bloco todo piscar** a cada palavra.
Use `\alpha&HFF&\t(0,150,\alpha&H00&)` apenas na palavra que acabou de acender.

### Tipografia

| Papel | Fonte | Uso |
|---|---|---|
| `normal` | Helvetica Neue **Bold** (700) | texto corrente — **toda** palavra sem serifa é Bold |
| `strong` | Helvetica Neue Bold (700) | igual ao normal (distinção morreu na v2.1) |
| `accent` | **Playfair Display Italic (400)** | expressão-chave enfatizada |

**A ênfase é por troca de família, não por cor.** MEDIDO na captura de estilo: traço/x-height da
sans = 0,225 e 0,209, contra 0,207 da HN Bold e 0,126 da Regular — a sans é **sempre Bold**.

### O serifado é composto MAIOR — e isso não é óbvio

No mesmo corpo, Playfair e Helvetica Neue têm x-height (ratio 1,019) e cap-height (1,000)
praticamente **iguais**. Mas na referência os glifos do serifado aparecem **1,5–1,7× maiores**:

| Frame | Helvetica | Playfair | ratio |
|---|---|---|---|
| "escreve" vs "roteiro" | 37 px | 55 px | 1,49 |
| "Vem comigo" vs "fazer" | 31 px | 47 px | 1,52 |

Ou seja: é **aumento deliberado do corpo**, não diferença de métrica. Use
`accent_size_ratio = 1.55` (na captura de estilo o ratio medido foi 1,51–1,56). Sem esse fator
a ênfase some visualmente.

### Métrica (medida)

- Corpo: típico **6,0% da altura do canvas**, faixa útil **4,8%–7,2%** (mediana 5,74% nos 294
  frames; a captura de estilo aprovada usa ~6,5%). Em 1920 de altura: ~115 px, faixa 92–138.
- Entrelinha: **1,205×** o corpo.
- Tracking **fechado**: −1,5 px em 1080 de largura (escalar proporcionalmente).
- **Espaço entre palavras encolhido para 55%** (`word_space_scale`): na referência o vão entre
  palavras é 0,25–0,35 x-height — com o espaço cheio da Helvetica ficava quase o dobro. Implementado
  com `\fscx55` no próprio caractere de espaço.
- Largura máxima do bloco: **82%** da largura; margem lateral **9%**.
- **Linhas curtas**: mediana ~8 glifos por linha. 1–2 linhas por bloco.

### Quebra de linha automática

Escolha o **maior corpo da faixa** em que o bloco cabe em até 2 linhas dentro da largura máxima,
medindo a largura real com as fontes (PIL/fontTools), já aplicando o `accent_size_ratio` nas
palavras de destaque e o tracking. Nunca deixe linha estourar. O `build_plan.py` faz isso.

### Cor
**`#FCF8F6`** — branco levemente quente, não `#FFFFFF` puro. Medido em 46 amostras de núcleo
erodido sobre fundo escuro (mediana RGB 252, 248, 246).

### Acabamento — halo difuso + glow do serifado **[v2.1, medido + preferência do Gabriel]**
- Sem contorno (`outline`), sem tarja de fundo, **sem sombra dura** — a sombra deslocada 4 px foi a
  diferença mais visível contra o estilo real.
- **Halo escuro difuso** (`soft_glow`): camada inferior com o mesmo texto, borda 8 px + blur 20 px,
  preto a 48%, dy 2 px. MEDIDO na captura de estilo: a luminância do fundo cai ~24 níveis com pico a
  ~13–16 px da borda e extensão ~30 px (escala 1080), quase simétrico. É esse halo que dá a
  impressão de "glow/degradê" — nos glifos em si **não há gradiente** (delta ~4 níveis = compressão).
- **Glow claro e curto só no serifado** (`accent_glow`): camada entre o halo e o texto, branco a
  60%, borda 2,5 px + blur 6 px, apenas nas palavras Playfair — como em "agente"/"IA" da referência.
  As demais palavras ficam invisíveis nessa camada para o layout da linha não mudar.
- Cor de preenchimento **#FBF8F4** em todas as famílias.

### Posição **[preferência do Gabriel]**

A referência alterna três faixas (~52% inferior, ~40% rodapé, ~9% superior) e mistura alinhamento
centro (45%) com esquerda (25%).

**O Gabriel não quer isso.** Reclamou que a legenda "do nada vai pra outra posição e fica indo pros
cantos". O padrão é:

- **posição vertical única**: topo do bloco em **0,62** da altura, em todos os blocos;
- **sempre centralizado**.

A única variação que resta é o bloco crescer para baixo quando entra a segunda linha — isso é o
karaokê funcionando, não deslocamento.

**A altura não é um número fixo — é medida no vídeo.** `scripts/detect_subject.py` detecta o rosto
(YuNet) em 40 amostras e deriva:

```
âncora = queixo_p98 + max(0,035 ; 0,20 × altura_da_face)     presa em [0,42 ; 0,72]
```

No IMG_1171: queixo em 0,559, face de 0,228 → âncora **0,605**. Antes esse número era medido a olho
(0,62) e só valia para aquele enquadramento — numa pessoa mais perto ou mais afastada da câmera,
errava. O `0,62` que sobrou no perfil é apenas o **fallback** para quando não há rosto detectado.

O mesmo `subject.json` define até onde uma inserção no topo pode descer
(`head_top = testa_p02 − 0,30 × altura_da_face`), que também era medido a mão.

Só use âncora diferente se o usuário pedir, ou se uma **inserção gráfica** ocupar a mesma faixa
naquele instante (aí a legenda sai da frente).

### Pausas
Intervalos sem legenda entre blocos fazem parte do estilo, mas **não force**: quando a fala é
contínua, a troca é seca (substituição), sem pausa artificial.

## 9. Imagens e elementos gráficos

- ~3,9 inserções/min no material de referência.
- Sempre **sobreposição plana**: sem parallax, sem profundidade, blend normal, opacidade 100%.
- Entrada rápida por fade (~350 ms); saída por fade curto (~300 ms).
- Praticamente **estáticas** durante a exibição.
- Duração muito variável: 0,5 s a 21,5 s (mediana ~1,6 s).
- Devem **fazer sentido com o que está sendo dito naquele instante**.

### Margens — nunca colar nas bordas **[preferência do Gabriel]**

| Parâmetro | Valor |
|---|---|
| Respiro do topo | **3,5%** da altura |
| Largura máxima | **86%** (nunca colada nas laterais) |
| Base da imagem | acima de **~20,5%**, sempre acima de onde começa a cabeça |

**A faixa livre vem do `subject.json`**, não de medição manual: `head_top` é derivado da testa
detectada menos 0,30 × altura da face (folga para o volume do cabelo). No IMG_1171 isso dá 0,204,
então a inserção vai de 3,5% a 19,2%.

Cantos levemente arredondados (`rounded_rect`, raio ~3%) integram melhor que canto reto.

### De onde vêm as imagens

**Acervo Creative Commons quase nunca serve** para nicho comercial. Testado em 4 rodadas
(Openverse + Wikimedia) para "tráfego pago", "leads", "IA", "follow-up", "corretoras do Brasil",
"dinheiro na mesa": só devolveu foto documental e clipart genérico — fachada de corretora
britânica, mapa da América do Sul, screenshot de benchmark de LLM, cerimônia em Gana. Pior: os PNGs
marcados como "transparent background" vêm com o **xadrez pintado na imagem**, sem canal alfa
(tentei três algoritmos para recuperar o alfa; nenhum ficou limpo).

Use `scripts/fetch_images_apify.py` (Google Images via Apify, token em `.credentials.json`).

**O que vem de lá tem direitos autorais.** Sempre:

1. **Olhe cada imagem** — relevância é decisão sua.
2. **Recorte marcas de terceiros**, principalmente de **concorrentes do usuário**.
3. **Avise no resumo final** e sugira trocar por material próprio dele.
4. Se nada pertinente aparecer, **omita** e registre em `limitations`. Nunca use asset genérico de
   preenchimento.

### Só imagem real **[v2.4, preferência do Gabriel]**

Ele viu a primeira entrega e pediu: *"imagem do whatsapp real mesmo como ele é e não uma edit ou
feito com IA, ou imagem feita no photoshop"*.

Só vale **print de tela** ou **fotografia**. Estão proibidos mockup vetorial, render 3D de celular,
arte generativa e composição de Photoshop — inclusive os bem-feitos.

| Sinal de **mockup** | Sinal de **print real** |
|---|---|
| "Lorem ipsum dolor sit amet" | barra de status com hora, bateria, operadora |
| balões perfeitamente uniformes e repetidos | textos de tamanhos irregulares, conteúdo específico |
| avatar como círculo chapado ou silhueta | fotos de perfil de pessoas de verdade |
| 09:41 ou 12:30 repetido em todos os painéis | horários variados |
| fundo colorido chapado atrás do aparelho | reflexo, moiré, dedo, borda do aparelho |
| "template", "UI kit", "PSD", "IMAGE NOT INCLUDED" | — |

**Privacidade:** descarte print real que exponha **nome + foto de pessoa privada identificável**
(lista de conversas com contatos reais). Num vídeo comercial isso é risco — há decisão do STJ sobre
divulgação de print de conversa de WhatsApp. Prefira print sem nome visível, ou recorte.

Cuidado com o efeito colateral: quase todo print de "caixa de entrada cheia" que existe na web
pública vem de **artigo de tutorial**, e chega com seta vermelha desenhada por cima, nome borrado
(cara de censura) ou marca d'água de blog. Todos os três leem como "editado" e o Gabriel rejeita.

Quando o assunto é o produto **dele**, o melhor asset não está na web: é um print do próprio
celular/sistema do usuário — real, em português, no contexto certo, sem direitos de terceiros e sem
expor ninguém. **Peça.** Vale mais que qualquer rodada de busca.

### A armadilha da página de bloqueio **[v2.4, medido]**

Sites de SEO-spam (billionhands, findarticles, accio, spora, nollymove…) respondem ao hotlink com um
**JPEG válido de 1344×768** contendo só o texto *"This site does not have permission to access or
serve this content"*. Passa por qualquer filtro de tamanho e de domínio.

Medido em **217 candidatas de 24 consultas** (26/08/2026):

| O que veio | Quantas |
|---|---|
| página de bloqueio de hotlink | **86** |
| mockup vetorial / render 3D / composição | 48 |
| print ou fotografia real | 33 |
| irrelevante | 50 |

O `fetch_images_apify.py` agora tem `looks_like_block_page()`, que pega no pixel: bloqueio tem
**saturação ≤ 0,0028, 13–16 tons e ≥ 47% de branco**; imagem legítima tem saturação ≥ 0,012 e ≥ 19
tons. Verificado: **86/86 pegos, 0 falso positivo em 131**. O que ele barra vai para
`<outdir>/rejeitadas/` e fica listado em `images.json` — nada some calado.

> **Contra-intuitivo:** a página de bloqueio tem **16 tons**, não 2 — texto preto suavizado sobre
> branco gera a rampa de cinza inteira. Um limite de "poucos tons" não pega nada. Quem separa é a
> **saturação**: a página de bloqueio não tem um único pixel colorido.

Duas consequências práticas:

- **Peça 30 resultados por consulta**, não 3. Você vai descartar ~85%.
- **Consulta abstrata atrai o spam.** "gráfico de conversão", "ampulheta tempo passando" e "dinheiro
  na mesa" voltaram 100% bloqueio; "whatsapp", "excel line chart" e nome de produto voltaram
  resultado real. Se uma consulta só devolve bloqueio, troque o termo por algo concreto em vez de
  insistir.

Quando o full falha ou vem bloqueado, o `thumbnailUrl` aponta para `encrypted-tbn0.gstatic.com`, que
baixa sempre e costuma ter 500–740 px — suficiente, já que a inserção raramente passa de 1240 px.
O script cai para ele sozinho (`--no-fallback-thumb` desliga).

### A caixa é dimensionada pela folga do TRECHO — e a 16:9 entra inteira **[v2.6, medido]**

A folga acima da cabeça **varia** ao longo do vídeo: no cida-inss a testa oscilou entre **0,25 e
0,40 da altura** conforme ela se inclinava. Usar o p02 global desperdiça até metade do palco.

O `build_plan.py` agora mede o topo da face (YuNet) **dentro da janela de cada inserção** (timeline
de saída mapeada de volta à fonte) e deixa a imagem descer até **26 px antes da testa** — invade só
o alto do cabelo, nunca o rosto. Com o palco medido, a caixa **prefere a imagem inteira**: aspecto
da própria imagem, largura até 86%. Medido: caixa 928×522 (16:9 **sem corte nenhum**) onde o
global dava 890×340 com corte. Só cai no *cover* se a imagem inteira ficar mais estreita que 0,31
da largura. Sem detecção na janela, vale o limite global do `subject.json` (o relatório avisa).

Duas inserções na **mesma janela de push trocam por corte seco**: fade cruzado soma os dois alfas
sobre o palco (dupla exposição, medido em frames), e o intervalo entre fades deixa a faixa vazia.

### Imagem vertical vira cartão central **[v2.6, preferência do Gabriel]**

Imagem em pé (aspecto < ~1,15) na faixa renderiza com ~1/4 da largura — ilegível. Pedido do
Gabriel (26/08, aprovado "ficou perfeito"): ela vira um **cartão grande no centro**:

- vídeo inteiro **desfocado** atrás (`gblur` full_frame, σ 26) — a pessoa continua lá;
- imagem com **~58% da altura** do canvas, centrada;
- a **legenda desce para logo abaixo da imagem** (âncora `footer` recalculada): imagem+legenda
  formam um componente único **centrado na vertical**;
- janelas em **fronteira de bloco**: desfoque, cartão e reposição da legenda mudam no MESMO frame;
- cartões vizinhos dividem **um** desfoque e trocam por **corte seco**; entrada/saída secas
  (fade em cartão cheio deixa a pessoa "fantasma" sobre o fundo);
- com janela de push logo depois, o cartão termina **exatamente no down_start** dela — desfoque
  sai, vídeo desce, faixa entra, sem buraco.

No render o cartão é um overlay clássico (entra **antes** das legendas no filtergraph, passo 6),
por isso o texto fica por cima; o desfoque é um evento `blurs` comum. Parâmetros em
`graphics_overlays.center_card`.

### A proporção manda mais que a resolução **[v2.4]**

A faixa útil fica entre o topo e o `head_top` medido — tipicamente **~15% da altura do canvas**.
Como a altura está travada, a **largura sai da proporção da imagem**, e ela precisa alcançar o
mínimo de 0,31 da largura do canvas. Isso exige **proporção ≥ ~1,15:1**.

**Print de celular em pé não serve.** A 0,46:1 ele renderiza com ~13% da largura — ilegível. Ou
recorte uma **faixa horizontal** com a parte que comunica, ou procure **foto do aparelho na mão ou
na mesa**, que já vem deitada. No IMG_1169 as três inserções ficaram entre 2,0:1 e 2,3:1.

### Suavidade é regra dura **[v2.3.1, medido]**

O "tranco" tinha três causas, todas medidas por correlação de fase e corrigidas:

1. **Movimento em cima do corte**: `ease_out` tem velocidade máxima no primeiro frame — a imagem já
   deslizava a ~3 px/frame no frame seguinte ao corte. Agora **todo zoom tem `start_offset`**
   (0,12 s nos settles, 0,35 s nos punches) e easing `ease_in_out`: o corte assenta parado e o
   movimento entra e sai com velocidade zero. O punch_hold é **estático de verdade**.
2. **Gagueira em movimento lento**: com supersampling fixo 2,5×, o creep (~0,3 px/frame) alternava
   0,75 → 0,05 → 0,75 px. O fator agora é **adaptativo** (2,5× a 6× conforme a velocidade).
3. **Renormalização esticando settles**: mover só o `scale_from` de um vizinho criava settles de ~5%
   (varredura de 6,7 px/frame). O renorm desloca o settle **inteiro** (from e to juntos).

## 10. Abertura

Mecanismo único e reconhecível:
- Duração **700 ms**, easing `ease_out`, escala 1,08, sigma 18. **[preferência do Gabriel]**
- **[v2.3.2]** O movimento é o **zoom do primeiro segmento** (herda o supersampling; se o primeiro
  corte cair antes de ~0,95 s, o `build_plan` funde os dois primeiros segmentos). O desfoque é
  **gaussiano com sigma animado frame a frame** (um `gblur` por frame, sigma = σ₀·(1−p)²).
  Não use degraus largos (pulsam) nem crossfade nítido+desfocado (cara de dupla exposição — o
  usuário rejeitou: "tem que ser aquele desfoque gaussiano").
- Começa em **close desfocado e ampliado** e resolve simultaneamente **desfoque → 0** e
  **escala → 1,0**. Os valores concretos (escala inicial ~1,14, sigma ~26) são **parâmetros de
  reprodução**, não medições: o relatório mede a abertura por variância do Laplaciano (2,08 no frame
  0, o mínimo do vídeo) e descreve o efeito, sem número de escala nem de sigma.
- **Não** é fade de opacidade, **não** há tela de título, logo ou cartela.
- A primeira legenda entra quase imediatamente (~200 ms).

## 11. Encerramento

- Referência (medida): **corte seco**, sem fade, sem cartela, sem freeze.
- **[preferência do Gabriel, 01/09/2026 — prevalece]**: *"no final do vídeo coloque fade out no
  áudio e a tela ficando preta"*. Padrão desde a v2.8: vídeo escurece em **1,0 s**
  (`fade=t=out`) e o áudio apaga em **1,3 s** (`afade`), os dois terminando no último frame — o
  áudio começa a cair 0,3 s antes da imagem, então a voz some suave enquanto a tela já escurece.
- A cauda do plano cresce para comportar o fade **depois** da última palavra (`tail = última
  palavra + 0,26 + audio_fade_s`); senão o fade come o fim da frase. Em vídeo em trechos a última
  parte precisa ter essa sobra: `concat_parts.py --last-tail-extra 1.4`.
- Continua sem cartela, sem logo final, sem freeze.

## 12. Cor e acabamento

- Look **quente e discreto**, "vídeo social com tratamento cosmético".
- Contraste médio (curva S suave), **saturação média** (assim classificada em 87 dos 88 planos),
  meios-tons e realces puxados para laranja/dourado. Sem teal.
- Sombras: o relatório descreve tons quentes/amarronzados só no menor dos clusters; os clusters
  maiores trazem sombras neutras a levemente frias. Aquecer as sombras é **escolha estética**, não a
  média medida.
- **Sem** grain, **sem** aberração cromática, **sem** letterbox. Vinheta é rara (sutil em um cluster).
- Nenhum valor numérico de grading existe no relatório — os parâmetros de `eq`/`colorbalance` no
  perfil são tradução do guia de reprodução ("+5 a +10 de temperatura, curva S suave").
- Sharpening leve, sem halos. Bloom discreto nas áreas claras.
- Uniformidade alta: o mesmo look em praticamente todos os planos.

## 13. Áudio

- Preservar continuidade da fala acima de tudo. **Nunca cortar no meio de sílaba.**
- Remover apenas silêncios ≥ ~450 ms, mantendo ~90 ms de folga nas bordas.
- Crossfade de áudio **apenas** onde houver transição de vídeo, com a mesma duração (mantém A/V em
  sincronia, já que `xfade` e `acrossfade` encurtam igualmente).
- Normalizar para ~-14 LUFS, true peak -1,5 dB.
- **Sem música** por padrão.

> Nada nesta seção é medido: o relatório não analisa LUFS, limiar de silêncio nem crossfade. São
> defaults de engenharia.

## 14. Exportação

MP4 / H.264 (`libx264`) / `yuv420p` / perfil high / `+faststart`, tags de cor bt709 limited.
Qualidade alta: CRF 18, preset `slow`. Rascunho: CRF 26, preset `veryfast`.
Áudio AAC 48 kHz, ~224 kbps, estéreo. Preservar o FPS do original.

> Também não medido. O áudio **original** é HE-AAC 44100 Hz / 56 kbps; 48 kHz / 224 kbps é escolha
> de entrega, não reprodução da fonte.

---

## 15. Regras de adaptação (o que nunca fazer)

1. Não reutilizar timestamps absolutos do vídeo de referência — só taxas, proporções e faixas.
2. Não esticar a imagem em nenhuma hipótese.
3. Não aplicar transições/zooms acima da frequência do perfil.
4. Não cortar sílaba, respiração ou início/fim de palavra.
5. Não inventar dados, logotipos ou marcas.
6. Não adicionar música sem arquivo fornecido pelo usuário.
7. Não alterar o sentido das falas.
8. Remover pausas só com confiança suficiente; teto de ~35% da duração original.
9. **Nunca cortar enquanto a pessoa fala** — folga de 160 ms, remoção mínima de 100 ms, e nas
   transições o silêncio é mantido com o corte no meio dele.
10. Nunca reintroduzir `fps` logo depois de `zoompan` (multiplica os frames) nem zoom sem
    superamostragem (treme).

## 16. Vídeo em trechos — corte por parte **[v2.7, pedido do Gabriel 01/09]**

Clipe gerado (Veo, influencIA) tem ~8 s fixos: a fala acaba e o vídeo continua 1–2 s parado. Dez
partes concatenadas cruas = 15–20 s de ar morto e emendas moles. O pedido foi ficar **"cortadinho
certinho, igual acontece quando é renderizado no influencIA"**, e `scripts/concat_parts.py` copia
a regra do `normalizeTrimConcat` (`artifacts/api-server/src/lib/remotion-renderer.ts`):

| Medição | faster-whisper por palavra + `silencedetect=noise=-25dB:d=0.15` |
|---|---|
| Começo | silêncio que começa em < 0,05 s e termina até 0,2 s após a 1ª palavra → fim do silêncio − 0,05; senão 1ª palavra − 0,08 |
| Fim | última palavra + 0,15 s |
| Sem fala | começo do silêncio final + 0,05; sem silêncio: duração − 0,5 |

**Proteção que o influencIA não tem:** o Whisper costuma fechar a última palavra cedo. Se no ponto
de corte a energia ainda não caiu (o instante não está dentro de um silêncio medido), o fim anda
até o próximo silêncio + 0,05 (no máximo 0,6 s). Regra 5 (nunca cortar enquanto fala) vale aqui
também. Cada parte é re-encodada (crf 12, fade de 12 ms nas bordas para não estalar) e o concat é
sem re-encode.

Medido no Fable 5.1 (10 partes, 80 s): ar morto removido por parte entre 0,35 s e 2,39 s; total
80 → 60,2 s **antes** do `build_plan`, que depois só achou mais 1,0 s de pausa para tirar. As
emendas entre partes ficam com ~0,2 s de respiro (0,15 do fim + 0,05 do começo) — o mesmo ritmo do
influencIA.

**Balbucio da voz gerada não é pego pela máquina.** A parte 9 tinha 6,4 s de fonemas sem sentido
("Oristote Paracosfinete do Meto Borsenias…"): small, medium e large-v3 transcrevem como palavras,
o `avg_logprob` não denuncia, e o rabo vaza para os 0,24 s iniciais da parte 10 (o que impede a
regra do começo de disparar, porque ela exige silêncio desde 0,05 s). Só a leitura da transcrição
impressa pega. Correção por `--overrides` em segundos locais da parte, igual ao
`ClipTrimOverride`: `{"parte9.mp4": {"end": 1.58}, "parte10.mp4": {"start": 0.62}}`.

## 17. Logo de marca em motion design **[v2.7, pedido do Gabriel 01/09, aprovado]**

Pedido: *"quando fala no começo do Fable seria interessante aparecer o logo com efeito de entrada
de baixo pra cima e depois saindo no estilo motion design… pra ficar cinematográfico e bonito"*,
com uma referência do logo do Claude aceso em laranja no peito do moletom. Generalizado para
qualquer empresa citada (*"quando falar de alguma empresa como openai, anthropic etc"*).

### Asset
Só logotipo **oficial**, de fonte registrada (`references/brand-logos.json`): favicon/SVG do site
da empresa ou o SVG oficial hospedado na Wikimedia Commons. Rasterizado em 2048 px com canal alfa
(`assets/logos/<marca>.png` + `.json` de procedência). O renderer usa **só o alfa** — a cor vem da
paleta da marca, então wordmark preto (Anthropic) funciona igual. SVG com fundo chapado perde o
fundo por `remove_fill` (ChatGPT `#74aa9c`, Microsoft `#f3f3f3`); ícone branco sobre fundo escuro
usa `alpha_from_luma` (Perplexity). Marca sem fonte oficial (xAI) é **pulada**.

### Paleta (derivada da cor-base)
bloom = cor mais saturada, halo = cor clara, núcleo = cor dessaturada e clara, brilho = quase
branco. Base com saturação < 0,12 (OpenAI branco) recebe neon frio azulado. Composição de trás
para frente, alpha-over, com o fundo escuro isso lê como aditivo:

| Camada | Blur (unidade = tamanho/340) | Alfa |
|---|---|---|
| bloom | σ 74 (v2.7: 62) | 0,61 × pulso (v2.7: 0,72) |
| halo | σ 22 (v2.7: 18) | 0,72 × pulso (v2.7: 0,85) |
| mark | — | 1,0 |
| núcleo quente | máscara × densidade^1,35 (blur 0,155×tamanho, normalizado) | 0,68 × pulso (v2.7: 0,80) |

v2.8 (pedido 01/09): *"o glow deixe 15% mais fraco e um pouco maior o range"* — alfas ×0,85 e
σ ×1,2; o tile ganhou folga de 0,55×tamanho para o bloom não cortar na borda.

A "densidade" é o mark desfocado: alta no miolo, baixa nas pontas — é o que deixa o centro
branco-quente e as pontas na cor, como um neon de verdade.

### Movimento (valores aprovados)
| Fase | Duração | O que acontece |
|---|---|---|
| entrada | 0,66 s | sobe 250 px (em 1920) com `ease_out_back` (overshoot 1,28), escala 0,80→1, alfa smoothstep em 0,30 s, brilho +55% decaindo |
| sustentação | 1,00 s | brilho respira +14% (seno); **flutua** (v2.8): seno de ±0,45% da altura em y (2,2 s) e ±0,2% da largura em x (3,1 s), ganho smoothstep durante a subida — "como se tivesse flutuando, margem curta" |
| saída | 0,54 s | sobe 150 px com `ease_in_cubic`, escala →1,07, alfa cai por smoothstep a partir de 8% |

Entra **0,32 s depois de a palavra acender** (a menção fica com o logo já no meio da subida).
Espaço mínimo de **10 s** entre animações. Menção que cai em push-down, cartão central, desfoque
ou trecho removido é pulada: o quadro está deslocado e o logo, em espaço de tela, flutuaria.

### Posição (derivada do plano, não medida a olho)
Faixa útil = do **fundo da legenda de 2 linhas no maior corpo** (+ halo 1,2%) até a **reserva de
UI do Reels** (11,5%). Mark compacto (aspecto ≤ 1,6): largura 26,7% do canvas (288 px em 1080),
topo encostado na faixa. Wordmark (aspecto > 1,6): largura até 60%, centrado na faixa. No Fable
5.1: faixa 0,736–0,885, `cy` 0,811 — o primeiro teste a 0,781 com 330 px colidia com a segunda
linha ("saiu") da legenda; a 0,812/288 px sobrou 65 px de folga. A saída para cima cruza a área
da legenda, mas com `ease_in` o logo só anda de verdade quando já está quase apagado.

### Composição
Sequência RGBA de canvas inteiro **começando em t = 0** (frames vazios até o evento; PNG
transparente comprime a ~4 KB) e `overlay=0:0:eof_action=pass:format=auto` sobre o render — uma
entrada só, sem `itsoffset`, sem `-loop`. Segunda passagem de encode (render em crf 14 → final
crf 18, áudio copiado). `-t` casa a duração com o vídeo: o AAC sai ~67 ms mais longo que os
frames e o `validate_output` procura um frame em `duração − 0,10` que não existe.
