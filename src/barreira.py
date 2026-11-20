"""Barreira determinística de verificação em código (Etapa 3 e Etapa 6).

Responsabilidades:
1. Conferir `resposta.status` (RunStatus.completed) antes de ler qualquer conteúdo da resposta.
2. Conferir se `resposta.content` é uma instância válida do schema Pydantic `Instrucao`.
3. Auditar todas as chamadas de ferramentas (`resposta.tools`) contra o pedido e a complementação
   que a aplicação tem em mãos:
   - Toda matrícula consultada deve constar do pedido ou da complementação.
   - Toda data usada no cálculo (`data_pedido`, `data_partida`, `data_retorno`) deve constar
     do pedido ou da complementação.
   - O grupo de diária, a UF de destino, a unidade de lotação e o valor consultado no saldo
     devem corresponder estritamente aos dados reais retornados pelas ferramentas.
4. Em caso de falha ou recusa, impedir que o conteúdo recusado chegue ao conferente e devolver
   a mensagem padrão de encaminhamento para análise manual.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from agno.run.agent import RunStatus

from src.ferramentas import (
    SERVIDORES,
    VALORES,
    calcular_quantidade_diarias,
    classe_destino,
)
from src.modelos import Instrucao

MENSAGEM_PADRAO_ERRO = (
    "Não foi possível concluir a instrução automática com segurança verificável. "
    "O pedido foi bloqueado pela barreira de verificação e encaminhado para análise manual."
)


@dataclass
class ResultadoBarreira:
    aprovado: bool
    instrucao: Optional[Instrucao] = None
    mensagem_usuario: str = ""
    motivos_recusa: list[str] = field(default_factory=list)
    consultas_realizadas: list[dict[str, Any]] = field(default_factory=list)
    status_execucao: str = ""


def extrair_matriculas_permitidas(pedido: dict, texto_complementacao: Optional[str] = None) -> set[str]:
    """Extrai as matrículas autorizadas a partir do pedido e de eventual complementação."""
    permitidas = set()
    if pedido.get("matricula"):
        permitidas.add(str(pedido["matricula"]).strip())
    if texto_complementacao:
        for mat in re.findall(r"\b\d{6}\b", texto_complementacao):
            permitidas.add(mat.strip())
    return permitidas


def extrair_datas_permitidas(pedido: dict, texto_complementacao: Optional[str] = None) -> dict[str, set[str]]:
    """Extrai as datas autorizadas do pedido e de eventual complementação."""
    datas_pedido = {str(pedido["data_pedido"]).strip()} if pedido.get("data_pedido") else set()
    datas_partida = {str(pedido["data_partida"]).strip()} if pedido.get("data_partida") else set()
    datas_retorno = {str(pedido["data_retorno"]).strip()} if pedido.get("data_retorno") else set()

    if texto_complementacao:
        datas_comp = {dt.strip() for dt in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", texto_complementacao)}
        if not datas_retorno:
            datas_retorno |= datas_comp
        elif not datas_partida:
            datas_partida |= datas_comp
        else:
            datas_retorno |= datas_comp
            datas_partida |= datas_comp

    todas = datas_pedido | datas_partida | datas_retorno
    return {
        "data_pedido": datas_pedido,
        "data_partida": datas_partida,
        "data_retorno": datas_retorno,
        "todas": todas,
    }


def extrair_consultas(resposta: Any) -> list[dict[str, Any]]:
    """Extrai a lista de ferramentas chamadas, seus argumentos e resultados."""
    consultas: list[dict[str, Any]] = []
    ferramentas = getattr(resposta, "tools", None) or []
    for t in ferramentas:
        consultas.append(
            {
                "ferramenta": getattr(t, "tool_name", ""),
                "argumentos": dict(getattr(t, "tool_args", None) or {}),
                "resultado": getattr(t, "result", ""),
                "erro": getattr(t, "tool_call_error", False),
            }
        )
    return consultas


def verificar_barreira(
    resposta: Any,
    pedido: dict,
    texto_complementacao: Optional[str] = None,
) -> ResultadoBarreira:
    """Executa a barreira determinística no código sobre a saída e as chamadas do agente."""
    motivos: list[str] = []

    if resposta is None:
        return ResultadoBarreira(
            aprovado=False,
            instrucao=None,
            mensagem_usuario=MENSAGEM_PADRAO_ERRO,
            motivos_recusa=["Resposta nula devolvida pela execução do agente."],
            status_execucao="NONE",
        )

    status = getattr(resposta, "status", None)
    status_str = str(status.value if hasattr(status, "value") else status)
    consultas = extrair_consultas(resposta)

    # 1. Verificação obrigatória de resposta.status (Aula 06, Seção 5.3)
    if status != RunStatus.completed and status_str.upper() != "COMPLETED":
        motivos.append(f"Status da execução inválido ou erro da API: {status_str}.")
        return ResultadoBarreira(
            aprovado=False,
            instrucao=None,
            mensagem_usuario=MENSAGEM_PADRAO_ERRO,
            motivos_recusa=motivos,
            consultas_realizadas=consultas,
            status_execucao=status_str,
        )

    conteudo = getattr(resposta, "content", None)
    if not isinstance(conteudo, Instrucao):
        motivos.append(
            f"Saída estruturada ausente ou fora do schema Instrucao (tipo recebido: {type(conteudo).__name__})."
        )
        return ResultadoBarreira(
            aprovado=False,
            instrucao=None,
            mensagem_usuario=MENSAGEM_PADRAO_ERRO,
            motivos_recusa=motivos,
            consultas_realizadas=consultas,
            status_execucao=status_str,
        )

    matriculas_validas = extrair_matriculas_permitidas(pedido, texto_complementacao)
    matriculas_comp = (
        {m.strip() for m in re.findall(r"\b\d{6}\b", texto_complementacao)}
        if texto_complementacao
        else set()
    )
    matriculas_finais_esperadas = matriculas_comp if matriculas_comp else matriculas_validas
    datas_validas = extrair_datas_permitidas(pedido, texto_complementacao)

    # 2. Exigir que ao menos o cadastro tenha sido consultado via ferramenta
    if not consultas:
        motivos.append("Nenhuma ferramenta foi consultada pelo agente (proibido instruir com dados supostos).")

    matriculas_consultadas: set[str] = set()
    quantidades_calculadas_validas: set[float] = set()
    valores_calculados_validos: set[float] = set()

    # Pré-calcular quantidades e valores esperados para as combinações válidas do pedido/complementação
    for mat in matriculas_finais_esperadas:
        srv = SERVIDORES.get(mat)
        if srv and datas_validas["data_partida"] and datas_validas["data_retorno"]:
            for dp in datas_validas["data_partida"]:
                for dr in datas_validas["data_retorno"]:
                    try:
                        qtd_esp = round(calcular_quantidade_diarias(date.fromisoformat(dp), date.fromisoformat(dr)), 1)
                        classe_esp = classe_destino(pedido["destino_uf"])
                        val_unit = float(VALORES[srv["grupo_diaria"]][classe_esp])
                        quantidades_calculadas_validas.add(qtd_esp)
                        valores_calculados_validos.add(round(qtd_esp * val_unit, 2))
                    except ValueError:
                        pass

    # 3. Verificação dos argumentos de cada ferramenta chamada contra o pedido/complementação
    for c in consultas:
        nome_tool = c["ferramenta"]
        args = c["argumentos"]

        if c["erro"]:
            motivos.append(f"Erro reportado durante execução da ferramenta '{nome_tool}'.")

        if "matricula" in args:
            mat_arg = str(args["matricula"]).strip()
            matriculas_consultadas.add(mat_arg)
            if mat_arg not in matriculas_validas:
                motivos.append(
                    f"Matrícula '{mat_arg}' consultada em '{nome_tool}' não consta do pedido "
                    f"nem da complementação (permitidas: {sorted(matriculas_validas)})."
                )
            elif nome_tool != "consultar_servidor" and mat_arg not in matriculas_finais_esperadas:
                motivos.append(
                    f"Matrícula '{mat_arg}' consultada em '{nome_tool}' não corresponde à matrícula "
                    f"retificada na complementação ({sorted(matriculas_finais_esperadas)})."
                )

        if nome_tool == "consultar_servidor" and args.get("nome_solicitante"):
            nome_arg = str(args["nome_solicitante"]).strip().lower()
            nome_ped = str(pedido.get("nome", "")).strip().lower()
            if nome_ped and nome_arg != nome_ped:
                motivos.append(
                    f"Nome do solicitante '{args['nome_solicitante']}' passado em 'consultar_servidor' "
                    f"diverge do pedido ('{pedido.get('nome')}')."
                )

        for campo_dt in ("data_pedido", "data_partida", "data_retorno"):
            if campo_dt in args:
                val_dt = str(args[campo_dt]).strip()
                if val_dt and val_dt.lower() not in ("none", "null", ""):
                    if not datas_validas[campo_dt]:
                        motivos.append(
                            f"Data '{val_dt}' passada em '{campo_dt}' de '{nome_tool}', "
                            f"mas o pedido/complementação não possui '{campo_dt}' preenchida."
                        )
                    elif val_dt not in datas_validas[campo_dt]:
                        motivos.append(
                            f"Data '{val_dt}' no argumento '{campo_dt}' de '{nome_tool}' não consta "
                            f"do pedido nem da complementação para '{campo_dt}' "
                            f"(permitidas: {sorted(datas_validas[campo_dt])})."
                        )

        if nome_tool == "calcular_diarias":
            uf_arg = str(args.get("destino_uf", "")).strip().upper()
            uf_ped = str(pedido.get("destino_uf", "")).strip().upper()
            if uf_arg != uf_ped:
                motivos.append(
                    f"UF de destino '{uf_arg}' em 'calcular_diarias' diverge do pedido ('{uf_ped}')."
                )
            grp_arg = str(args.get("grupo", "")).strip().upper()
            grupos_permitidos = {
                SERVIDORES[m]["grupo_diaria"] for m in matriculas_finais_esperadas if m in SERVIDORES
            }
            if grupos_permitidos and grp_arg not in grupos_permitidos:
                motivos.append(
                    f"Grupo '{grp_arg}' em 'calcular_diarias' não corresponde ao cadastro do servidor "
                    f"(esperado: {sorted(grupos_permitidos)})."
                )

        if nome_tool == "consultar_saldo_diarias":
            unid_arg = str(args.get("unidade", "")).strip().upper()
            unidades_permitidas = {
                SERVIDORES[m]["unidade"] for m in matriculas_finais_esperadas if m in SERVIDORES
            }
            if unidades_permitidas and unid_arg not in unidades_permitidas:
                motivos.append(
                    f"Unidade '{unid_arg}' em 'consultar_saldo_diarias' não corresponde à lotação "
                    f"do servidor no cadastro (esperado: {sorted(unidades_permitidas)})."
                )
            if "valor" in args and valores_calculados_validos:
                try:
                    val_arg = round(float(args["valor"]), 2)
                    if val_arg not in valores_calculados_validos:
                        motivos.append(
                            f"Valor R$ {val_arg:.2f} consultado em 'consultar_saldo_diarias' não "
                            f"corresponde ao valor calculado para o pedido ({sorted(valores_calculados_validos)})."
                        )
                except (TypeError, ValueError):
                    motivos.append(f"Valor inválido em 'consultar_saldo_diarias': {args.get('valor')}.")

    # 4. Verificação de ancoragem do objeto final Instrucao contra o pedido e ferramentas
    if conteudo.numero_pedido.strip() != str(pedido["numero"]).strip():
        motivos.append(
            f"Número do pedido na instrução ('{conteudo.numero_pedido}') diverge do pedido ('{pedido['numero']}')."
        )

    if conteudo.matricula.strip() not in matriculas_finais_esperadas:
        motivos.append(
            f"Matrícula na instrução ('{conteudo.matricula}') não consta do pedido/complementação "
            f"ou não corresponde à matrícula retificada ({sorted(matriculas_finais_esperadas)})."
        )

    if conteudo.recomendacao == "diligencia":
        if conteudo.quantidade_diarias is not None or conteudo.valor_total is not None:
            motivos.append(
                f"Instrução de diligência deve manter quantidade_diarias e valor_total nulos "
                f"(obtido: qtd={conteudo.quantidade_diarias}, valor={conteudo.valor_total})."
            )
    else:
        mat_final = conteudo.matricula.strip()
        srv_final = SERVIDORES.get(mat_final)
        nome_pedido = str(pedido.get("nome", "")).strip()
        if srv_final is None:
            motivos.append(
                f"Instrução conclusiva ('{conteudo.recomendacao}') emitida para matrícula "
                f"'{mat_final}' inexistente no cadastro funcional (art. 9º)."
            )
        elif nome_pedido and srv_final["nome"].strip().lower() != nome_pedido.lower():
            motivos.append(
                f"Instrução conclusiva ('{conteudo.recomendacao}') calculada para servidor errado: "
                f"matrícula '{mat_final}' pertence a '{srv_final['nome']}', mas o solicitante do pedido é "
                f"'{nome_pedido}' (art. 9º)."
            )

        nomes_chamados = {c["ferramenta"] for c in consultas}
        obrigatorias = {
            "consultar_servidor",
            "consultar_historico_diarias",
            "calcular_diarias",
            "consultar_saldo_diarias",
        }
        faltantes = obrigatorias - nomes_chamados
        if faltantes:
            motivos.append(
                f"Instrução conclusiva ('{conteudo.recomendacao}') gerada sem consultar todas as "
                f"ferramentas obrigatórias. Faltaram: {sorted(faltantes)}."
            )
        if not datas_validas["data_retorno"]:
            motivos.append(
                f"Instrução conclusiva ('{conteudo.recomendacao}') emitida para pedido sem data_retorno "
                f"no pedido nem na complementação."
            )
        if conteudo.quantidade_diarias is None:
            motivos.append(
                f"Instrução conclusiva ('{conteudo.recomendacao}') sem quantidade_diarias preenchida."
            )
        elif quantidades_calculadas_validas and round(float(conteudo.quantidade_diarias), 1) not in quantidades_calculadas_validas:
            motivos.append(
                f"Quantidade de diárias na instrução ({conteudo.quantidade_diarias}) diverge do cálculo "
                f"das ferramentas ({sorted(quantidades_calculadas_validas)})."
            )
        if conteudo.valor_total is None:
            motivos.append(
                f"Instrução conclusiva ('{conteudo.recomendacao}') sem valor_total preenchido."
            )
        elif valores_calculados_validos and round(float(conteudo.valor_total), 2) not in valores_calculados_validos:
            motivos.append(
                f"Valor total na instrução (R$ {conteudo.valor_total}) diverge do cálculo das "
                f"ferramentas ({sorted(valores_calculados_validos)})."
            )

    if motivos:
        return ResultadoBarreira(
            aprovado=False,
            instrucao=None,
            mensagem_usuario=MENSAGEM_PADRAO_ERRO,
            motivos_recusa=motivos,
            consultas_realizadas=consultas,
            status_execucao=status_str,
        )

    return ResultadoBarreira(
        aprovado=True,
        instrucao=conteudo,
        mensagem_usuario="Instrução validada pela barreira de código.",
        motivos_recusa=[],
        consultas_realizadas=consultas,
        status_execucao=status_str,
    )
