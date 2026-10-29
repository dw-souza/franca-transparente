"""PNCP (JSON da API de consulta) → modelos normalizados.

Os nomes de campo seguem o schema da API de consulta v1. Campos ausentes viram None em vez de
quebrar a coleta; o JSON original fica em `payload_bruto` para reprocessamento.
"""

from __future__ import annotations

from typing import Any

from franca_collectors.models import Contrato, Fornecedor, ItemResultado, Licitacao, LicitacaoItem, Orgao
from franca_collectors.normalizacao import (
    caminho,
    data,
    data_hora,
    decimal_ou_none,
    hash_payload,
    inteiro_ou_none,
    texto,
)
from franca_collectors.pncp.dominios import MODALIDADES


def _orgao(raw: dict[str, Any]) -> Orgao:
    oe = raw.get("orgaoEntidade") or {}
    uo = raw.get("unidadeOrgao") or {}
    return Orgao(
        cnpj=oe.get("cnpj"),
        razao_social=texto(oe.get("razaoSocial")) or "(sem razão social)",
        poder=texto(oe.get("poderId")),
        esfera=texto(oe.get("esferaId")),
        codigo_ibge=texto(uo.get("codigoIbge")),
        municipio=texto(uo.get("municipioNome")),
        uf=texto(uo.get("ufSigla")),
    )


def _nome(obj: Any) -> str | None:
    """Campos de domínio vêm como {"id":..,"nome":..} ou, às vezes, como string."""
    if isinstance(obj, dict):
        return texto(obj.get("nome") or obj.get("descricao"))
    return texto(obj)


def normalizar_contratacao(raw: dict[str, Any]) -> Licitacao:
    modalidade_id = inteiro_ou_none(raw.get("modalidadeId"))
    return Licitacao(
        id_pncp=raw["numeroControlePNCP"],
        orgao=_orgao(raw),
        unidade_codigo=texto(caminho(raw, "unidadeOrgao.codigoUnidade")),
        unidade_nome=texto(caminho(raw, "unidadeOrgao.nomeUnidade")),
        numero=texto(raw.get("numeroCompra")),
        ano=int(raw["anoCompra"]),
        sequencial=inteiro_ou_none(raw.get("sequencialCompra")),
        processo=texto(raw.get("processo")),
        objeto=texto(raw.get("objetoCompra")) or "(objeto não informado)",
        informacao_complementar=texto(raw.get("informacaoComplementar")),
        modalidade_id=modalidade_id,
        modalidade_nome=texto(raw.get("modalidadeNome")) or MODALIDADES.get(modalidade_id or -1),
        modo_disputa=texto(raw.get("modoDisputaNome")),
        amparo_legal=_nome(raw.get("amparoLegal")),
        srp=bool(raw.get("srp")),
        valor_estimado=decimal_ou_none(raw.get("valorTotalEstimado")),
        valor_homologado=decimal_ou_none(raw.get("valorTotalHomologado")),
        data_publicacao=data_hora(raw.get("dataPublicacaoPncp")),
        data_abertura=data_hora(raw.get("dataAberturaProposta")),
        data_encerramento=data_hora(raw.get("dataEncerramentoProposta")),
        status=texto(raw.get("situacaoCompraNome")) or "Desconhecida",
        situacao_pncp_id=inteiro_ou_none(raw.get("situacaoCompraId")),
        link_sistema_origem=texto(raw.get("linkSistemaOrigem")),
        data_atualizacao_fonte=data_hora(raw.get("dataAtualizacaoGlobal") or raw.get("dataAtualizacao")),
        payload_hash=hash_payload(raw),
        payload_bruto=raw,
    )


