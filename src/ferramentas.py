"""Ferramentas determinísticas sobre os dados do órgão para instrução de diárias (Etapa 2).

Princípios de projeto:
1. Minimização de dados: CPF e e-mail do cadastro funcional nunca são devolvidos ao modelo.
2. Contas no código: toda a aritmética (pernoites, meia diária, valor total, antecedência,
   prazo em dias úteis da prestação de contas, soma mensal e comparação com saldo da unidade)
   é executada em Python puro, usando a data de referência fixa de `tabela_diarias.json`.
"""

import csv
import json
from datetime import date, timedelta
from pathlib import Path

PASTA_BASE = Path(__file__).resolve().parent.parent
PASTA_DADOS = PASTA_BASE / "dados"


def _carregar_acervo() -> tuple[dict[str, dict], list[dict], dict, dict[str, dict]]:
    with open(PASTA_DADOS / "servidores.csv", encoding="utf-8") as f:
        servidores = {linha["matricula"].strip(): linha for linha in csv.DictReader(f)}
    with open(PASTA_DADOS / "historico_diarias.csv", encoding="utf-8") as f:
        historico = list(csv.DictReader(f))
    tabela = json.loads((PASTA_DADOS / "tabela_diarias.json").read_text(encoding="utf-8"))
    unidades = json.loads((PASTA_DADOS / "unidades.json").read_text(encoding="utf-8"))
    return servidores, historico, tabela, unidades


SERVIDORES, HISTORICO, TABELA_DIARIAS, UNIDADES = _carregar_acervo()
DATA_DA_ANALISE = date.fromisoformat(TABELA_DIARIAS["data_da_analise"])
ANTECEDENCIA_MINIMA = int(TABELA_DIARIAS["antecedencia_minima_dias"])
LIMITE_MENSAL = float(TABELA_DIARIAS["limite_mensal_diarias"])
PRAZO_PRESTACAO = int(TABELA_DIARIAS["prazo_prestacao_dias_uteis"])
VALORES = TABELA_DIARIAS["valores"]


def somar_dias_uteis(inicio: date, dias: int) -> date:
    """Soma dias úteis (segunda a sexta-feira) a partir de uma data."""
    atual = inicio
    restantes = dias
    while restantes > 0:
        atual += timedelta(days=1)
        if atual.weekday() < 5:
            restantes -= 1
    return atual


def classe_destino(uf: str) -> str:
    """Classifica a UF de destino conforme o Anexo I da IN SEMA nº 07/2026."""
    sigla = uf.strip().upper()
    if sigla == "MT":
        return "interior_mt"
    if sigla == "DF":
        return "distrito_federal"
    return "outra_uf"


def calcular_quantidade_diarias(partida: date, retorno: date) -> float:
    """Uma diária por pernoite e meia no dia do retorno; sem pernoite, meia diária (art. 4º)."""
    pernoites = (retorno - partida).days
    return 0.5 if pernoites == 0 else pernoites + 0.5


def consultar_servidor(matricula: str) -> str:
    """Consulta o cadastro funcional de um servidor pela matrícula.

    Use como primeira consulta ao instruir um pedido ou complementação para conferir
    se a matrícula existe e se o nome no cadastro confere com o nome do solicitante no pedido.
    `matricula` é o código numérico de 6 dígitos informado no pedido ou complementação, como '204317'.
    Devolve nome, cargo, grupo de diária (A, B ou C), sigla da unidade de lotação e município-sede,
    omitindo CPF e e-mail por minimização de dados.
    """
    codigo = str(matricula).strip()
    servidor = SERVIDORES.get(codigo)
    if servidor is None:
        return f"Matrícula '{codigo}' não localizada no cadastro funcional (art. 9º)."
    return (
        f"Matrícula {servidor['matricula']}: nome='{servidor['nome']}', "
        f"cargo='{servidor['cargo']}', grupo_diaria='{servidor['grupo_diaria']}', "
        f"unidade='{servidor['unidade']}', municipio_sede='{servidor['municipio_sede']}' "
        f"(art. 3º e art. 9º)."
    )


