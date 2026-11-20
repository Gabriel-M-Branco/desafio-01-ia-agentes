""" Modelos Pydantic de saída estruturada para a instrução de pedidos de diárias (Etapa 3)."""

from typing import Literal, Optional
from pydantic import BaseModel


class Verificacao(BaseModel):
    criterio: Literal[
        "cadastro",
        "dados_completos",
        "antecedencia",
        "prestacao_contas",
        "limite_mensal",
        "saldo_orcamentario",
    ]
    situacao: Literal["atende", "nao_atende", "nao_verificado"]
    detalhe: str  # o dado que fundamenta a situação, como veio da ferramenta


class Instrucao(BaseModel):
    numero_pedido: str
    matricula: str
    quantidade_diarias: Optional[float] = None  # nulo na diligência
    valor_total: Optional[float] = None  # nulo na diligência
    verificacoes: list[Verificacao]
    recomendacao: Literal["apto_para_autorizacao", "diligencia", "nao_recomendado"]
    exige_autorizacao_superior: bool
    pendencias: list[str]  # o que o solicitante precisa corrigir
    alertas: list[str]  # ordens embutidas, dados mascarados, o que o conferente precisa ver
    minuta_despacho: str
