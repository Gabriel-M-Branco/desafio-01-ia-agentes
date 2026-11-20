"""Suíte de testes automatizados (pytest) para ferramentas, filtro PII, barreira e eliminação."""

import json
from pathlib import Path

from agno.metrics import MessageMetrics, RunMetrics
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunInput, RunOutput, RunStatus

from src.agente import _extrair_metricas, criar_banco_memoria, criar_guardrail_pii, formatar_entrada_pedido
from src.barreira import MENSAGEM_PADRAO_ERRO, verificar_barreira
from src.eliminacao import conferir_banco_por_tabela, eliminar_dados_servidor
from src.modelos import Instrucao, Verificacao
from tests.testar_ferramentas import executar_testes_ferramentas

PASTA_BASE = Path(__file__).resolve().parent.parent


def test_ferramentas_sem_agente():
    relatorio = executar_testes_ferramentas()
    assert "TODOS OS TESTES DETERMINÍSTICOS DAS FERRAMENTAS FORAM APROVADOS COM SUCESSO!" in relatorio


def test_guardrail_pii_mascara_cpf_e_conta_sem_afetar_matriculas_e_datas():
    pedidos = json.loads((PASTA_BASE / "dados" / "pedidos.json").read_text(encoding="utf-8"))
    guard = criar_guardrail_pii()

    for p in pedidos:
        entrada = formatar_entrada_pedido(p)
        ri = RunInput(input_content=entrada)
        guard.check(ri)
        mascarado = ri.input_content_string()

        # Nenhuma matrícula, data ou número de pedido pode ser mascarado
        assert p["numero"] in mascarado
        assert p["matricula"] in mascarado
        assert p["data_pedido"] in mascarado
        assert p["data_partida"] in mascarado
        if p["data_retorno"]:
            assert p["data_retorno"] in mascarado

        if p["numero"] == "DIA-2026-0104":
            assert "052.318.947-20" not in mascarado
            assert "98765-4" not in mascarado
            assert "1234-5" not in mascarado
            assert "**************" in mascarado

    # Variações comuns de pontuação e abreviação para conta/agência
    variacoes = [
        ("CPF: 052.318.947-20, conta corrente: 98765-4, agência: 1234-5.", ["052.318.947-20", "98765-4", "1234-5"]),
        ("Ag. 1234-5 C/C 98765-4 Agência 4321.", ["1234-5", "98765-4", "4321"]),
    ]
    for texto, bloqueados in variacoes:
        ri = RunInput(input_content=texto)
        guard.check(ri)
        saida = ri.input_content_string()
        for dado in bloqueados:
            assert dado not in saida, f"Dado sensível '{dado}' não foi mascarado em: {saida}"


def _criar_instrucao_valida_0101() -> Instrucao:
    return Instrucao(
        numero_pedido="DIA-2026-0101",
        matricula="204317",
        quantidade_diarias=3.5,
        valor_total=980.0,
        verificacoes=[
            Verificacao(criterio="cadastro", situacao="atende", detalhe="Ana Paula Figueiredo"),
            Verificacao(criterio="dados_completos", situacao="atende", detalhe="Completo"),
            Verificacao(criterio="antecedencia", situacao="atende", detalhe="32 dias"),
            Verificacao(criterio="prestacao_contas", situacao="atende", detalhe="Sem pendências"),
            Verificacao(criterio="limite_mensal", situacao="atende", detalhe="3.5/10.0"),
            Verificacao(criterio="saldo_orcamentario", situacao="atende", detalhe="Saldo suficiente"),
        ],
        recomendacao="apto_para_autorizacao",
        exige_autorizacao_superior=False,
        pendencias=[],
        alertas=[],
        minuta_despacho="Minuta de despacho regular.",
    )


def _tools_validas_0101() -> list[ToolExecution]:
    return [
        ToolExecution(
            tool_name="consultar_servidor",
            tool_args={"matricula": "204317"},
            result="Matrícula 204317",
        ),
        ToolExecution(
            tool_name="consultar_historico_diarias",
            tool_args={"matricula": "204317", "data_partida": "2026-11-09", "data_retorno": "2026-11-12"},
            result="Regular",
        ),
        ToolExecution(
            tool_name="calcular_diarias",
            tool_args={
                "grupo": "B",
                "destino_uf": "MT",
                "data_pedido": "2026-10-08",
                "data_partida": "2026-11-09",
                "data_retorno": "2026-11-12",
            },
            result="3.5 diárias, R$ 980.00",
        ),
        ToolExecution(
            tool_name="consultar_saldo_diarias",
            tool_args={"unidade": "CFF", "valor": 980.0},
            result="Saldo suficiente",
        ),
    ]


