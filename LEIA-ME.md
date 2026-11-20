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

## 7. As 3 Perguntas do Entregáveis - Decisões Técnicas

1. **Que configuração de chamadas paralelas, teto de chamadas e memória foi escolhida, e com base em quais números?**
   - **Chamadas paralelas desativadas (`parallel_tool_calls=False`)**: O cálculo das diárias depende do `grupo_diaria` retornado por `consultar_servidor`, e a consulta de saldo depende da `unidade` e do `valor_total` calculado por `calcular_diarias`. Desativar o paralelismo garante a ordem causal das consultas em 5 passos determinísticos.
   - **Teto de chamadas (`tool_call_limit=8`)**: Como o fluxo completo de mérito consome exatamente 4 chamadas de ferramentas (e o de diligência 1 chamada), o limite de 8 dá margem para eventual recuperação de contexto na complementação sem permitir laços descontrolados.
   - **Memória (`SqliteDb` com `add_history_to_context=True`, `num_history_runs=3` e `update_memory_on_run=False`)**: Medido em `resultados/medicao_memoria.json`, sem memória o agente acertou `0/2` complementações; com histórico da sessão acertou `2/2` com `44.352` tokens totais; ativar `update_memory_on_run=True` também acertou `2/2`, porém elevou o consumo para `51.749` tokens (`+16,7%`) sem ganho de acurácia para pedidos isolados por sessão.

2. **Como o sistema impede que uma instrução fundamentada em dado inventado chegue ao conferente?**
   - Pela **barreira determinística em código (`src/barreira.py`)** executada após `agent.run()`. Ela confere `resposta.status == RunStatus.completed`, valida o schema Pydantic `Instrucao` e audita todas as chamadas em `resposta.tools`, exigindo que toda matrícula, data, UF, grupo de diária, unidade e valor consultado constem estritamente do pedido/complementação em mãos e do cadastro real. Caso haja qualquer divergência ou falha da API, o conteúdo recusado é descartado e a interface exibe apenas a mensagem padrão encaminhando o pedido para análise manual.

3. **Que dados do servidor o agente guarda, por quanto tempo e como o titular os elimina?**
   - O banco de trabalho `memoria_agente.db` (`SqliteDb`) armazena apenas o histórico das sessões (`agno_sessions` e `agno_runs`, indexadas por `session_id=numero_pedido` e `user_id=matricula`), já com CPF e dados bancários mascarados pelo `PIIDetectionGuardrail` antes de chegar ao modelo ou ao banco. Os registros administrativos originais em `dados/` não são alterados.
   - O titular elimina seus dados pela aba **Eliminação Verificável de Dados (LGPD)** no `app.py` (ou via `src/eliminacao.py`), que remove sessões, execuções e memórias (`delete_user_memories`) e audita o banco **tabela por tabela** procurando matrícula e nome — tratando inclusive casos de matrícula trocada como o `DIA-2026-0112` sem apagar dados de terceiros.
