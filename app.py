"""Formulário de conferência humana de pedidos de diárias em Streamlit (Etapa 5).

Funcionalidades:
1. Mantém um único agente Agno e SqliteDb em cache (`@st.cache_resource`), passando
   `session_id=numero_pedido` e `user_id=matricula` a cada chamada `run()`.
2. Seleção e exibição estruturada dos pedidos protocolados (`dados/pedidos.json`).
3. Progresso visível das etapas de instrução sem expor dados pessoais sensíveis.
4. Exibição da recomendação, quantidade, valor total, verificações com fundamentação,
   alertas, pendências e consultas realizadas com seus argumentos.
5. Minuta do despacho em campo editável e registro obrigatório da conferência humana
   (encaminhamento sugerido pelo agente ao lado do decidido pelo servidor, com motivo
   obrigatório quando divergirem).
6. Envio de complementação na mesma sessão quando o pedido estiver em diligência.
7. Área separada para acionar a rotina de eliminação (LGPD) e inspecionar o banco SQLite
   tabela por tabela antes e depois da exclusão.
8. Exibição exclusiva da mensagem padrão e encaminhamento para análise manual se a execução
   falhar ou se a barreira de código recusar a instrução.
"""

from datetime import datetime
import html
import json
import logging
from pathlib import Path
from typing import Any

from agno.models.response import ToolExecution
from agno.run.agent import RunOutput, RunStatus
import streamlit as st

logger = logging.getLogger(__name__)

from src.agente import (
    CAMINHO_DB_PADRAO,
    ResultadoExecucaoAgente,
    criar_agente,
    criar_banco_memoria,
    instruir_pedido,
)
from src.barreira import MENSAGEM_PADRAO_ERRO, verificar_barreira
from src.eliminacao import conferir_banco_por_tabela, eliminar_dados_servidor
from src.ferramentas import SERVIDORES

PASTA_BASE = Path(__file__).parent
PASTA_RESULTADOS = PASTA_BASE / "resultados"
ARQUIVO_CONFERENCIAS = PASTA_RESULTADOS / "registros_conferencia.json"

ROTULOS_RECOMENDACAO = {
    "apto_para_autorizacao": "Apto para autorização",
    "diligencia": "Diligência",
    "nao_recomendado": "Não recomendado",
}

BADGE_SITUACAO = {
    "atende": ("Atende", "#14532D", "#DCFCE7", "#16A34A"),
    "nao_atende": ("Não atende", "#7F1D1D", "#FEE2E2", "#DC2626"),
    "nao_verificado": ("Não verificado", "#1E293B", "#E2E8F0", "#64748B"),
}

ESTILO_RECOMENDACAO = {
    "apto_para_autorizacao": ("#14532D", "#DCFCE7", "#16A34A"),
    "diligencia": ("#78350F", "#FEF3C7", "#D97706"),
    "nao_recomendado": ("#7F1D1D", "#FEE2E2", "#DC2626"),
}