def test_barreira_aprova_execucao_ancorada_e_bloqueia_adulteracoes():
    pedidos = {
        p["numero"]: p
        for p in json.loads((PASTA_BASE / "dados" / "pedidos.json").read_text(encoding="utf-8"))
    }
    p_0101 = pedidos["DIA-2026-0101"]

    # 1. Caso válido ancorado
    resp_ok = RunOutput(
        status=RunStatus.completed,
        content=_criar_instrucao_valida_0101(),
        tools=_tools_validas_0101(),
    )
    res_ok = verificar_barreira(resp_ok, p_0101)
    assert res_ok.aprovado is True
    assert res_ok.instrucao is not None

    # 2. Caso com erro de status da API
    resp_err = RunOutput(
        status=RunStatus.error,
        content=_criar_instrucao_valida_0101(),
        tools=_tools_validas_0101(),
    )
    res_err = verificar_barreira(resp_err, p_0101)
    assert res_err.aprovado is False
    assert res_err.instrucao is None
    assert res_err.mensagem_usuario == MENSAGEM_PADRAO_ERRO

    # 3. Caso com matrícula inventada na ferramenta
    tools_mat_errada = _tools_validas_0101()
    tools_mat_errada[0] = ToolExecution(
        tool_name="consultar_servidor",
        tool_args={"matricula": "207481"},
        result="Rafael",
    )
    resp_mat_errada = RunOutput(
        status=RunStatus.completed,
        content=_criar_instrucao_valida_0101(),
        tools=tools_mat_errada,
    )
    res_mat = verificar_barreira(resp_mat_errada, p_0101)
    assert res_mat.aprovado is False
    assert res_mat.instrucao is None
    assert any("207481" in m for m in res_mat.motivos_recusa)

    # 4. Caso com data inventada em calcular_diarias
    tools_dt_errada = _tools_validas_0101()
    tools_dt_errada[2] = ToolExecution(
        tool_name="calcular_diarias",
        tool_args={
            "grupo": "B",
            "destino_uf": "MT",
            "data_pedido": "2026-10-08",
            "data_partida": "2026-11-09",
            "data_retorno": "2026-11-25",
        },
        result="Adulterado",
    )
    resp_dt_errada = RunOutput(
        status=RunStatus.completed,
        content=_criar_instrucao_valida_0101(),
        tools=tools_dt_errada,
    )
    res_dt = verificar_barreira(resp_dt_errada, p_0101)
    assert res_dt.aprovado is False
    assert res_dt.instrucao is None
    assert any("2026-11-25" in m for m in res_dt.motivos_recusa)

    # 5. Caso de complementação de matrícula (DIA-2026-0112) em que o agente mantém a matrícula errada 207481
    p_0112 = pedidos["DIA-2026-0112"]
    inst_0112_nao_retificada = _criar_instrucao_valida_0101().model_copy(
        update={"numero_pedido": "DIA-2026-0112", "matricula": "207481", "valor_total": 980.0}
    )
    tools_0112_erradas = [
        ToolExecution(tool_name="consultar_servidor", tool_args={"matricula": "207481"}, result="Rafael"),
        ToolExecution(
            tool_name="consultar_historico_diarias",
            tool_args={"matricula": "207481", "data_partida": "2026-11-24", "data_retorno": "2026-11-27"},
            result="Regular",
        ),
        ToolExecution(
            tool_name="calcular_diarias",
            tool_args={
                "grupo": "B",
                "destino_uf": "MT",
                "data_pedido": "2026-10-09",
                "data_partida": "2026-11-24",
                "data_retorno": "2026-11-27",
            },
            result="3.5 diárias, R$ 980.00",
        ),
        ToolExecution(tool_name="consultar_saldo_diarias", tool_args={"unidade": "CFA", "valor": 980.0}, result="OK"),
    ]
    resp_0112_errada = RunOutput(
        status=RunStatus.completed,
        content=inst_0112_nao_retificada,
        tools=tools_0112_erradas,
    )
    res_0112 = verificar_barreira(
        resp_0112_errada,
        p_0112,
        texto_complementacao="Complementação ao pedido em diligência: houve erro de digitação, e a minha matrícula correta é 207418.",
    )
    assert res_0112.aprovado is False
    assert res_0112.instrucao is None
    assert any("207418" in m for m in res_0112.motivos_recusa)

    # 6. Pedido sem data_retorno (DIA-2026-0111) em que o agente inventa data_retorno=data_partida
    p_0111 = pedidos["DIA-2026-0111"]
    inst_0111_falsa = _criar_instrucao_valida_0101().model_copy(
        update={
            "numero_pedido": "DIA-2026-0111",
            "matricula": "206689",
            "quantidade_diarias": 0.5,
            "valor_total": 140.0,
        }
    )
    tools_0111_falsas = [
        ToolExecution(tool_name="consultar_servidor", tool_args={"matricula": "206689"}, result="OK"),
        ToolExecution(
            tool_name="consultar_historico_diarias",
            tool_args={"matricula": "206689", "data_partida": "2026-11-17", "data_retorno": "2026-11-17"},
            result="OK",
        ),
        ToolExecution(
            tool_name="calcular_diarias",
            tool_args={
                "grupo": "B",
                "destino_uf": "MT",
                "data_pedido": "2026-10-09",
                "data_partida": "2026-11-17",
                "data_retorno": "2026-11-17",
            },
            result="0.5 diárias, R$ 140.00",
        ),
        ToolExecution(tool_name="consultar_saldo_diarias", tool_args={"unidade": "CFF", "valor": 140.0}, result="OK"),
    ]
    res_0111_falsa = verificar_barreira(
        RunOutput(status=RunStatus.completed, content=inst_0111_falsa, tools=tools_0111_falsas),
        p_0111,
    )
    assert res_0111_falsa.aprovado is False
    assert res_0111_falsa.instrucao is None
    assert any("data_retorno" in m for m in res_0111_falsa.motivos_recusa)

    # 7. Quantidade de diárias adulterada na Instrucao (com valor_total inalterado)
    inst_qtd_errada = _criar_instrucao_valida_0101().model_copy(update={"quantidade_diarias": 99.5})
    res_qtd_err = verificar_barreira(
        RunOutput(status=RunStatus.completed, content=inst_qtd_errada, tools=_tools_validas_0101()),
        p_0101,
    )
    assert res_qtd_err.aprovado is False
    assert res_qtd_err.instrucao is None
    assert any("Quantidade de diárias" in m for m in res_qtd_err.motivos_recusa)

    # 8. Instrucao conclusiva com quantidade_diarias/valor_total nulos
    inst_nulos = _criar_instrucao_valida_0101().model_copy(
        update={"quantidade_diarias": None, "valor_total": None}
    )
    res_nulos = verificar_barreira(
        RunOutput(status=RunStatus.completed, content=inst_nulos, tools=_tools_validas_0101()),
        p_0101,
    )
    assert res_nulos.aprovado is False
    assert res_nulos.instrucao is None

    # 9. Diligência com quantidade_diarias ou valor_total preenchidos indevidamente
    inst_dil_preenchida = _criar_instrucao_valida_0101().model_copy(update={"recomendacao": "diligencia"})
    res_dil_err = verificar_barreira(
        RunOutput(status=RunStatus.completed, content=inst_dil_preenchida, tools=_tools_validas_0101()[:1]),
        p_0101,
    )
    assert res_dil_err.aprovado is False
    assert res_dil_err.instrucao is None

    # 10. Pedido DIA-2026-0112 (1º turno, sem complementação): agente tenta aprovar calculando para o servidor errado (Rafael 207481 em nome de Carla)
    res_0112_servidor_errado = verificar_barreira(resp_0112_errada, p_0112)
    assert res_0112_servidor_errado.aprovado is False
    assert res_0112_servidor_errado.instrucao is None
    assert any("servidor errado" in m for m in res_0112_servidor_errado.motivos_recusa)


