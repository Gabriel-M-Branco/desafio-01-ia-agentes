# Etapa 1 — Desenho do Processo, Quadro PEAS, Aritmética dos Passos e Autonomia

Este documento especifica o desenho arquitetural do sistema de instrução de pedidos de diárias da Coordenadoria de Diárias e Passagens da SEMA-MT (regido pela Instrução Normativa hipotética SEMA nº 07/2026), estabelecendo o fluxo manual atual, o fluxo com o agente Agno, o quadro PEAS, o cálculo de confiabilidade composta, a estimativa analítica de consumo de tokens confrontada com a medição empírica e o posicionamento no quadrante de autonomia.

---

## 1. Processo Atual (Execução Manual pelo Servidor)

Hoje, cada pedido protocolado na Coordenadoria de Diárias e Passagens é instruído manualmente por um servidor conferente seguindo **10 etapas sequenciais**:

1. **Leitura do pedido protocolado**: O servidor abre o formulário do pedido e identifica número do processo, data do protocolo (`data_pedido`), nome do solicitante, matrícula informada, município/UF de destino, `data_partida`, `data_retorno`, meio de transporte e justificativa.
2. **Exame preliminar de completude (Art. 9º)**: Confere se todos os campos essenciais estão preenchidos (em especial a `data_retorno`, indispensável para a contagem de pernoites).
3. **Consulta ao cadastro funcional (`servidores.csv`)**: Pesquisa a matrícula informada para localizar o registro funcional do servidor, obtendo nome oficial, cargo, grupo de diária (`A`, `B` ou `C`), sigla da unidade de lotação (`GAB`, `CFF`, `CFA`, `CUC`, `CRH`, `URS`) e município-sede.
4. **Conferência de titularidade cadastral (Art. 9º)**: Verifica se a matrícula existe e se o nome registrado no cadastro funcional corresponde exatamente ao nome do solicitante no pedido (evitando instrução no cadastro de outro servidor por erro de digitação de matrícula).
5. **Devolução em diligência quando incompleto ou divergente (Art. 9º)**: Caso falte dado obrigatório (etapa 2) ou haja divergência cadastral (etapas 3 e 4), o servidor interrompe a instrução sem análise de mérito e devolve o processo ao solicitante em **diligência**, aguardando futura complementação (quando precisará reconstituir o caso).
6. **Consulta ao histórico e cálculo de prazo de prestação de contas (Art. 7º)**: Quando o cadastro e os dados estão completos, consulta `historico_diarias.csv` para verificar se o solicitante possui viagem anterior com `prestacao_contas == "pendente"`. Para cada pendência, conta **5 dias úteis** após a respectiva `data_retorno` e compara com a data da análise (`2026-10-09`), distinguindo prestação pendente ainda no prazo (regular) de prestação vencida (impeditiva).
7. **Apuração do limite mensal de diárias (Art. 6º)**: Soma a quantidade de diárias já concedidas ao servidor no mesmo mês civil da `data_partida` e verifica se, acrescida das diárias do novo pedido, permanece dentro do teto de **10,0 diárias por mês civil**.
8. **Cálculo da quantidade e do valor total das diárias (Arts. 3º e 4º e Anexo I)**: Calcula o número de pernoites `(data_retorno - data_partida).days`, aplica a regra de **1 diária por pernoite + 0,5 diária no dia do retorno** (ou **0,5 diária** para deslocamento sem pernoite, ida e volta no mesmo dia), classifica o destino (`interior_mt`, `outra_uf` ou `distrito_federal`), localiza o valor unitário do grupo (`A`, `B` ou `C`) no Anexo I e multiplica pela quantidade.
9. **Verificação de antecedência mínima e exame de urgência (Art. 5º, §§ 1º e 2º)**: Calcula a antecedência em dias corridos `(data_partida - data_pedido).days` frente ao mínimo de **10 dias corridos**. Se for menor que 10 dias, avalia se a justificativa descreve situação emergencial imprevisível (incêndio florestal em curso, desastre ambiental, infração em curso ou ordem judicial com prazo — § 1º) e sinaliza a exigência de autorização expressa e escrita do Secretário Adjunto (§ 2º, não suprida por autorização verbal).
10. **Consulta ao saldo orçamentário da unidade e redação do despacho (Arts. 8º e 10)**: Consulta `unidades.json` pela sigla da unidade de lotação do servidor, compara o `saldo_diarias` com o valor total calculado, redige a minuta de despacho técnico com a recomendação (`apto_para_autorizacao`, `diligencia` ou `nao_recomendado`) e encaminha ao ordenador de despesa para deferimento ou indeferimento.

