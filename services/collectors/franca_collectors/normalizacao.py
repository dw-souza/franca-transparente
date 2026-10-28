"""Funções puras de normalização compartilhadas por todos os coletores."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

FUSO_BRASILIA = ZoneInfo("America/Sao_Paulo")
_NAO_ALFANUM = re.compile(r"[^0-9A-Za-z]")


def normalizar_documento(valor: Any) -> str | None:
    """CNPJ/CPF só com [0-9A-Z]. Preserva letras do CNPJ alfanumérico."""
    if valor is None:
        return None
    return _NAO_ALFANUM.sub("", str(valor)).upper() or None


def texto(valor: Any) -> str | None:
    if valor is None:
        return None
    s = re.sub(r"\s+", " ", str(valor)).strip()
    return s or None


def decimal_ou_none(valor: Any) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        # str() evita artefatos de float binário (0.1 + 0.2)
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def inteiro_ou_none(valor: Any) -> int | None:
    try:
        return int(valor) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def data_hora(valor: Any) -> datetime | None:
    """ISO 8601; datas sem fuso (padrão do PNCP) são interpretadas no horário de Brasília."""
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor))  # aceita sufixo "Z" desde o Python 3.11
    except ValueError:
        return None
    return dt.replace(tzinfo=FUSO_BRASILIA) if dt.tzinfo is None else dt


def data(valor: Any) -> date | None:
    if not valor:
        return None
    s = str(valor)
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    try:  # formato brasileiro, comum nos portais municipais
        return datetime.strptime(s[:10], "%d/%m/%Y").date()
    except ValueError:
        return None


def hash_payload(payload: Any) -> str:
    bruto = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def caminho(obj: Any, expr: str | None, padrao: Any = None) -> Any:
    """Acesso por caminho pontuado: "unidadeOrgao.codigoIbge", "itens.0.valor". "" ou None = o próprio obj."""
    if not expr:
        return obj
    atual = obj
    for parte in expr.split("."):
        if isinstance(atual, dict):
            atual = atual.get(parte)
        elif isinstance(atual, list) and parte.lstrip("-").isdigit():
            idx = int(parte)
            atual = atual[idx] if -len(atual) <= idx < len(atual) else None
        else:
            return padrao
        if atual is None:
            return padrao
    return atual