def consultar_historico_diarias(
    matricula: str,
    data_partida: str,
    data_retorno: str = "",
) -> str:
    """Consulta o histórico de prestações de contas e o limite mensal de diárias do servidor.

    Use após validar o cadastro e a completude dos dados do pedido.
    `matricula` é o código de 6 dígitos do servidor, como '205882';
    `data_partida` é a data de início da viagem no formato ISO 'AAAA-MM-DD', como '2026-11-09';
    `data_retorno` é a data de término da viagem no formato ISO 'AAAA-MM-DD', como '2026-11-12'.
    Devolve a situação das prestações de contas em relação ao prazo de 5 dias úteis na data da
    análise (art. 7º) e a soma das diárias no mês civil da partida frente ao limite de 10 diárias (art. 6º).
    """
    codigo = str(matricula).strip()
    if codigo not in SERVIDORES:
        return f"Matrícula '{codigo}' não localizada no cadastro funcional."

    try:
        partida = date.fromisoformat(str(data_partida).strip())
    except ValueError:
        return f"Data de partida inválida: '{data_partida}'. Use o formato AAAA-MM-DD."

    qtd_pedida = 0.0
    if data_retorno and str(data_retorno).strip() and str(data_retorno).strip().lower() != "none":
        try:
            retorno = date.fromisoformat(str(data_retorno).strip())
            if retorno < partida:
                return f"Data de retorno '{data_retorno}' anterior à partida '{data_partida}'."
            qtd_pedida = calcular_quantidade_diarias(partida, retorno)
        except ValueError:
            return f"Data de retorno inválida: '{data_retorno}'. Use o formato AAAA-MM-DD."

    registros = [h for h in HISTORICO if h["matricula"] == codigo]

    # 1. Verificação de prestação de contas (art. 7º)
    vencidas = []
    pendentes_no_prazo = []
    for h in registros:
        if h["prestacao_contas"] == "pendente":
            ret_hist = date.fromisoformat(h["data_retorno"])
            prazo_final = somar_dias_uteis(ret_hist, PRAZO_PRESTACAO)
            if prazo_final < DATA_DA_ANALISE:
                vencidas.append(
                    f"pedido {h['pedido']} ({h['destino']}, retorno {h['data_retorno']}, "
                    f"prazo de {PRAZO_PRESTACAO} dias úteis venceu em {prazo_final.isoformat()})"
                )
            else:
                pendentes_no_prazo.append(
                    f"pedido {h['pedido']} ({h['destino']}, retorno {h['data_retorno']}, "
                    f"pendente DENTRO DO PRAZO até {prazo_final.isoformat()})"
                )

    if vencidas:
        msg_prestacao = (
            f"Prestação de contas: NÃO ATENDE (VENCIDA) - {'; '.join(vencidas)} "
            f"(data da análise {DATA_DA_ANALISE.isoformat()}, art. 7º)."
        )
    elif pendentes_no_prazo:
        msg_prestacao = (
            f"Prestação de contas: ATENDE - há prestação {'; '.join(pendentes_no_prazo)}, "
            f"ainda não vencida na data da análise {DATA_DA_ANALISE.isoformat()} (art. 7º)."
        )
    else:
        msg_prestacao = (
            f"Prestação de contas: ATENDE - sem prestações pendentes ou vencidas "
            f"na data da análise {DATA_DA_ANALISE.isoformat()} (art. 7º)."
        )

    # 2. Verificação de limite mensal no mês civil da partida (art. 6º)
    mes = partida.isoformat()[:7]
    diarias_mes = [
        h for h in registros if h["data_partida"][:7] == mes
    ]
    usadas = round(sum(float(h["quantidade"]) for h in diarias_mes), 1)
    detalhe_mes = (
        ", ".join(f"{h['pedido']} ({h['quantidade']} diárias)" for h in diarias_mes)
        if diarias_mes
        else "nenhuma diária anterior no mês"
    )

    if qtd_pedida > 0:
        total_mes = round(usadas + qtd_pedida, 1)
        situacao_limite = (
            "ATENDE" if total_mes <= LIMITE_MENSAL else "NÃO ATENDE (LIMITE MENSAL EXCEDIDO)"
        )
        msg_limite = (
            f"Limite mensal ({mes}): {situacao_limite} - {usadas:.1f} diárias já concedidas "
            f"({detalhe_mes}) + {qtd_pedida:.1f} pedidas = {total_mes:.1f} diárias "
            f"(limite máximo de {LIMITE_MENSAL:.1f} diárias/mês, art. 6º)."
        )
    else:
        saldo_mes = round(LIMITE_MENSAL - usadas, 1)
        msg_limite = (
            f"Limite mensal ({mes}): {usadas:.1f} diárias já concedidas ({detalhe_mes}); "
            f"restam {saldo_mes:.1f} diárias até o limite de {LIMITE_MENSAL:.1f} (art. 6º)."
        )

    return f"{msg_prestacao} {msg_limite}"