def normalizar_contrato(raw: dict[str, Any]) -> Contrato:
    valor_global = decimal_ou_none(raw.get("valorGlobal"))
    valor_inicial = decimal_ou_none(raw.get("valorInicial"))
    tipo_pessoa = (texto(raw.get("tipoPessoa")) or "PJ").upper()
    return Contrato(
        id_pncp=raw["numeroControlePNCP"],
        id_pncp_compra=texto(raw.get("numeroControlePncpCompra")),
        orgao=_orgao(raw),
        fornecedor=Fornecedor(
            cnpj_cpf=raw.get("niFornecedor"),
            tipo_pessoa=tipo_pessoa if tipo_pessoa in ("PJ", "PF", "PE") else "PJ",
            razao_social=texto(raw.get("nomeRazaoSocialFornecedor")) or "(sem razão social)",
        ),
        unidade_codigo=texto(caminho(raw, "unidadeOrgao.codigoUnidade")),
        unidade_nome=texto(caminho(raw, "unidadeOrgao.nomeUnidade")),
        numero=texto(raw.get("numeroContratoEmpenho")),
        ano=inteiro_ou_none(raw.get("anoContrato")),
        sequencial=inteiro_ou_none(raw.get("sequencialContrato")),
        processo=texto(raw.get("processo")),
        tipo_contrato=_nome(raw.get("tipoContrato")),
        categoria_processo=_nome(raw.get("categoriaProcesso")),
        objeto=texto(raw.get("objetoContrato")) or "(objeto não informado)",
        informacao_complementar=texto(raw.get("informacaoComplementar")),
        valor_inicial=valor_inicial,
        valor_total=valor_global if valor_global is not None else (valor_inicial or 0),
        valor_acumulado=decimal_ou_none(raw.get("valorAcumulado")),
        numero_parcelas=inteiro_ou_none(raw.get("numeroParcelas")),
        valor_parcela=decimal_ou_none(raw.get("valorParcela")),
        data_assinatura=data(raw.get("dataAssinatura")),
        vigencia_inicio=data(raw.get("dataVigenciaInicio")),
        vigencia_fim=data(raw.get("dataVigenciaFim")),
        data_publicacao=data_hora(raw.get("dataPublicacaoPncp")),
        receita=bool(raw.get("receita")),
        data_atualizacao_fonte=data_hora(raw.get("dataAtualizacaoGlobal") or raw.get("dataAtualizacao")),
        payload_hash=hash_payload(raw),
        payload_bruto=raw,
    )


def normalizar_resultado(raw: dict[str, Any]) -> ItemResultado:
    ni = raw.get("niFornecedor")
    tipo_pessoa = (texto(raw.get("tipoPessoa")) or "PJ").upper()
    return ItemResultado(
        sequencial=int(raw.get("sequencialResultado") or 1),
        fornecedor=Fornecedor(
            cnpj_cpf=ni,
            tipo_pessoa=tipo_pessoa if tipo_pessoa in ("PJ", "PF", "PE") else "PJ",
            razao_social=texto(raw.get("nomeRazaoSocialFornecedor")) or "(sem razão social)",
        ) if ni else None,
        quantidade_homologada=decimal_ou_none(raw.get("quantidadeHomologada"), casas=4),
        valor_unitario_homologado=decimal_ou_none(raw.get("valorUnitarioHomologado"), casas=4),
        valor_total_homologado=decimal_ou_none(raw.get("valorTotalHomologado")),
        percentual_desconto=decimal_ou_none(raw.get("percentualDesconto"), casas=4),
        porte_fornecedor=texto(raw.get("porteFornecedorNome")),
        situacao=texto(raw.get("situacaoCompraItemResultadoNome")),
        data_resultado=data(raw.get("dataResultado")),
        data_atualizacao_fonte=data_hora(raw.get("dataAtualizacao")),
        payload_hash=hash_payload(raw),
    )


def normalizar_item(raw: dict[str, Any], resultados: list[dict[str, Any]] | None = None) -> LicitacaoItem:
    tipo = (texto(raw.get("materialOuServico")) or "").upper()
    return LicitacaoItem(
        numero_item=int(raw["numeroItem"]),
        descricao=texto(raw.get("descricao")) or "(sem descrição)",
        material_servico=tipo if tipo in ("M", "S") else None,
        unidade_medida=texto(raw.get("unidadeMedida")),
        quantidade=decimal_ou_none(raw.get("quantidade"), casas=4),
        valor_unitario_estimado=decimal_ou_none(raw.get("valorUnitarioEstimado"), casas=4),
        valor_total_estimado=decimal_ou_none(raw.get("valorTotal")),
        orcamento_sigiloso=bool(raw.get("orcamentoSigiloso")),
        criterio_julgamento=texto(raw.get("criterioJulgamentoNome")),
        situacao=texto(raw.get("situacaoCompraItemNome")),
        tem_resultado=bool(raw.get("temResultado")),
        ncm_nbs_codigo=texto(raw.get("ncmNbsCodigo")),
        catalogo_codigo=texto(raw.get("catalogoCodigoItem")),
        data_atualizacao_fonte=data_hora(raw.get("dataAtualizacao")),
        payload_hash=hash_payload(raw),
        resultados=tuple(normalizar_resultado(r) for r in resultados or ()),
    )