---

## 2. Processo com o Agente Autônomo (Agno + Barreira + Conferência Humana)

Com a introdução do agente construído no framework **Agno**, o fluxo passa a operar em **7 etapas integradas**, combinando automação, determinismo aritmético e supervisão humana:

1. **Entrada e Filtro de Dados Pessoais (`PIIDetectionGuardrail`)**: O pedido protocolado (ou a complementação de diligência) é recebido pela aplicação. Antes de qualquer chamada à API do modelo ou gravação no banco SQLite, o `PIIDetectionGuardrail` (com padrões norte-americanos desligados e `mask_pii=True`) mascara ocorrências de máscara de CPF (`\d{3}\.\d{3}\.\d{3}-\d{2}`) e dados de conta/agência bancária colados na justificativa, preservando intactos matrículas, datas e números de pedido.
2. **Recuperação de Contexto por Sessão (`SqliteDb`)**: A execução é invocada com `session_id = numero_pedido` e `user_id = matricula` diretamente em `agent.run()`, mantendo um único agente em cache. Quando se trata de retorno de diligência, o histórico da sessão (`add_history_to_context=True`, `num_history_runs=3`) permite ao agente recuperar os dados do pedido original do 1º turno e aplicar a complementação.
3. **Exame Preliminar Automatizado via Ferramenta Cadastral**: No 1º passo de chamada ao modelo (`gpt-5.6-luna`, `reasoning_effort="none"`), o agente invoca `consultar_servidor(matricula)` — que aplica minimização de dados e jamais retorna CPF ou e-mail — e verifica a titularidade cadastral e a presença de `data_retorno`. Havendo divergência ou ausência de dado obrigatório, encerra as consultas e emite `Instrucao` com `recomendacao="diligencia"` no 2º passo (sem análise de mérito, conforme art. 9º).
4. **Execução das Ferramentas Determinísticas de Mérito**: Quando cadastro e completude estão atendidos, o agente invoca as demais ferramentas Python onde **todas as contas saem prontas do código**:
   - `consultar_historico_diarias(matricula, data_partida, data_retorno)`: calcula o prazo de 5 dias úteis das prestações pendentes contra `2026-10-09` e soma as diárias do mês frente ao limite de 10,0.
   - `calcular_diarias(grupo, destino_uf, data_pedido, data_partida, data_retorno)`: calcula pernoites, meia diária, valor pelo Anexo I e antecedência em dias corridos.
   - `consultar_saldo_diarias(unidade, valor)`: compara o saldo da dotação da unidade com o valor calculado.
5. **Saída Estruturada (`output_schema=Instrucao`)**: No 5º passo, o modelo consolida o resultado das ferramentas, avalia a justificativa quanto à urgência legítima (art. 5º, §§ 1º e 2º) e eventuais tentativas de injeção de prompt, e devolve um objeto Pydantic `Instrucao` validado, acompanhado da minuta do despacho.
6. **Barreira Determinística de Código (`verificar_barreira`)**: Antes de exibir qualquer dado na interface, o código Python verifica `resposta.status == RunStatus.completed` e audita os argumentos reais de todas as ferramentas chamadas (`resposta.tools`) contra o pedido/complementação em mãos. Se qualquer matrícula, data, grupo, unidade ou valor não vier estritamente do pedido/complementação e das ferramentas, a instrução é descartada e o pedido é desviado para análise manual com mensagem padrão.
7. **Conferência Humana e Decisão do Ordenador**: No formulário Streamlit, o servidor conferente visualiza as verificações fundamentadas, alertas e consultas, edita a minuta do despacho e **registra obrigatoriamente sua decisão ao lado da sugestão do agente** (com justificativa quando divergirem), encaminhando o processo ao ordenador de despesa.

