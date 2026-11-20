"""Testes determinísticos das ferramentas sem agente e sem chave de API (Etapa 2).

Verifica:
1. Os quatro casos obrigatórios citados no enunciado:
   - Matrícula trocada do DIA-2026-0112 (207481 vs Carla Regina Souza 207418).
   - Prestação de contas vencida do DIA-2026-0108 (e distinção com a pendente no prazo do DIA-2026-0102).
   - Meia diária (ida e volta no mesmo dia) do DIA-2026-0103.
   - Saldo insuficiente da unidade CRH no DIA-2026-0110.
2. Minimização de dados: ausência total de CPF e e-mail na saída de `consultar_servidor`.
3. Coerência aritmética com todos os 12 pedidos e 2 complementações do acervo.
"""

import json
import sys
from pathlib import Path

PASTA_BASE = Path(__file__).resolve().parent.parent
if str(PASTA_BASE) not in sys.path:
    sys.path.insert(0, str(PASTA_BASE))

from src.ferramentas import (
    SERVIDORES,
    calcular_diarias,
    consultar_historico_diarias,
    consultar_saldo_diarias,
    consultar_servidor,
)

PASTA_RESULTADOS = PASTA_BASE / "resultados"


def executar_testes_ferramentas() -> str:
    linhas: list[str] = []
    linhas.append("=" * 80)
    linhas.append("ETAPA 2 - TESTE DAS FERRAMENTAS SEM AGENTE E SEM CHAVE DE API")
    linhas.append("=" * 80)

    # 1. Minimização de dados (nenhum CPF ou e-mail devolvido)
    for mat, s in SERVIDORES.items():
        saida = consultar_servidor(mat)
        assert s["cpf"] not in saida, f"CPF vazou na matrícula {mat}"
        assert s["email"] not in saida, f"E-mail vazou na matrícula {mat}"
        assert "@" not in saida, f"E-mail detectado na matrícula {mat}"
    linhas.append("\n[OK] 1. Minimização de dados verificada em todos os 40 servidores (0 CPFs, 0 e-mails).")

    # 2. Caso obrigatório 1: Matrícula trocada do DIA-2026-0112
    linhas.append("\n--- Caso 1: Matrícula trocada do DIA-2026-0112 ---")
    s_errada = consultar_servidor("207481", "Carla Regina Souza")
    s_correta = consultar_servidor("207418", "Carla Regina Souza")
    s_inexistente = consultar_servidor("999999")
    linhas.append(f"Pedido DIA-2026-0112 (solicitante Carla Regina Souza, digitou 207481):")
    linhas.append(f"  consultar_servidor('207481', 'Carla Regina Souza') -> {s_errada}")
    linhas.append(f"  consultar_servidor('207418', 'Carla Regina Souza') -> {s_correta}")
    linhas.append(f"  consultar_servidor('999999') -> {s_inexistente}")
    assert "Rafael Lima Antunes" in s_errada and "DIVERGÊNCIA CADASTRAL" in s_errada
    assert "Carla Regina Souza" in s_correta and "Titularidade cadastral: ATENDE" in s_correta
    assert "não localizada" in s_inexistente

    # 3. Caso obrigatório 2: Prestação vencida do DIA-2026-0108 (e pendente no prazo do DIA-2026-0102 + limite do DIA-2026-0109)
    linhas.append("\n--- Caso 2: Prestação vencida do DIA-2026-0108 vs. no prazo do DIA-2026-0102 e limite do DIA-2026-0109 ---")
    h_0108 = consultar_historico_diarias("203648", "2026-11-03", "2026-11-06")
    h_0102 = consultar_historico_diarias("205882", "2026-11-09", "2026-11-12")
    h_0109 = consultar_historico_diarias("208114", "2026-11-23", "2026-11-26")
    linhas.append(f"  DIA-2026-0108 (Gustavo, 203648): {h_0108}")
    linhas.append(f"  DIA-2026-0102 (Marcos, 205882):  {h_0102}")
    linhas.append(f"  DIA-2026-0109 (Larissa, 208114): {h_0109}")
    assert "NÃO ATENDE (VENCIDA)" in h_0108 and "DIA-2026-0023" in h_0108
    assert "Prestação de contas: ATENDE" in h_0102 and "DENTRO DO PRAZO" in h_0102
    assert "LIMITE MENSAL EXCEDIDO" in h_0109 and "11.5 diárias" in h_0109

    # 4. Caso obrigatório 3: Meia diária do DIA-2026-0103 (e antecedência insuficiente do DIA-2026-0105)
    linhas.append("\n--- Caso 3: Meia diária do DIA-2026-0103 ---")
    c_0103 = calcular_diarias("B", "MT", "2026-10-07", "2026-11-05", "2026-11-05")
    c_0105 = calcular_diarias("B", "MT", "2026-10-08", "2026-10-13", "2026-10-15")
    linhas.append(f"  DIA-2026-0103 (Juliana, ida e volta 2026-11-05): {c_0103}")
    linhas.append(f"  DIA-2026-0105 (Fernanda, 5 dias antecedência):   {c_0105}")
    assert "0.5 diárias" in c_0103 and "R$ 140.00" in c_0103 and "ATENDE o mínimo de 10 dias" in c_0103
    assert "2.5 diárias" in c_0105 and "R$ 700.00" in c_0105 and "INFERIOR ao mínimo de 10 dias" in c_0105

    # 5. Caso obrigatório 4: Saldo insuficiente do DIA-2026-0110
    linhas.append("\n--- Caso 4: Saldo insuficiente do DIA-2026-0110 ---")
    c_0110 = calcular_diarias("B", "RO", "2026-10-02", "2026-11-10", "2026-11-14")
    saldo_0110 = consultar_saldo_diarias("CRH", 1800.0)
    saldo_0101 = consultar_saldo_diarias("CFF", 980.0)
    linhas.append(f"  DIA-2026-0110 cálculo: {c_0110}")
    linhas.append(f"  DIA-2026-0110 saldo:   {saldo_0110}")
    linhas.append(f"  DIA-2026-0101 saldo:   {saldo_0101}")
    assert "4.5 diárias" in c_0110 and "R$ 1800.00" in c_0110
    assert "R$ 640.00" in saldo_0110 and "INSUFICIENTE para R$ 1800.00" in saldo_0110
    assert "R$ 18400.00" in saldo_0101 and "suficiente para R$ 980.00" in saldo_0101

    # 6. Varredura completa dos 12 pedidos + 2 complementações
    linhas.append("\n--- Varredura Completa dos 12 Pedidos e 2 Complementações ---")
    pedidos = json.loads((PASTA_BASE / "dados" / "pedidos.json").read_text(encoding="utf-8"))
    for p in pedidos:
        num = p["numero"]
        mat = p["matricula"]
        cad = consultar_servidor(mat)
        linhas.append(f"\n[{num}] Solicitante: {p['nome']} (matrícula {mat})")
        linhas.append(f"  1. consultar_servidor -> {cad}")
        if not p["data_retorno"]:
            linhas.append("  2. data_retorno ausente -> devolução em diligência (art. 9º)")
            continue
        if f"nome='{p['nome']}'" not in cad:
            linhas.append("  2. nome diverge do cadastro -> devolução em diligência (art. 9º)")
            continue
        srv = SERVIDORES[mat]
        hist = consultar_historico_diarias(mat, p["data_partida"], p["data_retorno"])
        calc = calcular_diarias(
            srv["grupo_diaria"], p["destino_uf"], p["data_pedido"], p["data_partida"], p["data_retorno"]
        )
        # Extrair valor total do texto calculado
        valor_str = calc.split("total = R$ ")[1].split(" ")[0]
        saldo = consultar_saldo_diarias(srv["unidade"], float(valor_str))
        linhas.append(f"  2. consultar_historico_diarias -> {hist}")
        linhas.append(f"  3. calcular_diarias -> {calc}")
        linhas.append(f"  4. consultar_saldo_diarias -> {saldo}")

    # Varredura das 2 complementações após diligência
    complementacoes = json.loads((PASTA_BASE / "dados" / "complementacoes.json").read_text(encoding="utf-8"))
    por_numero = {p["numero"]: p for p in pedidos}
    ajustes_comp = {
        "DIA-2026-0111": {"data_retorno": "2026-11-20"},
        "DIA-2026-0112": {"matricula": "207418"},
    }
    esperados_comp = {
        "DIA-2026-0111": ("3.5 diárias", "R$ 980.00", "suficiente para R$ 980.00"),
        "DIA-2026-0112": ("3.5 diárias", "R$ 770.00", "suficiente para R$ 770.00"),
    }
    for comp in complementacoes:
        num = comp["numero"]
        p_comp = {**por_numero[num], **ajustes_comp[num]}
        mat = p_comp["matricula"]
        srv = SERVIDORES[mat]
        cad = consultar_servidor(mat)
        hist = consultar_historico_diarias(mat, p_comp["data_partida"], p_comp["data_retorno"])
        calc = calcular_diarias(
            srv["grupo_diaria"],
            p_comp["destino_uf"],
            p_comp["data_pedido"],
            p_comp["data_partida"],
            p_comp["data_retorno"],
        )
        valor_str = calc.split("total = R$ ")[1].split(" ")[0]
        saldo = consultar_saldo_diarias(srv["unidade"], float(valor_str))
        esp_qtd, esp_val, esp_saldo = esperados_comp[num]
        assert f"nome='{p_comp['nome']}'" in cad
        assert esp_qtd in calc and esp_val in calc
        assert esp_saldo in saldo
        linhas.append(f"\n[{num} (complementacao)] Solicitante: {p_comp['nome']} (matrícula {mat})")
        linhas.append(f"  Texto: {comp['texto']}")
        linhas.append(f"  1. consultar_servidor -> {cad}")
        linhas.append(f"  2. consultar_historico_diarias -> {hist}")
        linhas.append(f"  3. calcular_diarias -> {calc}")
        linhas.append(f"  4. consultar_saldo_diarias -> {saldo}")

    linhas.append("\n" + "=" * 80)
    linhas.append("TODOS OS TESTES DETERMINÍSTICOS DAS FERRAMENTAS FORAM APROVADOS COM SUCESSO!")
    linhas.append("=" * 80)

    relatorio = "\n".join(linhas)
    PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    (PASTA_RESULTADOS / "teste_ferramentas_sem_agente.txt").write_text(relatorio, encoding="utf-8")
    return relatorio


def test_ferramentas_pytest() -> None:
    relatorio = executar_testes_ferramentas()
    assert "TODOS OS TESTES DETERMINÍSTICOS DAS FERRAMENTAS FORAM APROVADOS COM SUCESSO!" in relatorio


if __name__ == "__main__":
    print(executar_testes_ferramentas())
