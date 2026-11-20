"""Rotina verificável de eliminação de dados do servidor no banco do agente (Etapa 4 - LGPD).

Cumpre os requisitos da Etapa 4:
1. Apaga as sessões do titular (`delete_session`), que levam junto as execuções (`agno_runs`).
2. Lista (`get_user_memories`) e apaga (`delete_user_memories`) as memórias do usuário.
3. Confere o banco SQLite tabela por tabela, procurando a matrícula e o nome do titular.
4. Trata e documenta o caso especial do pedido DIA-2026-0112 (Carla Regina Souza, matrícula 207418,
   cujo pedido inicial foi protocolado com a matrícula trocada 207481 de Rafael Lima Antunes,
   fazendo com que a sessão ficasse gravada sob `user_id = '207481'`), eliminando os registros
   associados à titular sem apagar dados pertencentes a terceiros.
5. Atua exclusivamente no banco SQLite de memória do agente (cópia de trabalho), preservando
   intactos os arquivos originais do processo administrativo em `dados/`.
"""

from contextlib import closing
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from agno.db.sqlite import SqliteDb

from src.ferramentas import SERVIDORES

PASTA_BASE = Path(__file__).resolve().parent.parent
PASTA_RESULTADOS = PASTA_BASE / "resultados"


def conferir_banco_por_tabela(
    caminho_db: Path | str,
    matricula: str,
    nome: str,
) -> dict[str, Any]:
    """Varre todas as tabelas do banco SQLite procurando ocorrências da matrícula ou do nome do titular."""
    caminho = Path(caminho_db)
    if not caminho.exists():
        return {"tabelas": {}, "total_ocorrencias": 0, "banco_existe": False}

    termos = [t.strip().lower() for t in (matricula, nome) if t and t.strip()]
    resultado_tabelas: dict[str, dict[str, Any]] = {}
    total_ocorrencias = 0

    with closing(sqlite3.connect(str(caminho))) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        tabelas = [
            r["name"]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        ]

        for tabela in tabelas:
            linhas = cur.execute(f'SELECT * FROM "{tabela}"').fetchall()
            ocorrencias_tabela: list[dict[str, Any]] = []
            for linha in linhas:
                d = dict(linha)
                texto_linha = " ".join(str(v) for v in d.values() if v is not None).lower()
                encontrados = [termo for termo in termos if termo in texto_linha]
                if encontrados:
                    ocorrencias_tabela.append(
                        {
                            "session_id": d.get("session_id"),
                            "run_id": d.get("run_id"),
                            "memory_id": d.get("memory_id"),
                            "user_id": d.get("user_id"),
                            "termos_encontrados": encontrados,
                        }
                    )
            resultado_tabelas[tabela] = {
                "total_linhas_tabela": len(linhas),
                "ocorrencias_titular": len(ocorrencias_tabela),
                "registros": ocorrencias_tabela,
            }
            total_ocorrencias += len(ocorrencias_tabela)

    return {
        "banco_existe": True,
        "caminho_db": str(caminho),
        "matricula_procurada": matricula,
        "nome_procurado": nome,
        "tabelas": resultado_tabelas,
        "total_ocorrencias": total_ocorrencias,
    }


def _extrair_ids_memorias(memorias: Any) -> list[str]:
    """Extrai a lista de memory_id retornada por db.get_user_memories."""
    if not memorias:
        return []
    lista = memorias[0] if isinstance(memorias, tuple) else memorias
    ids: list[str] = []
    for m in lista:
        if isinstance(m, dict) and m.get("memory_id"):
            ids.append(str(m["memory_id"]))
        elif hasattr(m, "memory_id") and getattr(m, "memory_id"):
            ids.append(str(getattr(m, "memory_id")))
    return ids