CSS_ALTO_CONTRASTE = """
<style>
/* Aproveitamento de espaço em layout wide */
.block-container {
    padding-top: 1.25rem !important;
    padding-bottom: 2rem !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    max-width: 1440px !important;
}

/* Eliminar textos semitransparentes em todo o app */
[data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p,
[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] p,
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
.stMarkdown p,
.stMarkdown li,
blockquote,
blockquote p {
    opacity: 1 !important;
}

/* Garantir contraste em campos desabilitados e textareas */
input:disabled,
textarea:disabled {
    opacity: 1 !important;
    -webkit-text-fill-color: currentColor !important;
    font-weight: 600 !important;
}

/* Melhorar separação visual de abas e métricas */
button[data-baseweb="tab"] {
    opacity: 1 !important;
    font-weight: 600 !important;
    font-size: 0.98rem !important;
    padding: 0.5rem 1rem !important;
}

[data-testid="stMetric"] {
    border: 1px solid rgba(148, 163, 184, 0.45);
    border-radius: 8px;
    padding: 0.65rem 0.85rem;
}

[data-testid="stMetricValue"] {
    font-size: 1.35rem !important;
    font-weight: 700 !important;
}

/* Banner de cabeçalho e recomendação */
.sema-header {
    border-left: 5px solid #0F766E;
    background: rgba(15, 118, 110, 0.10);
    padding: 0.75rem 1rem;
    border-radius: 6px;
    margin-bottom: 0.75rem;
}
.sema-header h1 {
    margin: 0 0 0.2rem 0;
    font-size: 1.45rem;
    line-height: 1.25;
}
.sema-header p {
    margin: 0;
    font-size: 0.92rem;
    font-weight: 500;
}

.sema-justificativa {
    border: 1px solid rgba(148, 163, 184, 0.5);
    border-left: 4px solid #3B82F6;
    background: rgba(59, 130, 246, 0.08);
    padding: 0.65rem 0.9rem;
    border-radius: 6px;
    margin: 0.4rem 0 0.8rem 0;
    font-size: 0.95rem;
    line-height: 1.45;
}

.sema-rec-banner {
    padding: 0.65rem 1rem;
    border-radius: 8px;
    font-weight: 700;
    font-size: 1.05rem;
    margin-bottom: 0.75rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

/* Tabela de verificações com quebra de linha e alto contraste */
.sema-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 0.35rem;
    margin-bottom: 0.75rem;
    font-size: 0.92rem;
}
.sema-table th {
    text-align: left;
    padding: 0.55rem 0.75rem;
    border-bottom: 2px solid rgba(148, 163, 184, 0.6);
    font-weight: 700;
}
.sema-table td {
    padding: 0.55rem 0.75rem;
    border-bottom: 1px solid rgba(148, 163, 184, 0.35);
    vertical-align: top;
    line-height: 1.4;
}
.sema-badge {
    display: inline-block;
    padding: 0.18rem 0.55rem;
    border-radius: 999px;
    font-weight: 700;
    font-size: 0.82rem;
    white-space: nowrap;
}
</style>
"""


@st.cache_resource
def obter_agente_e_banco():
    """Mantém um único agente Agno e conexão SqliteDb em cache sem misturar sessões."""
    db = criar_banco_memoria(CAMINHO_DB_PADRAO)
    agente = criar_agente(
        db=db,
        usar_memoria_sessao=True,
        atualizar_memoria_usuario=False,
        chamadas_paralelas=False,
    )
    return agente, db


def carregar_pedidos_e_complementacoes() -> tuple[dict[str, dict], dict[str, dict]]:
    pedidos = {
        p["numero"]: p
        for p in json.loads((PASTA_BASE / "dados" / "pedidos.json").read_text(encoding="utf-8"))
    }
    complementacoes = {
        c["numero"]: c
        for c in json.loads((PASTA_BASE / "dados" / "complementacoes.json").read_text(encoding="utf-8"))
    }
    return pedidos, complementacoes


