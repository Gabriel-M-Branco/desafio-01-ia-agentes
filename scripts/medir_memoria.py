"""Medição do custo por turno da memória nas 3 configurações e teste de eliminação LGPD (Etapa 4).

Executa:
1. As duas diligências e suas complementações (`DIA-2026-0111` e `DIA-2026-0112`) em três configurações:
   - `sem_memoria`: sem SqliteDb e sem histórico de sessão.
   - `historico_sessao`: com SqliteDb, `add_history_to_context=True` e `num_history_runs=3`.
   - `historico_e_memorias_usuario`: com SqliteDb, `add_history_to_context=True`, `num_history_runs=3`
     e `update_memory_on_run=True`.
   Registra os tokens de entrada do 1º turno, os tokens de entrada do turno da complementação,
   tokens totais, tempo, custo e se a complementação foi aplicada ao pedido certo conforme o gabarito.
2. O teste completo da rotina de eliminação (`eliminar_dados_servidor`) com as duas servidoras que
   passaram por diligência:
   - Beatriz Moraes Cunha (`206689`, pedido `DIA-2026-0111`)
   - Carla Regina Souza (`207418`, pedido `DIA-2026-0112`, gravado sob `user_id='207481'`)
   Comprova no banco, tabela por tabela, o estado antes da exclusão, após busca apenas pelo `user_id`
   da titular (evidenciando por que `DIA-2026-0112` exige a conferência por tabela) e após a exclusão
   completa (0 ocorrências residuais).
"""

import json
import sys
from pathlib import Path
from typing import Any

PASTA_BASE = Path(__file__).resolve().parent.parent
if str(PASTA_BASE) not in sys.path:
    sys.path.insert(0, str(PASTA_BASE))

from src.agente import criar_agente, criar_banco_memoria, instruir_pedido
from src.eliminacao import conferir_banco_por_tabela, eliminar_dados_servidor

PASTA_RESULTADOS = PASTA_BASE / "resultados"


def _avaliar_contra_gabarito(instrucao: Any, esperado: dict, matricula_esperada: str, numero_esperado: str) -> bool:
    if instrucao is None:
        return False
    nao_atendidos = sorted(v.criterio for v in instrucao.verificacoes if v.situacao == "nao_atende")
    return (
        instrucao.numero_pedido.strip() == numero_esperado
        and instrucao.matricula.strip() == matricula_esperada
        and instrucao.recomendacao == esperado["recomendacao"]
        and instrucao.quantidade_diarias == esperado["quantidade_diarias"]
        and instrucao.valor_total == esperado["valor_total"]
        and instrucao.exige_autorizacao_superior == esperado["exige_autorizacao_superior"]
        and nao_atendidos == sorted(esperado["criterios_nao_atendidos"])
    )


