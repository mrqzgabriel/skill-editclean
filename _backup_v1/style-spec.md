# EditClean — especificação técnica do estilo

Conteúdo técnico extraído de `ANALISE_TECNICA_EDICAO_VIDEO_REFERENCIA.md`, reduzido ao que é
necessário para **executar** uma edição. Material descritivo, timestamps absolutos do vídeo de
referência e seções de auditoria foram removidos — o que importa aqui são as regras aplicáveis a
qualquer vídeo.

Os valores numéricos operacionais vivem em `style-profile.json`. Este documento explica **como
interpretá-los**.

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
- Corte preferencialmente em **fronteira de fala** (fim de frase, fim de respiração), respeitando
  ~90 ms de folga para não decepar sílaba nem respiração.

## 4. Transições

- Raras: ~3,5/min, no máximo ~15% das fronteiras.
- Duração curta: **100–367 ms** (3–11 frames a 30 fps), mediana ~167 ms.
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

### Sistema
Revelação **palavra a palavra** ("pop-on" / karaokê): a primeira linha fica fixa e o bloco cresce
para baixo conforme novas palavras entram. Saída por substituição seca, sem fade-out.

### Tipografia
Duas famílias alternadas **dentro do mesmo bloco**:

| Papel | Fonte | Uso |
|---|---|---|
| `normal` | Helvetica Neue Regular (400) | texto corrente |
| `strong` | Helvetica Neue Bold (700) | linha/trecho de peso |
| `accent` | **Playfair Display Italic (400)** | expressão-chave enfatizada |

**A ênfase é feita por troca de família, não por troca de cor.** Todas as variantes são
`#FFFFFF` — inclusive o serifado. Diferença de tom percebida em frame comprimido é artefato, não
design.

> As duas famílias foram identificadas pelo usuário olhando um frame do vídeo. O relatório só tinha
> estimativas (Arial / Georgia / Times / Bodoni, confiança 46–68); a identificação do usuário
> prevalece.

Escolha das palavras `accent`: substantivos e expressões-chave curtas. **Nunca** artigos,
preposições ou conjunções. Cerca de 18% das palavras.

### Métrica
- Corpo: **~4,0% da altura do canvas** (faixa 3,1–4,5%; mediana 4,06%).
- Entrelinha: **~1,28×** o corpo.
- Tracking **fechado** (negativo leve); espaço entre palavras reduzido.
- Largura máxima do bloco: **76% da largura** do canvas.
- 1–2 linhas por bloco, 3–7 palavras.

### Acabamento
- Sem contorno (`outline`), sem tarja/caixa de fundo.
- Sombra escura **sutil e nem sempre presente**: metade das instâncias catalogadas não tem sombra
  nenhuma. Como padrão seguro: deslocamento ~2 px, desfoque ~3 px, alpha ~0,62.

### Ancoragem vertical (varia de propósito)
| Âncora | Topo do bloco | Frequência | Quando |
|---|---|---|---|
| `lower_default` | ~59% da altura | ~70% | padrão |
| `footer` | ~76% | ~20% | variante mais baixa |
| `upper` | ~15,5% | ~10% | quando o rosto/gesto ou um gráfico ocupa a metade de baixo |

Margem lateral mínima observada: **11,1%**. Área segura: 8% topo, 10% base, 6% laterais.

As frequências 70/20/10 acima são **estimativa qualitativa** ("a inferior vale na maior parte do
vídeo"), não frequência medida — o catálogo de 6 instâncias é amostra de variação (2/2/2).

### Pausas
Intervalos de 0,1–1 s **sem legenda** entre blocos fazem parte do estilo. Não preencha à força.

## 9. Imagens e elementos gráficos

- ~3,9 inserções/min no material de referência.
- Sempre **sobreposição plana**: sem parallax, sem profundidade, sem sombra projetada, blend normal,
  opacidade 100%.
- Entrada rápida por fade ou pop de escala (170–330 ms); saída abrupta ou fade curto.
- Praticamente **estáticas** durante a exibição.
- Zonas típicas: terço superior, centro, **centro inferior** (sobre o torso), ao lado do sujeito.
- Largura de **31% a 100%** do canvas, com **80% sendo o valor típico**.
- Duração muito variável: de **0,5 s a 21,5 s** (mediana ~1,6 s).
- Cantos em geral retos, mas há exceções (uma cápsula de raio alto, um cartão de raio moderado).
  Sombra é rara. Opacidade 98–100%.
- Devem **fazer sentido com o que está sendo dito naquele instante** — a inserção acompanha o
  assunto da fala, entrando junto com a menção e saindo quando o assunto muda.

### De onde vêm as imagens
Além de arquivos que o usuário fornecer, a skill busca imagens pertinentes com
`scripts/fetch_images.py`, que consulta acervos **Creative Commons** (Openverse e Wikimedia Commons,
sem necessidade de chave de API). O termo de busca sai do que está sendo dito no trecho.

- Qualidade mínima aceita: lado maior ≥ 900 px e área ≥ 480.000 px. O script classifica cada imagem
  como `media` ou `boa`; prefira `boa`.
- **Confirmação visual é obrigatória**: abra cada candidata e descarte a que não corresponder ao que
  está sendo dito.
- Se nada pertinente aparecer, **omita a inserção**. Nunca use imagem genérica de preenchimento.
- Licença e autor de cada imagem ficam em `images.json` e devem ser repassados ao usuário — várias
  licenças CC exigem crédito na publicação.

## 10. Abertura

Mecanismo único e reconhecível:
- Duração **~367 ms** (11 frames a 30 fps), easing `ease_out`.
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