def salvar_registro_conferencia(registro: dict[str, Any]) -> list[dict[str, Any]]:
    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    registros: list[dict[str, Any]] = []
    if ARQUIVO_CONFERENCIAS.exists():
        try:
            registros = json.loads(ARQUIVO_CONFERENCIAS.read_text(encoding="utf-8"))
        except Exception:
            registros = []
    registros.append(registro)
    ARQUIVO_CONFERENCIAS.write_text(
        json.dumps(registros, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return registros


def _renderizar_tabela_verificacoes(verificacoes: list[Any]) -> None:
    """Renderiza tabela HTML sem truncamento e com badges de alto contraste."""
    linhas_html: list[str] = []
    for v in verificacoes:
        rotulo, fg, bg, border = BADGE_SITUACAO.get(
            v.situacao, (v.situacao, "#1E293B", "#E2E8F0", "#64748B")
        )
        criterio_esc = html.escape(str(v.criterio))
        detalhe_esc = html.escape(str(v.detalhe))
        badge_html = (
            f'<span class="sema-badge" style="color:{fg};background:{bg};border:1px solid {border};">'
            f"{html.escape(rotulo)}</span>"
        )
        linhas_html.append(
            f"<tr>"
            f"<td style='width:18%;font-weight:700;'><code>{criterio_esc}</code></td>"
            f"<td style='width:15%;'>{badge_html}</td>"
            f"<td>{detalhe_esc}</td>"
            f"</tr>"
        )

    tabela_html = (
        '<table class="sema-table">'
        "<thead><tr>"
        "<th>Critério</th><th>Situação</th><th>Fundamentação (Retorno da Ferramenta)</th>"
        "</tr></thead>"
        f"<tbody>{''.join(linhas_html)}</tbody>"
        "</table>"
    )
    st.markdown(tabela_html, unsafe_allow_html=True)


def renderizar_resultado_instrucao(
    res: ResultadoExecucaoAgente,
    pedido: dict[str, Any],
    complementacoes: dict[str, dict],
    agente: Any,
) -> None:
    """Renderiza o resultado validado pela barreira ou a mensagem padrão de erro."""
    st.markdown("### 2. Resultado da Instrução e Barreira de Verificação")

    # 8.7 Falhas: exibir exclusivamente a mensagem padrão e encaminhar para análise manual
    # Nada do conteúdo recusado nem detalhes de valores/matrículas recusados aparece ao servidor.
    if not res.aprovado_barreira or res.instrucao is None:
        logger.warning(
            "Barreira bloqueou pedido %s (status=%s): %s",
            res.numero_pedido,
            res.barreira.status_execucao,
            "; ".join(res.barreira.motivos_recusa),
        )
        st.error(res.barreira.mensagem_usuario or MENSAGEM_PADRAO_ERRO)
        st.warning(
            "**Encaminhamento obrigatório:** Este pedido foi bloqueado pela barreira de segurança "
            "no código e encaminhado para **análise manual**. Nenhum conteúdo recusado ou parcial "
            "é exibido para evitar viés de ancoragem."
        )
        return

    inst = res.instrucao

    # Banner de recomendação de alto contraste
    fg, bg, border = ESTILO_RECOMENDACAO.get(
        inst.recomendacao, ("#1E293B", "#E2E8F0", "#64748B")
    )
    rotulo_rec = ROTULOS_RECOMENDACAO.get(inst.recomendacao, inst.recomendacao)
    sup_texto = (
        "Exige autorização expressa e escrita do Secretário Adjunto (Art. 5º, § 2º)"
        if inst.exige_autorizacao_superior
        else "Sem exigência adicional de autorização superior"
    )
    st.markdown(
        f'<div class="sema-rec-banner" style="color:{fg};background:{bg};border:1px solid {border};border-left:6px solid {border};">'
        f"<span>Recomendação: {html.escape(rotulo_rec)} (<code>{html.escape(inst.recomendacao)}</code>)</span>"
        f'<span style="font-size:0.88rem;font-weight:600;">{html.escape(sup_texto)}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    # KPIs principais compactos
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Número do Pedido", inst.numero_pedido)
    col2.metric("Matrícula", inst.matricula)
    col3.metric(
        "Quantidade de Diárias",
        f"{inst.quantidade_diarias:.1f}" if inst.quantidade_diarias is not None else "— (Diligência)",
    )
    col4.metric(
        "Valor Total",
        f"R$ {inst.valor_total:.2f}" if inst.valor_total is not None else "— (Diligência)",
    )

    # Alertas e Pendências lado a lado em cards
    col_alerta, col_pend = st.columns(2)
    with col_alerta:
        with st.container(border=True):
            st.markdown("**Alertas ao Conferente**")
            if inst.alertas:
                for alerta in inst.alertas:
                    st.warning(alerta)
            else:
                st.markdown("Nenhum alerta registrado para este pedido.")

    with col_pend:
        with st.container(border=True):
            st.markdown("**Pendências para Diligência**")
            if inst.pendencias:
                for pend in inst.pendencias:
                    st.error(pend)
            else:
                st.markdown("Nenhuma pendência cadastral ou de completude.")

    # Verificações realizadas e fundamentação (tabela completa sem truncamento)
    with st.container(border=True):
        st.markdown("**Verificações Exigidas pela Norma e Fundamentação**")
        _renderizar_tabela_verificacoes(inst.verificacoes)

    # Consultas realizadas e argumentos
    with st.expander("Consultas Realizadas pelo Agente e Argumentos Auditados pela Barreira", expanded=False):
        if res.barreira.consultas_realizadas:
            for idx, c in enumerate(res.barreira.consultas_realizadas, 1):
                st.markdown(
                    f"**{idx}. `{c['ferramenta']}`** — Argumentos: `{json.dumps(c['argumentos'], ensure_ascii=False)}`"
                )
                st.markdown(f"Retorno: `{c['resultado']}`")
        else:
            st.markdown("Nenhuma ferramenta registrada.")
        st.markdown(
            f"**Métricas da execução:** {res.input_tokens} tokens de entrada | "
            f"{res.output_tokens} tokens de saída | {res.total_tokens} tokens totais | "
            f"Tempo: {res.tempo_segundos:.2f}s | Custo estimado: US$ {res.custo_estimado_usd:.6f}"
        )

    # 8.5 Área de Diligência e Complementação na mesma sessão
    if inst.recomendacao == "diligencia":
        with st.container(border=True):
            st.markdown("### 3. Resposta de Diligência (Complementação na Mesma Sessão)")
            st.info(
                f"O pedido **{inst.numero_pedido}** aguarda complementação. Ao enviar a resposta abaixo, "
                f"ela será processada na **mesma sessão (`session_id='{inst.numero_pedido}'`)**, "
                f"recuperando o histórico do pedido no `SqliteDb`."
            )
            comp_padrao = complementacoes.get(inst.numero_pedido, {}).get("texto", "")
            texto_comp = st.text_area(
                "Texto da complementação do servidor solicitante:",
                value=comp_padrao,
                height=90,
                key=f"txt_comp_{inst.numero_pedido}",
            )
            if st.button("Enviar Complementação na Mesma Sessão", type="primary", key=f"btn_comp_{inst.numero_pedido}"):
                if not texto_comp.strip():
                    st.warning("Informe o texto da complementação antes de enviar.")
                else:
                    with st.status("Processando complementação na sessão existente...", expanded=True) as status_box:
                        st.write(f"1. Recuperando histórico da sessão `{inst.numero_pedido}` no SqliteDb...")
                        st.write("2. Aplicando filtro de dados pessoais (PIIDetectionGuardrail)...")
                        st.write("3. Executando consultas às ferramentas do órgão com o dado complementado...")
                        res_comp = instruir_pedido(
                            agente,
                            pedido,
                            texto_complementacao=texto_comp.strip(),
                            data_complementacao="2026-10-09",
                        )
                        st.write("4. Validando argumentos na barreira determinística de código...")
                        if res_comp.aprovado_barreira:
                            status_box.update(label="Complementação processada e validada!", state="complete")
                        else:
                            status_box.update(
                                label="Complementação bloqueada pela barreira — encaminhada para análise manual.",
                                state="error",
                            )
                    st.session_state[f"resultado_{pedido['numero']}"] = res_comp
                    seq_key = f"exec_seq_{pedido['numero']}"
                    st.session_state[seq_key] = st.session_state.get(seq_key, 0) + 1
                    st.rerun()

    # 8.3 e 8.4 Minuta do Despacho Editável e Conferência Humana lado a lado (otimiza tela wide)
    st.markdown("### 4. Minuta do Despacho e Registro da Conferência Humana")
    st.markdown(
        "A instrução do agente **não constitui decisão administrativa automática** (art. 10 da IN SEMA nº 07/2026). "
        "Revise a minuta e registre o encaminhamento decidido pelo servidor conferente."
    )

    exec_seq = st.session_state.get(f"exec_seq_{pedido['numero']}", 0)
    col_minuta, col_conf = st.columns([1.3, 1.0], gap="medium")

    with col_minuta:
        with st.container(border=True):
            minuta_editada = st.text_area(
                "Minuta do Despacho (Editável):",
                value=inst.minuta_despacho,
                height=245,
                key=f"minuta_{inst.numero_pedido}_{inst.recomendacao}_{exec_seq}",
            )

    with col_conf:
        with st.container(border=True):
            opcoes_enc = ["apto_para_autorizacao", "diligencia", "nao_recomendado"]
            idx_sugerido = opcoes_enc.index(inst.recomendacao) if inst.recomendacao in opcoes_enc else 0

            st.text_input(
                "Encaminhamento sugerido pelo agente:",
                value=f"{rotulo_rec} ({inst.recomendacao})",
                disabled=True,
                key=f"sug_{inst.numero_pedido}_{inst.recomendacao}_{exec_seq}",
            )
            decisao_servidor = st.selectbox(
                "Encaminhamento decidido pelo servidor conferente:",
                options=opcoes_enc,
                index=idx_sugerido,
                format_func=lambda x: f"{ROTULOS_RECOMENDACAO.get(x, x)} ({x})",
                key=f"dec_{inst.numero_pedido}_{inst.recomendacao}_{exec_seq}",
            )
            divergiu = decisao_servidor != inst.recomendacao
            justificativa_divergencia = st.text_area(
                "Justificativa (obrigatória se houver divergência):",
                placeholder="Descreva o motivo técnico ou normativo da divergência...",
                height=85,
                key=f"just_div_{inst.numero_pedido}_{inst.recomendacao}_{exec_seq}",
            )

            if st.button(
                "Registrar Conferência Humana",
                type="primary",
                width="stretch",
                key=f"btn_conf_{inst.numero_pedido}_{inst.recomendacao}_{exec_seq}",
            ):
                if divergiu and not justificativa_divergencia.strip():
                    st.error(
                        "Quando o encaminhamento decidido diverge do sugerido pelo agente, "
                        "o preenchimento da justificativa é obrigatório."
                    )
                else:
                    registro = {
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "numero_pedido": inst.numero_pedido,
                        "matricula": inst.matricula,
                        "encaminhamento_sugerido_agente": inst.recomendacao,
                        "encaminhamento_decidido_servidor": decisao_servidor,
                        "houve_divergencia": divergiu,
                        "justificativa_divergencia": justificativa_divergencia.strip() if divergiu else "",
                        "minuta_despacho_final": minuta_editada,
                    }
                    todos_registros = salvar_registro_conferencia(registro)
                    concordancias = sum(1 for r in todos_registros if not r.get("houve_divergencia"))
                    taxa_conc = (concordancias / len(todos_registros)) * 100.0
                    st.success(
                        f"Conferência registrada! (Total: {len(todos_registros)} | "
                        f"Concordância: {taxa_conc:.1f}%)"
                    )


def main() -> None:
    st.set_page_config(
        page_title="SEMA-MT | Instrução de Pedidos de Diárias",
        layout="wide",
    )
    st.markdown(CSS_ALTO_CONTRASTE, unsafe_allow_html=True)

    st.markdown(
        '<div class="sema-header">'
        "<h1>Instrução de Pedidos de Diárias — Coordenadoria de Diárias e Passagens (SEMA-MT)</h1>"
        "<p>Sistema de apoio à instrução regido pela IN SEMA nº 07/2026 (hipotética) • "
        "Agente Agno com saída estruturada, filtro PII, barreira determinística e memória SQLite.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

    agente, db = obter_agente_e_banco()
    pedidos, complementacoes = carregar_pedidos_e_complementacoes()

    aba_instrucao, aba_eliminacao = st.tabs(
        ["📋 Instrução e Conferência de Pedidos", "🗑️ Eliminação Verificável de Dados (LGPD)"]
    )

    with aba_instrucao:
        with st.container(border=True):
            st.markdown("### 1. Seleção e Dados do Pedido Protocolado")
            numeros_pedidos = list(pedidos.keys())
            numero_selecionado = st.selectbox(
                "Selecione o pedido de diárias para instrução:",
                options=numeros_pedidos,
                format_func=lambda n: f"{n} — {pedidos[n]['nome']} ({pedidos[n]['destino_municipio']}/{pedidos[n]['destino_uf']})",
            )
            pedido_atual = pedidos[numero_selecionado]

            c1, c2, c3, c4 = st.columns(4)
            c1.markdown(f"**Número:** `{pedido_atual['numero']}`  \n**Data do Pedido:** `{pedido_atual['data_pedido']}`")
            c2.markdown(f"**Solicitante:** {pedido_atual['nome']}  \n**Matrícula:** `{pedido_atual['matricula']}`")
            c3.markdown(
                f"**Destino:** {pedido_atual['destino_municipio']}/{pedido_atual['destino_uf']}  \n"
                f"**Transporte:** {pedido_atual['transporte']}"
            )
            c4.markdown(
                f"**Partida:** `{pedido_atual['data_partida']}`  \n"
                f"**Retorno:** `{pedido_atual['data_retorno'] or 'AUSENTE (null)'}`"
            )
            st.markdown(
                f'<div class="sema-justificativa"><strong>Justificativa Protocolada:</strong> '
                f"{html.escape(str(pedido_atual['justificativa']))}</div>",
                unsafe_allow_html=True,
            )

            col_btn1, col_btn2 = st.columns([1, 1])
            with col_btn1:
                acionar_instrucao = st.button(
                    "Instruir Pedido com Agente Agno",
                    type="primary",
                    width="stretch",
                )
            with col_btn2:
                simular_bloqueio = st.button(
                    "Simular Recusa da Barreira de Segurança (Teste de Falha)",
                    width="stretch",
                )

        if acionar_instrucao:
            with st.status("Executando instrução automatizada do pedido...", expanded=True) as status_box:
                st.write("1. Aplicando filtro de dados pessoais (PIIDetectionGuardrail - máscara de CPF e conta bancária)...")
                st.write(
                    f"2. Inicializando sessão `{pedido_atual['numero']}` no SqliteDb e consultando ferramentas do órgão..."
                )
                resultado = instruir_pedido(agente, pedido_atual)
                st.write("3. Verificando `resposta.status` e auditando argumentos das ferramentas na barreira de código...")
                if resultado.aprovado_barreira:
                    status_box.update(label="Instrução concluída e validada pela barreira!", state="complete")
                else:
                    status_box.update(
                        label="Instrução bloqueada pela barreira — encaminhada para análise manual.",
                        state="error",
                    )
            st.session_state[f"resultado_{numero_selecionado}"] = resultado
            seq_key = f"exec_seq_{numero_selecionado}"
            st.session_state[seq_key] = st.session_state.get(seq_key, 0) + 1

        if simular_bloqueio:
            resposta_invalida = RunOutput(
                status=RunStatus.completed,
                content=None,
                tools=[
                    ToolExecution(
                        tool_name="consultar_servidor",
                        tool_args={"matricula": "999999"},
                        result="Matrícula '999999' não localizada.",
                    )
                ],
            )
            barreira_recusada = verificar_barreira(resposta_invalida, pedido_atual)
            st.session_state[f"resultado_{numero_selecionado}"] = ResultadoExecucaoAgente(
                numero_pedido=numero_selecionado,
                user_id=pedido_atual["matricula"],
                session_id=numero_selecionado,
                aprovado_barreira=False,
                instrucao=None,
                barreira=barreira_recusada,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                tempo_segundos=0.0,
                custo_estimado_usd=0.0,
                detalhes_chamadas_modelo=[],
            )

        if f"resultado_{numero_selecionado}" in st.session_state:
            renderizar_resultado_instrucao(
                st.session_state[f"resultado_{numero_selecionado}"],
                pedido_atual,
                complementacoes,
                agente,
            )

    with aba_eliminacao:
        with st.container(border=True):
            st.markdown("### Rotina de Eliminação de Dados do Servidor no Banco do Agente (Etapa 4 — LGPD)")
            st.markdown(
                "Esta rotina atua **exclusivamente no banco SQLite de memória do agente (`db/memoria_agente.db`)**, "
                "preservando intactos os registros administrativos originais em `dados/`. "
                "Ela apaga sessões, execuções e memórias (`delete_user_memories`) e audita o banco **tabela por tabela** "
                "procurando matrícula e nome (inclusive sessões gravadas sob matrícula trocada, como no pedido `DIA-2026-0112`)."
            )

            opcoes_servidores = [
                ("206689", "Beatriz Moraes Cunha (Diligência DIA-2026-0111)"),
                ("207418", "Carla Regina Souza (Diligência DIA-2026-0112 — digitou 207481 no 1º turno)"),
            ] + [
                (mat, f"{s['nome']} ({s['unidade']})")
                for mat, s in sorted(SERVIDORES.items())
                if mat not in ("206689", "207418")
            ]

            mat_elim = st.selectbox(
                "Selecione o servidor titular para verificação ou eliminação de dados no banco do agente:",
                options=[m for m, _ in opcoes_servidores],
                format_func=lambda m: f"{m} — {dict(opcoes_servidores)[m]}",
            )
            nome_elim = SERVIDORES[mat_elim]["nome"]

            if st.session_state.get("ultimo_mat_elim") != mat_elim:
                st.session_state["ultimo_mat_elim"] = mat_elim
                st.session_state.pop("ultimo_relatorio_eliminacao", None)
                st.session_state.pop("ultima_auditoria_banco", None)

            col_aud, col_del = st.columns(2)
            with col_aud:
                if st.button("Conferir Banco Tabela por Tabela (Antes da Exclusão)", width="stretch"):
                    auditoria_atual = conferir_banco_por_tabela(CAMINHO_DB_PADRAO, mat_elim, nome_elim)
                    st.session_state["ultima_auditoria_banco"] = auditoria_atual

            with col_del:
                if st.button("Executar Rotina de Eliminação Verificável (LGPD)", type="primary", width="stretch"):
                    relatorio_elim = eliminar_dados_servidor(db, matricula=mat_elim, nome=nome_elim)
                    st.session_state["ultimo_relatorio_eliminacao"] = relatorio_elim
                    st.session_state["ultima_auditoria_banco"] = relatorio_elim["auditoria_final_tabela_por_tabela"]

        if "ultimo_relatorio_eliminacao" in st.session_state:
            rel = st.session_state["ultimo_relatorio_eliminacao"]
            if rel["eliminacao_completa_verificada"]:
                st.success(
                    f"Eliminação concluída e verificada tabela por tabela para **{rel['nome_titular']} ({rel['matricula_titular']})**: "
                    f"0 ocorrências restantes no banco SQLite!"
                )
            else:
                st.error("Atenção: Ainda foram encontradas ocorrências residuais no banco.")

            m1, m2, m3 = st.columns(3)
            m1.metric("Ocorrências Antes", rel["auditoria_antes"]["total_ocorrencias"])
            m2.metric("Após Busca por user_id", rel["auditoria_apos_busca_apenas_user_id"]["total_ocorrencias"])
            m3.metric("Ocorrências Finais", rel["auditoria_final_tabela_por_tabela"]["total_ocorrencias"])

            with st.expander("Relatório Completo da Eliminação (JSON)", expanded=False):
                st.json(rel)

        if "ultima_auditoria_banco" in st.session_state:
            aud = st.session_state["ultima_auditoria_banco"]
            with st.container(border=True):
                st.markdown("**Estado Atual das Tabelas no Banco SQLite (`db/memoria_agente.db`)**")
                if aud.get("tabelas"):
                    linhas_tab = [
                        {
                            "Tabela": nome_tab,
                            "Total de Linhas": info["total_linhas_tabela"],
                            "Ocorrências do Titular": info["ocorrencias_titular"],
                        }
                        for nome_tab, info in aud["tabelas"].items()
                    ]
                    st.dataframe(linhas_tab, width="stretch", hide_index=True)
                with st.expander("Inspeção Bruta das Tabelas (JSON)", expanded=False):
                    st.json(aud)


if __name__ == "__main__":
    main()
