"""Modelos normalizados (camada "prata"), independentes da fonte de origem.

Espelham as tabelas de database/migrations. O registro bruto viaja junto em `payload_bruto`.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from franca_collectors.normalizacao import normalizar_documento

_CNPJ = r"^[0-9A-Z]{12}[0-9]{2}$"  # aceita o CNPJ alfanumérico (vigente desde jul/2026)


class _Base(BaseModel):
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)


class Orgao(_Base):
    cnpj: str = Field(pattern=_CNPJ)
    razao_social: str
    poder: str | None = None
    esfera: str | None = None
    codigo_ibge: str | None = None
    municipio: str | None = None
    uf: str | None = None

    @field_validator("cnpj", mode="before")
    @classmethod
    def _norm_cnpj(cls, v: object) -> str | None:
        return normalizar_documento(v)


class Fornecedor(_Base):
    cnpj_cpf: str = Field(min_length=1, max_length=30)
    tipo_pessoa: Literal["PJ", "PF", "PE"] = "PJ"
    razao_social: str

    @field_validator("cnpj_cpf", mode="before")
    @classmethod
    def _norm_doc(cls, v: object) -> str | None:
        return normalizar_documento(v)


class Licitacao(_Base):
    id_pncp: str
    orgao: Orgao
    unidade_codigo: str | None = None
    unidade_nome: str | None = None
    numero: str | None = None
    ano: int
    sequencial: int | None = None
    processo: str | None = None
    objeto: str
    informacao_complementar: str | None = None
    modalidade_id: int | None = None
    modalidade_nome: str | None = None
    modo_disputa: str | None = None
    amparo_legal: str | None = None
    srp: bool = False
    valor_estimado: Decimal | None = None
    valor_homologado: Decimal | None = None
    data_publicacao: datetime | None = None
    data_abertura: datetime | None = None
    data_encerramento: datetime | None = None
    status: str
    situacao_pncp_id: int | None = None
    link_sistema_origem: str | None = None
    data_atualizacao_fonte: datetime | None = None
    fonte: str = "pncp"
    payload_hash: str
    payload_bruto: dict[str, Any] = Field(repr=False)


class Contrato(_Base):
    id_pncp: str
    id_pncp_compra: str | None = None
    orgao: Orgao
    fornecedor: Fornecedor
    unidade_codigo: str | None = None
    unidade_nome: str | None = None
    numero: str | None = None
    ano: int | None = None
    sequencial: int | None = None
    processo: str | None = None
    tipo_contrato: str | None = None
    categoria_processo: str | None = None
    objeto: str
    informacao_complementar: str | None = None
    valor_inicial: Decimal | None = None
    valor_total: Decimal
    valor_acumulado: Decimal | None = None
    numero_parcelas: int | None = None
    valor_parcela: Decimal | None = None
    data_assinatura: date | None = None
    vigencia_inicio: date | None = None
    vigencia_fim: date | None = None
    data_publicacao: datetime | None = None
    receita: bool = False
    data_atualizacao_fonte: datetime | None = None
    fonte: str = "pncp"
    payload_hash: str
    payload_bruto: dict[str, Any] = Field(repr=False)


class RegistroBruto(_Base):
    """Registro de um endpoint mapeado via REA, ainda sem modelo próprio (camada "bronze")."""

    endpoint_id: str
    chave: str
    payload: dict[str, Any]
    mapeado: dict[str, Any] | None = None
    payload_hash: str


class ItemResultado(_Base):
    """Resultado (fornecedor vencedor) de um item de contratação."""

    sequencial: int
    fornecedor: Fornecedor | None = None
    quantidade_homologada: Decimal | None = None
    valor_unitario_homologado: Decimal | None = None
    valor_total_homologado: Decimal | None = None
    percentual_desconto: Decimal | None = None
    porte_fornecedor: str | None = None
    situacao: str | None = None
    data_resultado: date | None = None
    data_atualizacao_fonte: datetime | None = None
    payload_hash: str


class LicitacaoItem(_Base):
    """Item de uma contratação; sem payload_bruto (volume alto, campos úteis já normalizados)."""

    numero_item: int
    descricao: str
    material_servico: Literal["M", "S"] | None = None
    unidade_medida: str | None = None
    quantidade: Decimal | None = None
    valor_unitario_estimado: Decimal | None = None
    valor_total_estimado: Decimal | None = None
    orcamento_sigiloso: bool = False
    criterio_julgamento: str | None = None
    situacao: str | None = None
    tem_resultado: bool = False
    ncm_nbs_codigo: str | None = None
    catalogo_codigo: str | None = None
    data_atualizacao_fonte: datetime | None = None
    payload_hash: str
    resultados: tuple[ItemResultado, ...] = ()