---

## 3. Especificação pelo Quadro PEAS

| Dimensão | Especificação Técnica no Desafio 01 |
| :--- | :--- |
| **P — Performance**<br>*(Medida de Desempenho)* | Verificável objetivamente contra `gabarito.json` (Etapa 6):<br>1. **Exatidão da recomendação** (`apto_para_autorizacao`, `diligencia`, `nao_recomendado`) nos 12 pedidos e 2 complementações (meta: 14/14).<br>2. **Exatidão aritmética** em `quantidade_diarias` e `valor_total` (`null` na diligência; valores exatos nos demais casos).<br>3. **Exatidão normativa** nos critérios não atendidos (`criterios_nao_atendidos`) e em `exige_autorizacao_superior` (art. 5º, § 2º).<br>4. **Segurança e Ancoragem**: 0% de instruções fundamentadas em dados inventados chegando ao conferente; 100% de mascaramento de CPF/conta bancária antes do modelo e do banco; 100% de resistência a prompt injection (`DIA-2026-0107`).<br>5. **Eficiência**: consumo de tokens dentro do orçamento estimado (< 3% de desvio), tempo de resposta e custo por instrução. |
| **E — Environment**<br>*(Ambiente)* | - **Acervo normativo e administrativo do órgão (`dados/`)**: `normas.md` (IN SEMA nº 07/2026), `servidores.csv` (40 servidores), `historico_diarias.csv` (21 registros), `tabela_diarias.json` (data de análise `2026-10-09`, regras e Anexo I), `unidades.json` (6 unidades e saldos), `pedidos.json` (12 pedidos) e `complementacoes.json` (2 respostas de diligência).<br>- **Propriedades**: Parcialmente observável (o agente só enxerga o cadastro, histórico e saldo quando aciona as ferramentas), determinístico nas fontes de dados e cálculos, sequencial/multi-turno por sessão de pedido (`SqliteDb`), estático durante a execução de um turno e discreto. |
| **A — Actuators**<br>*(Atuadores)* | 1. Invocação das 4 ferramentas Python (`consultar_servidor`, `consultar_historico_diarias`, `calcular_diarias`, `consultar_saldo_diarias`) com argumentos estruturados.<br>2. Emissão do objeto estruturado `Instrucao` (`verificacoes`, `recomendacao`, `quantidade_diarias`, `valor_total`, `exige_autorizacao_superior`, `pendencias`, `alertas`, `minuta_despacho`).<br>3. Persistência e remoção de sessões, execuções e memórias no banco de trabalho `SqliteDb`.<br>*(Restrição: o agente não possui atuador para deferir/indeferir despesa nem alterar os arquivos originais do órgão).* |
| **S — Sensors**<br>*(Sensores)* | 1. Dados do pedido protocolado formatados na entrada (após filtragem pelo `PIIDetectionGuardrail`).<br>2. Texto de complementação enviado pelo servidor solicitante na mesma sessão (`session_id`).<br>3. Retornos textuais estruturados das 4 ferramentas Python.<br>4. Histórico de mensagens e execuções anteriores da sessão recuperado do `SqliteDb` (`add_history_to_context=True`). |

---

## 4. Aritmética dos Passos e Confiabilidade Composta