def test_extrair_metricas_ignora_mensagens_de_historico():
    resp = RunOutput(
        status=RunStatus.completed,
        metrics=RunMetrics(input_tokens=6100, output_tokens=600, total_tokens=6700),
        messages=[
            Message(role="system", content="Regras"),
            Message(role="user", content="Pedido turno 1", from_history=True),
            Message(
                role="assistant",
                content="Chamada turno 1",
                from_history=True,
                metrics=MessageMetrics(input_tokens=2345, output_tokens=22),
            ),
            Message(role="user", content="Complementação turno 2", from_history=False),
            Message(
                role="assistant",
                content="Chamada 1 turno 2",
                from_history=False,
                metrics=MessageMetrics(input_tokens=3000, output_tokens=30),
            ),
            Message(
                role="assistant",
                content="Chamada 2 turno 2",
                from_history=False,
                metrics=MessageMetrics(input_tokens=3100, output_tokens=570),
            ),
        ],
    )
    in_tok, out_tok, tot_tok, _, chamadas = _extrair_metricas(resp, 1.0)
    assert in_tok == 6100 and out_tok == 600 and tot_tok == 6700
    assert len(chamadas) == 2
    assert chamadas[0]["input_tokens"] == 3000
    assert chamadas[1]["input_tokens"] == 3100


