# Desafio 01 — Instrução de Pedidos de Diárias (SEMA-MT)

Sistema de apoio à instrução de pedidos de diárias da Coordenadoria de Diárias e Passagens da SEMA-MT (hipotética), regido pela **Instrução Normativa SEMA nº 07/2026**, construído com **Agno 3.0.9**, saída estruturada em **Pydantic**, filtro de dados pessoais (**`PIIDetectionGuardrail`**), barreira determinística de verificação em código, memória persistente em **`SqliteDb`** com eliminação verificável (LGPD) e formulário de conferência em **Streamlit**.

---

## 1. Pré-requisitos

- **Python 3.10 ou superior**
- Chave de API da OpenAI (`OPENAI_API_KEY`) com acesso ao modelo `gpt-5.6-luna`

---

## 2. Ambiente Virtual (`venv`) e Dependências

1. Crie e ative o ambiente virtual na raiz do projeto:

   **Windows (PowerShell):**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   **Linux / macOS:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Com o `.venv` ativo, instale as dependências a partir do `requirements.txt` (que inclui `agno==3.0.9` e `sqlalchemy[asyncio]` com o pacote `greenlet` exigido pelo `SqliteDb`):

   ```bash
   pip install -r requirements.txt
   ```

---

## 3. Configuração do `.env`

1. Copie o arquivo de exemplo `.env.example` para `.env` na raiz do projeto:
   ```bash
   cp .env.example .env
   ```
   *(No Windows PowerShell: `Copy-Item .env.example .env`)*

2. Preencha sua chave no arquivo `.env`:
   ```env
   OPENAI_API_KEY=sua_chave_openai_aqui
   OPENAI_MODEL=gpt-5.6-luna
   ```

> **Segurança:** O arquivo `.env` e os bancos locais (`*.db`) estão protegidos pelo `.gitignore` e nunca devem ser versionados nem exibidos na interface ou em relatórios.

---

## 4. Geração dos Dados (Opcional — já incluídos)

Os dados hipotéticos em `dados/` e o `gabarito.json` já estão gerados com semente fixa (`20261009`). Para regenerá-los a qualquer momento:

```bash
python gerar_dados.py
```

---

## 5. Como Executar

### 5.1. Testes Automatizados (Sem Agente e Sem Chave de API)

Executa os testes determinísticos das 4 ferramentas, filtro de PII, barreira de código, rotina de eliminação LGPD e carregamento da interface Streamlit:

```bash
python -m pytest -v
```

Para rodar apenas o script isolado das ferramentas (que grava a evidência em `resultados/teste_ferramentas_sem_agente.txt`):

```bash
python tests/testar_ferramentas.py
```

### 5.2. Aplicação Streamlit (Formulário de Conferência Humana)

Inicia a interface web para instrução de pedidos, envio de complementações em diligência, registro da conferência humana e eliminação verificável de dados:

```bash
streamlit run app.py
```

### 5.3. Medição de Memória e Eliminação LGPD (Etapa 4)

Executa os dois casos de diligência (`DIA-2026-0111` e `DIA-2026-0112`) nas três configurações de memória (`sem_memoria`, `historico_sessao`, `historico_e_memorias_usuario`) e valida a eliminação tabela por tabela no SQLite:

```bash
python scripts/medir_memoria.py
```

### 5.4. Avaliação Completa contra o Gabarito (Etapa 6)

Executa as 3 rodadas completas (12 pedidos + 2 complementações por rodada), a comparação entre chamadas paralelas ativadas e desativadas e os 4 modos de falha provocados, salvando os resultados em `resultados/`:

```bash
python -u scripts/avaliar.py
```

---

## 6. Estrutura do Projeto

```text
exemplos/
├── .env                        # Chave local da OpenAI (não versionado)
├── .env.example                # Modelo de configuração de ambiente
├── .gitignore                  # Proteção de .env, bancos *.db e caches
├── pyproject.toml              # Configuração do pytest (pythonpath = ["."])
├── app.py                      # Aplicação Streamlit (Etapa 5)
├── desenho.md                  # Desenho do processo, quadro PEAS e estimativas (Etapa 1)
├── relatorio.md                # Relatório de medições, paralelismo, falhas e conferência (Etapa 6)
├── LEIA-ME.md                  # Este guia de instalação, execução e decisões técnicas
├── gerar_dados.py              # Gerador determinístico do acervo e do gabarito
├── gabarito.json               # Respostas esperadas (uso exclusivo de scripts/avaliar.py)
├── dados/                      # Acervo hipotético (CSV, JSON e normas.md)
├── db/                         # Bancos SQLite locais de trabalho (não versionados)
├── resultados/                 # Saídas das medições, testes e evidências
├── src/                        # Pacote principal do agente
│   ├── agente.py               # Agente Agno, prompt, PIIDetectionGuardrail e SqliteDb
│   ├── barreira.py             # Barreira determinística pós-execução em código
│   ├── eliminacao.py           # Rotina de eliminação LGPD e auditoria por tabela
│   ├── ferramentas.py          # 4 ferramentas determinísticas sobre os dados do órgão
│   └── modelos.py              # Esquemas Pydantic (Verificacao e Instrucao)
├── scripts/                    # Scripts de medição e avaliação
│   ├── avaliar.py              # 3 rodadas, comparação de paralelismo e 4 falhas
│   └── medir_memoria.py        # Custo por turno nas 3 configurações de memória
└── tests/                      # Suíte de testes automatizados
    ├── testar_ferramentas.py   # Testes determinísticos das ferramentas sem LLM
    └── test_sistema.py         # Testes de PII, barreira, eliminação e Streamlit
```