def executar_medicao_memoria_e_eliminacao() -> dict[str, Any]:
    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    pedidos = {
        p["numero"]: p
        for p in json.loads((PASTA_BASE / "dados" / "pedidos.json").read_text(encoding="utf-8"))
    }
    complementacoes = {
        c["numero"]: c
        for c in json.loads((PASTA_BASE / "dados" / "complementacoes.json").read_text(encoding="utf-8"))
    }
    gabarito = json.loads((PASTA_BASE / "gabarito.json").read_text(encoding="utf-8"))

    configuracoes = [
        {
            "id": "sem_memoria",
            "descricao": "Sem memória (add_history_to_context=False, update_memory_on_run=False)",
            "usar_memoria_sessao": False,
            "atualizar_memoria_usuario": False,
        },
        {
            "id": "historico_sessao",
            "descricao": "Com histórico da sessão (SqliteDb, add_history_to_context=True, num_history_runs=3)",
            "usar_memoria_sessao": True,
            "atualizar_memoria_usuario": False,
        },
        {
            "id": "historico_e_memorias_usuario",
            "descricao": "Histórico da sessão + memórias do usuário (update_memory_on_run=True)",
            "usar_memoria_sessao": True,
            "atualizar_memoria_usuario": True,
        },
    ]

    casos_diligencia = [
        {"numero": "DIA-2026-0111", "matricula_correta": "206689", "nome": "Beatriz Moraes Cunha"},
        {"numero": "DIA-2026-0112", "matricula_correta": "207418", "nome": "Carla Regina Souza"},
    ]

    resultados_memoria: dict[str, Any] = {}
    bancos_por_config: dict[str, Path] = {}

    for cfg in configuracoes:
        cfg_id = cfg["id"]
        caminho_db = PASTA_RESULTADOS / f"memoria_{cfg_id}.db"
        if caminho_db.exists():
            caminho_db.unlink()
        bancos_por_config[cfg_id] = caminho_db

        db = criar_banco_memoria(caminho_db) if cfg["usar_memoria_sessao"] else None
        agente = criar_agente(
            db=db,
            usar_memoria_sessao=cfg["usar_memoria_sessao"],
            atualizar_memoria_usuario=cfg["atualizar_memoria_usuario"],
            chamadas_paralelas=False,
        )

        casos_cfg: dict[str, Any] = {}
        soma_in_t1 = 0
        soma_in_t2 = 0
        soma_total_tokens = 0
        acertos_complementacao = 0

        for caso in casos_diligencia:
            num = caso["numero"]
            pedido = pedidos[num]
            comp = complementacoes[num]

            # Turno 1: Pedido original (deve resultar em diligência)
            res_t1 = instruir_pedido(agente, pedido)
            acertou_t1 = (
                res_t1.aprovado_barreira
                and _avaliar_contra_gabarito(
                    res_t1.instrucao,
                    gabarito["pedidos"][num],
                    pedido["matricula"],
                    num,
                )
            )

            # Turno 2: Complementação enviada na mesma sessão
            res_t2 = instruir_pedido(
                agente,
                pedido,
                texto_complementacao=comp["texto"],
                data_complementacao=comp["data"],
            )
            aplicada_corretamente = (
                res_t2.aprovado_barreira
                and _avaliar_contra_gabarito(
                    res_t2.instrucao,
                    gabarito["complementacoes"][num],
                    caso["matricula_correta"],
                    num,
                )
            )

            # Para update_memory_on_run=True, se a geração da memória do usuário somar tokens na resposta,
            # já está contabilizada em res_t1.input_tokens / res_t2.input_tokens.
            in_t1_primeira_chamada = (
                res_t1.detalhes_chamadas_modelo[0]["input_tokens"]
                if res_t1.detalhes_chamadas_modelo
                else res_t1.input_tokens
            )
            in_t2_primeira_chamada = (
                res_t2.detalhes_chamadas_modelo[0]["input_tokens"]
                if res_t2.detalhes_chamadas_modelo
                else res_t2.input_tokens
            )

            soma_in_t1 += res_t1.input_tokens
            soma_in_t2 += res_t2.input_tokens
            soma_total_tokens += res_t1.total_tokens + res_t2.total_tokens
            if aplicada_corretamente:
                acertos_complementacao += 1

            casos_cfg[num] = {
                "numero_pedido": num,
                "solicitante": caso["nome"],
                "matricula_protocolada": pedido["matricula"],
                "matricula_correta": caso["matricula_correta"],
                "turno_1_pedido": {
                    "input_tokens_total_turno": res_t1.input_tokens,
                    "input_tokens_primeira_chamada": in_t1_primeira_chamada,
                    "output_tokens": res_t1.output_tokens,
                    "total_tokens": res_t1.total_tokens,
                    "tempo_segundos": res_t1.tempo_segundos,
                    "custo_usd": res_t1.custo_estimado_usd,
                    "num_chamadas_modelo": len(res_t1.detalhes_chamadas_modelo),
                    "aprovado_barreira": res_t1.aprovado_barreira,
                    "recomendacao": res_t1.instrucao.recomendacao if res_t1.instrucao else None,
                    "acertou_gabarito_turno_1": acertou_t1,
                },
                "turno_2_complementacao": {
                    "input_tokens_total_turno": res_t2.input_tokens,
                    "input_tokens_primeira_chamada": in_t2_primeira_chamada,
                    "output_tokens": res_t2.output_tokens,
                    "total_tokens": res_t2.total_tokens,
                    "tempo_segundos": res_t2.tempo_segundos,
                    "custo_usd": res_t2.custo_estimado_usd,
                    "num_chamadas_modelo": len(res_t2.detalhes_chamadas_modelo),
                    "aprovado_barreira": res_t2.aprovado_barreira,
                    "motivos_recusa_barreira": res_t2.barreira.motivos_recusa,
                    "recomendacao": res_t2.instrucao.recomendacao if res_t2.instrucao else None,
                    "matricula_final": res_t2.instrucao.matricula if res_t2.instrucao else None,
                    "quantidade_diarias": res_t2.instrucao.quantidade_diarias if res_t2.instrucao else None,
                    "valor_total": res_t2.instrucao.valor_total if res_t2.instrucao else None,
                    "aplicada_ao_pedido_certo": aplicada_corretamente,
                },
            }

        resultados_memoria[cfg_id] = {
            "configuracao": cfg["descricao"],
            "soma_input_tokens_turno_1": soma_in_t1,
            "soma_input_tokens_turno_2": soma_in_t2,
            "soma_total_tokens": soma_total_tokens,
            "complementacoes_aplicadas_corretamente": f"{acertos_complementacao}/2",
            "casos": casos_cfg,
        }

    # Gravar medição de memória
    (PASTA_RESULTADOS / "medicao_memoria.json").write_text(
        json.dumps(resultados_memoria, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2. Executar e registrar rotina de eliminação no banco com histórico + memórias de usuário
    db_elim = criar_banco_memoria(bancos_por_config["historico_e_memorias_usuario"])
    evidencias_eliminacao: dict[str, Any] = {}
    for caso in casos_diligencia:
        mat = caso["matricula_correta"]
        nome = caso["nome"]
        evidencias_eliminacao[caso["numero"]] = eliminar_dados_servidor(db_elim, matricula=mat, nome=nome)

    # Conferir também que para a matrícula 207481 (Rafael Lima Antunes) na sessão DIA-2026-0112 não restou a sessão de Carla
    conferencia_cruzada_207481 = conferir_banco_por_tabela(
        bancos_por_config["historico_e_memorias_usuario"], "207418", "Carla Regina Souza"
    )
    evidencias_eliminacao["conferencia_cruzada_pos_eliminacao_carla"] = conferencia_cruzada_207481

    (PASTA_RESULTADOS / "evidencia_eliminacao.json").write_text(
        json.dumps(evidencias_eliminacao, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "medicao_memoria": resultados_memoria,
        "evidencia_eliminacao": evidencias_eliminacao,
    }


if __name__ == "__main__":
    dados = executar_medicao_memoria_e_eliminacao()
    print("Medição de memória e evidências de eliminação gravadas em resultados/.")
    for cfg_id, info in dados["medicao_memoria"].items():
        print(
            f"[{cfg_id}] Turno 1 in={info['soma_input_tokens_turno_1']} | "
            f"Turno 2 in={info['soma_input_tokens_turno_2']} | "
            f"Total={info['soma_total_tokens']} | Acertos={info['complementacoes_aplicadas_corretamente']}"
        )
    for num, ev in dados["evidencia_eliminacao"].items():
        if isinstance(ev, dict) and "eliminacao_completa_verificada" in ev:
            print(
                f"Eliminação [{num}] ({ev['nome_titular']} - {ev['matricula_titular']}): "
                f"antes={ev['auditoria_antes']['total_ocorrencias']} -> "
                f"após_user_id={ev['auditoria_apos_busca_apenas_user_id']['total_ocorrencias']} -> "
                f"final={ev['auditoria_final_tabela_por_tabela']['total_ocorrencias']} "
                f"(verificada={ev['eliminacao_completa_verificada']})"
            )