Considerando cada chamada ao modelo de linguagem como **1 passo** ($n$):
- Em um pedido que passa pelo exame completo de mérito com chamadas paralelas desativadas (`parallel_tool_calls=False`), o agente executa **5 passos**:
  - **Passo 1 (Chamada 1)**: Lê instrução de sistema, esquemas das ferramentas, esquema de saída e pedido; decide chamar `consultar_servidor`.
  - **Passo 2 (Chamada 2)**: Recebe o cadastro funcional; decide chamar `consultar_historico_diarias`.
  - **Passo 3 (Chamada 3)**: Recebe a situação das prestações de contas e limite mensal; decide chamar `calcular_diarias`.
  - **Passo 4 (Chamada 4)**: Recebe quantidade, valor total e antecedência; decide chamar `consultar_saldo_diarias`.
  - **Passo 5 (Chamada 5)**: Recebe a comparação do saldo da unidade e preenche o esquema final `Instrucao`.
- Em um pedido devolvido preliminarmente em **diligência** (art. 9º, como nos 1ºs turnos de `DIA-2026-0111` e `DIA-2026-0112`), o agente executa **2 passos** (Passo 1: `consultar_servidor`; Passo 2: emissão da `Instrucao` de diligência sem análise de mérito).

Aplicando a fórmula de **confiabilidade composta** da Aula 01, $R(n) = p^n$, onde $p$ é a confiabilidade por passo:

| Número de Passos ($n$) | Etapa correspondente no fluxo | Confiabilidade com $p = 95\%$ ($0{,}95^n$) | Confiabilidade com $p = 99\%$ ($0{,}99^n$) |
| :---: | :--- | :---: | :---: |
| **1** | 1ª chamada (`consultar_servidor`) | 95,00% | 99,00% |
| **2** | Saída em diligência (Art. 9º) ou 2ª ferramenta | 90,25% | 98,01% |
| **3** | 3ª chamada (`calcular_diarias`) | 85,74% | 97,03% |
| **4** | 4ª chamada (`consultar_saldo_diarias`) | 81,45% | 96,06% |
| **5** | **Fluxo completo de mérito (4 ferramentas + saída `Instrucao`)** | **77,38%** | **95,10%** |
| **6** | Fluxo com recuperação de turno / memória adicional | 73,51% | 94,15% |
| **8** | Teto configurado em `tool_call_limit=8` | 66,34% | 92,27% |
| **10** | Processo manual de 10 passos se feito puro pelo modelo | 59,87% | 90,44% |

**Conclusão arquitetural da confiabilidade composta**:
- Para $n = 5$ passos, uma confiabilidade de $95\%$ por passo resulta em apenas **$77{,}38\%$** de sucesso ponta a ponta ($22{,}62\%$ de falha). Mesmo com $99\%$ por passo, a confiabilidade composta cai para **$95{,}10\%$** ($\approx 5\%$ de erro acumulado).
- É por essa razão matemática que:
  1. **Toda a aritmética fica no código Python das 4 ferramentas** (elevando a confiabilidade dos cálculos de pernoites, dias úteis, valores, limite mensal e saldo para 100% determinístico).
  2. **O teto de chamadas é fixado em `tool_call_limit=8`**, impedindo laços descontrolados na cauda de execução.
  3. **A barreira de verificação fica no código (`barreira.py`)**, validando determinísticamente os argumentos e cálculos antes que a saída chegue ao formulário.

---

## 5. Estimativa de Tokens, Custo por Passos e Volume Mensal

### 5.1. Anatomia da Entrada por Passo (5 Passos)

A entrada da **1ª chamada** ($E_1$) reúne quatro componentes fixos enviados ao provedor:
1. Instrução de sistema (`INSTRUCAO_SISTEMA` com as regras da IN SEMA nº 07/2026 e ordem das consultas).
2. Esquemas JSON das 4 ferramentas (`consultar_servidor`, `consultar_historico_diarias`, `calcular_diarias`, `consultar_saldo_diarias`) gerados a partir de suas assinaturas e docstrings.
3. Esquema JSON de saída estruturada (`output_schema=Instrucao` e `Verificacao`).
4. Texto formatado do pedido protocolado.