def calcular_diarias(
    grupo: str,
    destino_uf: str,
    data_pedido: str,
    data_partida: str,
    data_retorno: str,
) -> str:
    """Calcula a quantidade de diárias, o valor total em reais e a antecedência do pedido.

    Use depois de consultar o cadastro funcional para obter o `grupo` (A, B ou C) e somente
    quando o pedido possuir `data_retorno` preenchida e cadastro válido.
    `grupo` é a letra do grupo da diária devolvida pelo cadastro ('A', 'B' ou 'C');
    `destino_uf` é a sigla da UF de destino do pedido, como 'MT', 'DF' ou 'RO';
    `data_pedido`, `data_partida` e `data_retorno` são datas no formato ISO 'AAAA-MM-DD'.
    Devolve a quantidade de diárias (art. 4º), o valor unitário e total (art. 3º, Anexo I) e
    a antecedência em dias corridos comparada ao mínimo de 10 dias (art. 5º).
    """
    grp = str(grupo).strip().upper()
    if grp not in VALORES:
        return f"Grupo de diária '{grupo}' inválido. Grupos válidos: A, B, C."

    if not data_retorno or str(data_retorno).strip().lower() in ("", "none", "null"):
        return "Data de retorno ausente; pedido incompleto deve retornar em diligência sem cálculo (art. 9º)."

    try:
        dt_pedido = date.fromisoformat(str(data_pedido).strip())
        dt_partida = date.fromisoformat(str(data_partida).strip())
        dt_retorno = date.fromisoformat(str(data_retorno).strip())
    except ValueError as exc:
        return f"Erro no formato das datas (use AAAA-MM-DD): {exc}"

    if dt_retorno < dt_partida:
        return f"Data de retorno ({data_retorno}) anterior à data de partida ({data_partida})."

    pernoites = (dt_retorno - dt_partida).days
    qtd = calcular_quantidade_diarias(dt_partida, dt_retorno)
    classe = classe_destino(destino_uf)
    valor_unitario = float(VALORES[grp][classe])
    valor_total = round(qtd * valor_unitario, 2)

    antecedencia = (dt_partida - dt_pedido).days
    if antecedencia >= ANTECEDENCIA_MINIMA:
        msg_ant = (
            f"Antecedência: {antecedencia} dias corridos entre o pedido ({data_pedido}) "
            f"e a partida ({data_partida}) - ATENDE o mínimo de {ANTECEDENCIA_MINIMA} dias (art. 5º)."
        )
    else:
        msg_ant = (
            f"Antecedência: {antecedencia} dias corridos entre o pedido ({data_pedido}) "
            f"e a partida ({data_partida}) - INFERIOR ao mínimo de {ANTECEDENCIA_MINIMA} dias (art. 5º). "
            f"Só atende se a justificativa caracterizar urgência legítima imprevisível (art. 5º, § 1º), "
            f"hipótese que exige autorização expressa e escrita do Secretário Adjunto (art. 5º, § 2º, "
            f"exige_autorizacao_superior=True)."
        )

    regra_qtd = (
        "deslocamento sem pernoite = 0.5 diária"
        if pernoites == 0
        else f"{pernoites} pernoite(s) + 0.5 no retorno = {qtd:.1f} diárias"
    )
    return (
        f"Quantidade: {qtd:.1f} diárias ({regra_qtd}, art. 4º). "
        f"Valor: grupo {grp}, destino {destino_uf.strip().upper()} ({classe}), "
        f"R$ {valor_unitario:.2f}/diária, total = R$ {valor_total:.2f} (art. 3º, Anexo I). "
        f"{msg_ant}"
    )


def consultar_saldo_diarias(unidade: str, valor: float) -> str:
    """Consulta o saldo da dotação de diárias de uma unidade e o compara com o valor pedido.

    Use depois de calcular o valor total das diárias. `unidade` é a sigla da
    unidade de lotação devolvida pelo cadastro, como CFF ou GAB; `valor` é o
    total em reais, com ponto decimal, como 980.0. Devolve o saldo disponível e
    a indicação de saldo suficiente ou insuficiente para o pedido.
    """
    sigla = unidade.strip().upper()
    if sigla not in UNIDADES:
        return f"Unidade '{unidade}' não localizada. Siglas válidas: {', '.join(UNIDADES)}."
    saldo = UNIDADES[sigla]["saldo_diarias"]
    situacao = "suficiente" if saldo >= float(valor) else "INSUFICIENTE"
    return f"Saldo da unidade {sigla}: R$ {saldo:.2f}. Saldo {situacao} para R$ {float(valor):.2f} (art. 8º)."


FERRAMENTAS = [
    consultar_servidor,
    consultar_historico_diarias,
    calcular_diarias,
    consultar_saldo_diarias,
]