def test_rotina_eliminacao_caso_especial_dia_2026_0112(tmp_path):
    import sqlite3
    from agno.db.schemas.memory import UserMemory

    caminho_db = tmp_path / "teste_eliminacao.db"
    db = criar_banco_memoria(caminho_db)

    # Inicializa as tabelas reais do Agno 3.0.9
    db._get_table(table_type="sessions", create_table_if_not_found=True)
    db._get_table(table_type="runs", create_table_if_not_found=True)
    db.upsert_user_memory(
        UserMemory(
            memory_id="mem-carla",
            user_id="207481",
            memory="A servidora Carla Regina Souza tem matrícula 207418",
        )
    )

    with sqlite3.connect(str(caminho_db)) as conn:
        cur = conn.cursor()
        # Sessão DIA-2026-0112 gravada sob user_id='207481', mas pertencente a Carla Regina Souza (207418)
        cur.execute(
            "INSERT INTO agno_sessions (session_id, session_type, user_id, session_data, created_at) "
            "VALUES ('DIA-2026-0112', 'agent', '207481', '{\"solicitante\": \"Carla Regina Souza\"}', 1)"
        )
        cur.execute(
            "INSERT INTO agno_runs (run_id, session_id, run_index, run_type, user_id, run_data, created_at) "
            "VALUES ('run-1', 'DIA-2026-0112', 0, 'agent', '207481', '{\"content\": \"Carla Regina Souza - matrícula correta 207418\"}', 1)"
        )
        # Sessão de Ana Paula (204317) que deve permanecer intacta
        cur.execute(
            "INSERT INTO agno_sessions (session_id, session_type, user_id, session_data, created_at) "
            "VALUES ('DIA-2026-0101', 'agent', '204317', '{\"solicitante\": \"Ana Paula Figueiredo\"}', 1)"
        )
        conn.commit()

    relatorio = eliminar_dados_servidor(db, matricula="207418", nome="Carla Regina Souza")
    assert relatorio["auditoria_antes"]["total_ocorrencias"] == 3
    assert relatorio["auditoria_apos_busca_apenas_user_id"]["total_ocorrencias"] == 3
    assert relatorio["auditoria_final_tabela_por_tabela"]["total_ocorrencias"] == 0
    assert relatorio["eliminacao_completa_verificada"] is True

    # Verifica que os dados de Ana Paula (204317) foram preservados
    auditoria_ana = conferir_banco_por_tabela(caminho_db, "204317", "Ana Paula Figueiredo")
    assert auditoria_ana["total_ocorrencias"] == 1
    db.close()


def test_streamlit_app_carrega_e_simula_barreira():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PASTA_BASE / "app.py"), default_timeout=30)
    at.run()
    assert not at.exception
    # Aciona o botão de simulação de recusa da barreira de segurança
    at.button[1].click().run()
    assert not at.exception
    assert len(at.error) >= 1
    assert "análise manual" in at.error[0].value.lower()
    # Nada do conteúdo recusado (ex.: matrícula '999999' da ferramenta recusada) aparece na tela
    textos_tela = " ".join(
        [e.value for e in at.error]
        + [w.value for w in at.warning]
        + [m.value for m in at.markdown]
    )
    assert "999999" not in textos_tela