A cada passo seguinte ($k = 2, 3, 4, 5$), o histórico da execução acumula a chamada da ferramenta anterior ($\approx 25\text{ a }50$ tokens) e o texto devolvido pela ferramenta ($\approx 65\text{ a }140$ tokens), acrescentando um incremento médio $\Delta$ por passo:

$$E_k = E_1 + (k - 1)\cdot \Delta \implies \text{Entrada Total (5 passos)} = \sum_{k=1}^{5} E_k = 5\cdot E_1 + 10\cdot \Delta$$

#### A) Conta da Execução de Referência do Enunciado ($E_1 = 2.060$, $\Delta \in [90, 150]$, média $\Delta = 120$ tokens)
- Passo 1: $2.060$ tokens
- Passo 2: $2.060 + 120 = 2.180$ tokens
- Passo 3: $2.060 + 240 = 2.300$ tokens
- Passo 4: $2.060 + 360 = 2.420$ tokens
- Passo 5: $2.060 + 480 = 2.540$ tokens
- **Total estimado de entrada (referência)**: $5 \times 2.060 + 10 \times 120 = 10.300 + 1.200 = \mathbf{11.500\text{ tokens de entrada}}$.

#### B) Conta Estimada para a Nossa Implementação vs. Valor Real Medido (5 Passos)
Na nossa implementação (com a instrução de sistema completa incluindo regras detalhadas de urgência legítima, prompt injection e diligência):
- **Estimativa pré-execução**:
  - Entrada da 1ª chamada ($E_1$): **$2.357$ tokens** (Instrução de sistema $\approx 702$ tokens + Esquemas das 4 ferramentas $\approx 780$ tokens + Esquema `Instrucao` $\approx 715$ tokens + Pedido protocolado $\approx 160$ tokens).
  - Incremento médio por passo ($\Delta$): **$135$ tokens** por ferramenta consultada ($\Delta_1 \approx 90$, $\Delta_2 \approx 162$, $\Delta_3 \approx 198$, $\Delta_4 \approx 73$).
  - Entrada estimada por passo:
    - Passo 1: $2.357$ tokens
    - Passo 2: $2.357 + 135 = 2.492$ tokens
    - Passo 3: $2.357 + 270 = 2.627$ tokens
    - Passo 4: $2.357 + 405 = 2.762$ tokens
    - Passo 5: $2.357 + 540 = 2.897$ tokens
  - **Total estimado de entrada para 5 passos**: $5 \times 2.357 + 10 \times 135 = 11.785 + 1.350 = \mathbf{13.135\text{ tokens de entrada}}$ (mais $\approx 740$ tokens de saída totalizando **$13.875$ tokens totais** por pedido de 5 passos).
- **Confronto com o medido na Etapa 6 (Pedido regular `DIA-2026-0101`, Rodada 1, 5 passos)**:
  - Valor real medido de entrada (5 passos): **$13.100$ tokens de entrada** (Passo 1: $2.357$, Passo 2: $2.447$, Passo 3: $2.609$, Passo 4: $2.807$, Passo 5: $2.880$; saída: $738$ tokens; total: $13.838$ tokens).
  - **Desvio entre estimado ($13.135$) e medido ($13.100$)**: **$+0{,}27\%$** (muito abaixo do limite de $3\%$ exigido pela Etapa 1).

### 5.2. Volume Mensal Adotado e Projeção de Custo

Adotando um volume operacional realista para a Coordenadoria de Diárias e Passagens da SEMA-MT de **300 pedidos protocolados por mês**, com uma taxa histórica de **20% de pedidos devolvidos em diligência** (60 complementações/mês, totalizando **360 turnos de instrução/mês**):

- **240 pedidos completos no 1º turno (5 passos)**:
  - Entrada: $240 \times 13.135 = 3.152.400$ tokens
  - Saída: $240 \times 740 = 177.600$ tokens
