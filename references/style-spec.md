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

- **posição vertical única**: topo do bloco em **0,55** da altura, em todos os blocos;
- **sempre centralizado**.

A única variação que resta é o bloco crescer para baixo quando entra a segunda linha — isso é o
karaokê funcionando, não deslocamento.

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

**Meça onde começa a cabeça** nos frames extraídos — é isso que define a faixa livre. No IMG_1171 o
cabelo começava em 23,7% da altura, então a faixa útil era 3,5%–20,5%.

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

## 10. Abertura

Mecanismo único e reconhecível:
- Duração **550 ms**, easing `ease_out`. **[preferência do Gabriel]** — o relatório
  mede 367 ms; ele pediu efeitos mais suaves, com desfoque e escala iniciais menores (sigma 20,
  escala 1,10 em vez de 26 / 1,14).
- Começa em **close desfocado e ampliado** e resolve simultaneamente **desfoque → 0** e
  **escala → 1,0**. Os valores concretos (escala inicial ~1,14, sigma ~26) são **parâmetros de
  reprodução**, não medições: o relatório mede a abertura por variância do Laplaciano (2,08 no frame
  0, o mínimo do vídeo) e descreve o efeito, sem número de escala nem de sigma.
- **Não** é fade de opacidade, **não** há tela de título, logo ou cartela.
- A primeira legenda entra quase imediatamente (~200 ms).

## 11. Encerramento

- **Corte seco.** Sem fade-out, sem dip-to-black, sem cartela final, sem freeze.
- O vídeo simplesmente termina sobre o plano de conteúdo. Isso é deliberado; mantenha.

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
