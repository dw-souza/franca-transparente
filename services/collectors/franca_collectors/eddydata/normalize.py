"""EddyData (JSON da API do portal municipal) → modelos normalizados.

Lista branca: de cada objeto só saem os campos abaixo. O ``favorecido`` traz ~70 campos (CPF, PIS, nascimento,
endereço, dados bancários); daqui sai apenas documento, tipo de pessoa e nome. CPF dentro de texto livre
(histórico) chega mascarado. Vínculo com o PNCP: ``{cnpj}-1-{sequencial:06d}/{ano}`` (licitação) e
``{cnpj}-2-{sequencial:06d}/{ano}`` (contrato), conferido contra o PNCP em 2026-10-29.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from franca_collectors.models import (
    Aditamento,
    ContratoMunicipal,
    Empenho,
    Fornecedor,
    Liquidacao,
    Pagamento,
    UnidadeOrcamentaria,
)
from franca_collectors.normalizacao import (
    FUSO_BRASILIA,
    caminho,
    data_hora,
    decimal_ou_none,
    hash_payload,
    inteiro_ou_none,
    normalizar_documento,
    texto,
)

_CPF_EM_TEXTO = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")


def mascarar_cpf(valor: str | None) -> str | None:
    """CPF solto em texto livre (histórico, nome de MEI) vira ***.***.***-**."""
    return _CPF_EM_TEXTO.sub("***.***.***-**", valor) if valor else valor


def data_local(valor: Any) -> date | None:
    """Datas do EddyData vêm como meia-noite de Brasília em UTC ("2026-09-28T03:00:00.000Z")."""
    dt = data_hora(valor)
    return dt.astimezone(FUSO_BRASILIA).date() if dt else None


def _id_pncp(cnpj: str, tipo: int, sequencial: Any, ano: Any) -> str | None:
    seq, a = inteiro_ou_none(sequencial), inteiro_ou_none(ano)
    return f"{cnpj}-{tipo}-{seq:06d}/{a}" if seq and a else None


def _fornecedor(fav: dict[str, Any] | None) -> tuple[Fornecedor | None, str | None]:
    if not fav:
        return None, None
    nome = texto(fav.get("nome"))
    doc = normalizar_documento(fav.get("cpf_cnpj"))
    if doc and re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", doc):
        tipo = "PJ"
    elif doc and re.fullmatch(r"[0-9]{11}", doc):
        tipo = "PF"
    else:  # sem documento válido: guarda só o nome do credor
        return None, nome
    return Fornecedor(cnpj_cpf=doc, tipo_pessoa=tipo, razao_social=nome or "(sem nome)"), nome


def _codigo_nome(obj: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not isinstance(obj, dict):
        return None, None
    return texto(obj.get("codigo")), texto(obj.get("nome"))


def normalizar_empenho(raw: dict[str, Any], orgao_cnpj: str) -> Empenho:
    ficha = raw.get("ficha") or {}
    unidade_cod, unidade_nome = _codigo_nome(caminho(ficha, "executora.unidade"))
    executora_cod, executora_nome = _codigo_nome(ficha.get("executora"))
    despesa_cod, despesa_nome = _codigo_nome(ficha.get("despesa"))
    sub_cod, sub_nome = _codigo_nome(raw.get("subelemento"))
    recurso_cod, recurso_nome = _codigo_nome(ficha.get("recurso"))
    fornecedor, credor = _fornecedor(raw.get("favorecido"))
    contrato = raw.get("contrato") or {}
    licitacao = raw.get("licitacao") or {}
    data_empenho = data_local(raw.get("data_empenho"))
    return Empenho(
        id_fonte=int(raw["id"]),
        orgao_cnpj=orgao_cnpj,
        unidade=UnidadeOrcamentaria(codigo=unidade_cod, nome=unidade_nome or unidade_cod)
        if unidade_cod else None,
        fornecedor=fornecedor,
        credor_nome=credor,
        numero=inteiro_ou_none(raw.get("numero")),
        ano=data_empenho.year,
        especie=texto(raw.get("especie")),
        tipo_empenho=texto(raw.get("tipo_empenho")),
        data_empenho=data_empenho,
        valor=decimal_ou_none(raw.get("valor_empenho")),
        processo=texto(raw.get("processo")),
        historico=mascarar_cpf(texto(raw.get("historico"))),
        executora_codigo=executora_cod,
        executora_nome=executora_nome,
        despesa_codigo=despesa_cod,
        despesa_nome=despesa_nome,
        subelemento_codigo=sub_cod,
        subelemento_nome=sub_nome,
        funcao=texto(caminho(ficha, "funcao.nome")),
        subfuncao=texto(caminho(ficha, "subfuncao.nome")),
        programa=texto(caminho(ficha, "programa.nome")),
        acao=texto(caminho(ficha, "acao.nome")),
        fonte_recurso_codigo=recurso_cod,
        fonte_recurso_nome=recurso_nome,
        modalidade=texto(caminho(raw, "modalidade.nome")),
        contrato_id_fonte=inteiro_ou_none(contrato.get("id")),
        contrato_id_pncp=_id_pncp(orgao_cnpj, 2, contrato.get("sequencial_pncp"), contrato.get("ano")),
        licitacao_id_pncp=_id_pncp(orgao_cnpj, 1, licitacao.get("sequencial_pncp"), licitacao.get("ano_pncp")),
        payload_hash=hash_payload(raw),
    )


def normalizar_contrato_municipal(raw: dict[str, Any], orgao_cnpj: str) -> ContratoMunicipal:
    fornecedor, credor = _fornecedor(raw.get("favorecido"))
    licitacao = raw.get("licitacao") or {}
    return ContratoMunicipal(
        id_fonte=int(raw["id"]),
        orgao_cnpj=orgao_cnpj,
        fornecedor=fornecedor,
        credor_nome=mascarar_cpf(credor),
        numero=texto(raw.get("numero")),
        ano=inteiro_ou_none(raw.get("ano")),
        processo=texto(raw.get("processo")),
        tipo=texto(raw.get("tipo")),
        tipo_contrato=texto(raw.get("tipo_contrato")),
        objeto=texto(raw.get("objeto")),
        valor=decimal_ou_none(raw.get("valor_contrato")),
        data_assinatura=data_local(raw.get("data_assinatura")),
        data_inicio=data_local(raw.get("data_inicio")),
        data_termino=data_local(raw.get("data_termino")),
        excluido=bool(raw.get("excluido")),
        inativo=bool(raw.get("inativo")),
        id_pncp=_id_pncp(orgao_cnpj, 2, raw.get("sequencial_pncp"), raw.get("ano")),
        licitacao_id_pncp=_id_pncp(orgao_cnpj, 1, licitacao.get("sequencial_pncp"), licitacao.get("ano_pncp")),
        payload_hash=hash_payload(raw),
    )


def normalizar_aditamento(raw: dict[str, Any]) -> Aditamento:
    return Aditamento(
        id_fonte=int(raw["id"]),
        contrato_id_fonte=int(caminho(raw, "contrato.id")),
        numero=texto(raw.get("numero")),
        finalidade=texto(raw.get("finalidade")),
        data_aditamento=data_local(raw.get("data_aditamento")),
        data_inicio=data_local(raw.get("data_inicio")),
        data_termino=data_local(raw.get("data_termino")),
        valor_total=decimal_ou_none(raw.get("valor_total")),
        valor_aditado=decimal_ou_none(raw.get("valor_aditado")),
        mudanca_vigencia=raw.get("mudanca_vigencia"),
        mudanca_reajuste=raw.get("mudanca_reajuste"),
        mudanca_favorecido=raw.get("mudanca_favorecido"),
        payload_hash=hash_payload(raw),
    )


def normalizar_liquidacao(raw: dict[str, Any]) -> Liquidacao:
    return Liquidacao(
        id_fonte=int(raw["id"]),
        empenho_id_fonte=int(caminho(raw, "empenho.id")),
        data_liquidacao=data_local(raw.get("data_liquidacao")),
        valor=decimal_ou_none(raw.get("valor_liquidado")),
        anulacao=bool(raw.get("anulacao")),
        anulado_total=bool(raw.get("anulado_total")),
        documento=texto(raw.get("documento")),
        payload_hash=hash_payload(raw),
    )


def normalizar_pagamento(raw: dict[str, Any]) -> Pagamento:
    return Pagamento(
        id_fonte=int(raw["id"]),
        liquidacao_id_fonte=int(caminho(raw, "liquidacao.id")),
        empenho_id_fonte=inteiro_ou_none(caminho(raw, "liquidacao.empenho.id")),
        data_pagamento=data_local(raw.get("data_pagamento")),
        valor=decimal_ou_none(raw.get("valor_pago")),
        valor_retido=decimal_ou_none(raw.get("valor_retido")),
        anulacao=bool(raw.get("anulacao")),
        anulado_total=bool(raw.get("anulado_total")),
        documento=texto(raw.get("documento")),
        payload_hash=hash_payload(raw),
    )