- **60 pedidos devolvidos em diligência no 1º turno (2 passos)**:
  - Entrada: $60 \times 4.780 = 286.800$ tokens
  - Saída: $60 \times 500 = 30.000$ tokens
- **60 complementações no 2º turno com histórico da sessão (6 a 7 passos)**:
  - Entrada: $60 \times 16.200 = 972.000$ tokens
  - Saída: $60 \times 710 = 42.600$ tokens
- **Consumo Mensal Total (300 pedidos + 60 complementações)**:
  - **Tokens de entrada/mês**: $\mathbf{4.411.200\text{ tokens}}$ ($\approx 4{,}41\text{ M tokens}$)
  - **Tokens de saída/mês**: $\mathbf{250.200\text{ tokens}}$ ($\approx 0{,}25\text{ M tokens}$)
  - **Tokens totais/mês**: $\mathbf{4.661.400\text{ tokens}}$ ($\approx 4{,}66\text{ M tokens}$)
  - **Custo mensal estimado** (`gpt-5.6-luna` a $\text{US\$ }0{,}15 / 1\text{M input}$ e $\text{US\$ }0{,}60 / 1\text{M output}$):
    $$\text{Custo Mensal} = 4{,}4112 \times \text{US\$ }0{,}15 + 0{,}2502 \times \text{US\$ }0{,}60 = \text{US\$ }0{,}6617 + \text{US\$ }0{,}1501 = \mathbf{\text{US\$ }0{,}81/\text{mês}}$$

---

## 6. Grade de Reversibilidade × Tempo de Detecção (Quadrante de Autonomia)

Posicionando o processo de instrução de diárias na matriz da Aula 01 (Seção 5):

| Eixo | Classificação do Processo de Diárias (SEMA-MT) | Justificativa Prática |
| :--- | :--- | :--- |
| **Reversibilidade da Ação** | **Parcialmente Reversível com Alto Custo Administrativo** | Uma diária paga indevidamente pode, em tese, ser devolvida ao erário mediante notificação e guia de recolhimento/desconto em folha, mas exige instauração de processo administrativo e gera desgaste jurídico e operacional. |
| **Tempo de Detecção do Erro** | **Longo / Tardio (Meses depois, na Auditoria)** | Como enfatizado na especificação do problema, uma diária concedida a quem tem prestação de contas vencida (`DIA-2026-0108`) ou um pedido urgente aceito com autorização meramente verbal (`DIA-2026-0107`) raramente é percebido no dia da concessão, vindo à tona **meses depois, na auditoria interna ou no controle externo (TCE)**. |

```
                   TEMPO DE DETECÇÃO DO ERRO
                 Imediato / Curto           Tardio / Na Auditoria (Meses)
              +--------------------------+----------------------------------+
  Reversível  | Autonomia supervisionada | ★ QUADRANTE DO DESAFIO 01 ★      |
  (com custo) | com auditoria por        | O AGENTE NÃO AGE SOZINHO:        |
              | amostragem               | Agente instrui + Barreira código |
              |                          | + Conferência humana obrigatória |
              +--------------------------+----------------------------------+
  Irreversível| Conferência humana prévia| Proibida decisão autônoma;       |
              | obrigatória              | múltiplas travas e assinatura    |
              +--------------------------+----------------------------------+
```

**Decisão de Autonomia**:
O processo situa-se no quadrante **(Reversível com atrito × Detecção Tardia na Auditoria)**, no qual **o agente jamais age ou decide sozinho**:
1. O **agente** executa as consultas, organiza as evidências e redige a minuta de despacho.
2. A **barreira no código** bloqueia determinísticamente qualquer instrução com status de erro ou fundamentada em matrícula/data/valor que não conste do pedido e das ferramentas.
3. O **servidor conferente** revisa a instrução no formulário Streamlit, edita a minuta e registra sua concordância ou divergência fundamentada.
4. O **ordenador de despesa** profere a decisão administrativa final (deferimento ou indeferimento, art. 10).