def eliminar_dados_servidor(
    db: SqliteDb,
    matricula: str,
    nome: Optional[str] = None,
) -> dict[str, Any]:
    """Elimina sessões, execuções e memórias de um servidor e audita o banco tabela por tabela."""
    codigo = str(matricula).strip()
    nome_titular = (nome or SERVIDORES.get(codigo, {}).get("nome", "")).strip()
    caminho_db = Path(db.db_file) if getattr(db, "db_file", None) else PASTA_BASE / "db" / "memoria_agente.db"

    # 1. Auditoria antes da eliminação
    antes = conferir_banco_por_tabela(caminho_db, codigo, nome_titular)

    sessoes_removidas_por_user_id: list[str] = []
    memorias_removidas_por_user_id: list[str] = []
    sessoes_removidas_por_conferencia: list[dict[str, Any]] = []
    memorias_removidas_por_conferencia: list[dict[str, Any]] = []

    # 2. Eliminação padrão pelo user_id do titular
    if caminho_db.exists():
        with closing(sqlite3.connect(str(caminho_db))) as conn:
            cur = conn.cursor()
            tabelas_existentes = {
                r[0]
                for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "agno_sessions" in tabelas_existentes:
                s_ids = [
                    r[0]
                    for r in cur.execute(
                        "SELECT session_id FROM agno_sessions WHERE user_id = ?", (codigo,)
                    ).fetchall()
                ]
                for s_id in s_ids:
                    db.delete_session(session_id=s_id, user_id=codigo)
                    sessoes_removidas_por_user_id.append(s_id)

        try:
            mems = db.get_user_memories(user_id=codigo)
            mem_ids = _extrair_ids_memorias(mems)
            if mem_ids:
                db.delete_user_memories(memory_ids=mem_ids, user_id=codigo)
                memorias_removidas_por_user_id.extend(mem_ids)
        except Exception:
            pass

    # 3. Primeira conferência tabela por tabela após busca exclusiva por user_id
    apos_busca_user_id = conferir_banco_por_tabela(caminho_db, codigo, nome_titular)

    # 4. Tratamento de registros gravados sob user_id divergente (ex.: DIA-2026-0112 com matrícula trocada 207481)
    if apos_busca_user_id["total_ocorrencias"] > 0 and caminho_db.exists():
        termos = [t.lower() for t in (codigo, nome_titular) if t]
        sessoes_divergentes: dict[str, str] = {}

        for nome_tab, info_tab in apos_busca_user_id["tabelas"].items():
            for reg in info_tab["registros"]:
                s_id = reg.get("session_id")
                u_id = reg.get("user_id")
                m_id = reg.get("memory_id")
                if s_id:
                    sessoes_divergentes[str(s_id)] = str(u_id or "")
                elif m_id and nome_tab == "agno_memories":
                    # Apagar apenas a memória específica que menciona o titular (sem apagar memórias de terceiros)
                    db.delete_user_memories(memory_ids=[str(m_id)], user_id=str(u_id) if u_id else None)
                    memorias_removidas_por_conferencia.append(
                        {"memory_id": str(m_id), "user_id_gravado": str(u_id or "")}
                    )

        # Verificar que cada sessão divergente realmente pertence ao pedido do titular antes de apagar
        with closing(sqlite3.connect(str(caminho_db))) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            tabelas_existentes = {
                r[0]
                for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            nome_low = nome_titular.lower()
            for s_id, u_id in sessoes_divergentes.items():
                linha_sess = (
                    cur.execute("SELECT * FROM agno_sessions WHERE session_id = ?", (s_id,)).fetchone()
                    if "agno_sessions" in tabelas_existentes
                    else None
                )
                linhas_runs = (
                    cur.execute("SELECT * FROM agno_runs WHERE session_id = ?", (s_id,)).fetchall()
                    if "agno_runs" in tabelas_existentes
                    else []
                )
                texto_completo = " ".join(
                    [json.dumps(dict(linha_sess), ensure_ascii=False) if linha_sess else ""]
                    + [json.dumps(dict(r), ensure_ascii=False) for r in linhas_runs]
                ).lower()

                # Confirma que a matrícula real ou a identificação de solicitante pertence ao titular
                # (evita apagar sessão de terceiro que apenas mencionou o nome na justificativa)
                eh_sessao_do_titular = (
                    (bool(codigo) and codigo.lower() in texto_completo)
                    or (
                        bool(nome_low)
                        and (
                            f"nome do solicitante: {nome_low}" in texto_completo
                            or f'"solicitante": "{nome_low}"' in texto_completo
                            or f"solicitante: {nome_low}" in texto_completo
                        )
                    )
                )
                if eh_sessao_do_titular:
                    db.delete_session(session_id=s_id)
                    sessoes_removidas_por_conferencia.append(
                        {
                            "session_id": s_id,
                            "user_id_gravado": u_id,
                            "motivo": (
                                f"Sessão do titular {nome_titular} ({codigo}) estava gravada sob "
                                f"user_id='{u_id}' devido a erro de digitação de matrícula no pedido original."
                            ),
                        }
                    )

    # 5. Conferência final tabela por tabela (comprovação de zero resíduos)
    conferencia_final = conferir_banco_por_tabela(caminho_db, codigo, nome_titular)

    return {
        "matricula_titular": codigo,
        "nome_titular": nome_titular,
        "auditoria_antes": antes,
        "eliminacao_por_user_id": {
            "sessoes_removidas": sessoes_removidas_por_user_id,
            "memorias_removidas": memorias_removidas_por_user_id,
        },
        "auditoria_apos_busca_apenas_user_id": apos_busca_user_id,
        "eliminacao_complementar_por_conferencia_tabela": {
            "sessoes_removidas": sessoes_removidas_por_conferencia,
            "memorias_removidas": memorias_removidas_por_conferencia,
        },
        "auditoria_final_tabela_por_tabela": conferencia_final,
        "eliminacao_completa_verificada": conferencia_final["total_ocorrencias"] == 0,
    }