---

## 7. Decisões Técnicas — Respostas às Perguntas do Enunciado

1. **Que configuração de chamadas paralelas, teto de chamadas e memória você escolheu, e com base em que número?**
   - **Chamadas paralelas desativadas (`parallel_tool_calls=False`)**: Medido em `resultados/comparacao_paralelismo.json`, com `parallel_tool_calls=False` o agente obteve **`14/14` acertos (`100%`) nas 3 rodadas independentes** (`42/42`, `0` falhas na barreira), com média de `182.563,7` tokens de entrada, `192.264,7` tokens totais, `127,28s` e `US$ 0,033204` por rodada. Na comparação com `parallel_tool_calls=True` (`resultados/rodada_paralela.json`), a execução paralela também atingiu `14/14` (`0` falhas), reduzindo o consumo para `157.667` tokens (`-17,99%`), o tempo para `108,88s` (`-14,46%`) e o custo para `US$ 0,028056` por agrupar `consultar_historico_diarias` e `calcular_diarias` no Passo 2 após o retorno do cadastro. Mantivemos `parallel_tool_calls=False` como padrão de produção pela previsibilidade estrita da cadeia causal (Aula 06, Seção 4.3: cadastro → histórico → cálculo → saldo), validada em 3 rodadas consecutivas com variação `< 0,09%` e custo adicional de apenas `US$ 0,005` por lote de 14 casos.
   - **Teto de chamadas (`tool_call_limit=8`)**: Como o fluxo completo de mérito consome exatamente 4 chamadas de ferramentas em 5 passos (tanto no 1º turno quanto na complementação) e a diligência consome 1 chamada em 2 passos, o limite de `8` oferece margem de segurança para uma eventual consulta adicional sem permitir laços descontrolados na cauda de execução.
   - **Memória (`SqliteDb` com `add_history_to_context=True`, `num_history_runs=3` e `update_memory_on_run=False`)**: Medido em `resultados/medicao_memoria.json`, sem memória o agente acertou `0/2` complementações (`22.037` tokens); com histórico da sessão acertou `2/2` com `46.904` tokens totais (`10.090` de entrada no 1º turno e `34.289` no 2º turno); ativar `update_memory_on_run=True` também acertou `2/2`, porém elevou o consumo para `54.561` tokens (`+16,32%`) sem ganho de acurácia e gerando registros adicionais na tabela `agno_memories`.

2. **Como o sistema impede que uma instrução fundamentada em dado inventado chegue ao conferente?**
   - Pela **barreira determinística em código (`src/barreira.py`)** executada após `agent.run()`. Ela confere `resposta.status == RunStatus.completed`, valida o schema Pydantic `Instrucao`, audita todas as chamadas em `resposta.tools` (exigindo que toda matrícula, nome do solicitante, data, UF, grupo de diária, unidade e valor consultado constem estritamente do pedido/complementação em mãos e do cadastro real) e verifica que toda instrução conclusiva pertence exatamente ao servidor solicitante e traz `quantidade_diarias` e `valor_total` compatíveis com o cálculo das ferramentas. Em qualquer divergência ou erro da API, o objeto `Instrucao` é descartado (`None`) e a interface exibe exclusivamente a mensagem padrão encaminhando o pedido para análise manual.

3. **Que dados do servidor o agente guarda, por quanto tempo, e como o titular os elimina?**
   - **Quais dados guarda**: O banco de trabalho `db/memoria_agente.db` (`SqliteDb`) armazena apenas o histórico das sessões nas tabelas `agno_sessions` e `agno_runs` (indexadas por `session_id=numero_pedido` e `user_id=matricula`), contendo os dados do pedido/complementação (nome, matrícula, destino, datas, justificativa), os retornos das ferramentas (já sem CPF e sem e-mail por minimização) e a instrução gerada. Qualquer CPF ou dado bancário colado na justificativa é mascarado pelo `PIIDetectionGuardrail` antes de chegar ao modelo ou ao banco. Com `update_memory_on_run=False`, não são criados perfis persistentes na tabela `agno_memories`.
   - **Por quanto tempo**: Os dados no `memoria_agente.db` são mantidos apenas como cópia temporária de trabalho durante o ciclo de instrução e eventual retorno de diligência do pedido — permanecendo retidos somente até a conclusão do fluxo ou até o titular acionar a exclusão (ou política periódica de expurgo da base de trabalho). Os arquivos e registros administrativos oficiais do processo de diárias (em `dados/` e no processo formal de despesa pública) **não são alterados** por esta rotina, pois estão sujeitos às regras de transparência e aos prazos legais de guarda das normas de prestação de contas e à LGPD.
   - **Como o titular elimina**: Pela aba **Eliminação Verificável de Dados (LGPD)** no `app.py` (ou via `src/eliminacao.py`), o titular solicita a remoção de suas sessões/execuções e memórias (`delete_user_memories`), seguida de conferência automática do banco SQLite **tabela por tabela** buscando matrícula e nome — localizando e removendo inclusive registros gravados sob matrícula trocada (como no caso `DIA-2026-0112`), comprovando `0` ocorrências restantes sem apagar dados de terceiros.
