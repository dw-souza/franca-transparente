"""Especificação declarativa de um endpoint mapeado (um arquivo YAML pode conter vários)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from franca_collectors.normalizacao import hash_payload

Status = Literal["a_mapear", "mapeado", "validado", "quebrado", "descontinuado"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")  # erro de digitação no YAML falha cedo


class Paginacao(_Base):
    tipo: Literal["nenhuma", "pagina", "offset"] = "nenhuma"
    parametro: str = "pagina"                # nome do parâmetro de página (ou de offset, ex.: "start")
    inicio: int = 1                          # 1 para página 1-based, 0 para offset
    tamanho_parametro: str | None = None     # ex.: "tamanhoPagina", "length", "pageSize"
    tamanho: int | None = None
    total_paginas_em: str | None = None      # caminho no JSON com o total de páginas, se houver
    max_paginas: int = 1000                  # trava de segurança
    em: Literal["params", "corpo"] = "params"


class Descoberta(_Base):
    em: date | None = None
    por: str | None = None
    metodo: str | None = None                # "devtools/HAR", "mitmproxy", "leitura do JS"...
    evidencia: str | None = None             # caminho do HAR/print no repositório de evidências


class EndpointSpec(_Base):
    id: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")   # "transparencia.despesas.empenhos"
    portal: str
    descricao: str | None = None
    status: Status = "a_mapear"
    ativo: bool = False
    destino: str | None = None               # entidade lógica: licitacoes, contratos, despesas, diarios...

    metodo: Literal["GET", "POST"] = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)      # aceitam templates: "{data_inicio:%d/%m/%Y}"
    corpo: dict[str, Any] | None = None
    corpo_tipo: Literal["form", "json"] = "form"

    registros_em: str | None = None          # caminho da lista de registros no JSON ("data", "d.itens")
    chave: str | list[str] | None = None     # campo(s) que identificam o registro; vazio = hash do payload
    mapeamento: dict[str, str] = Field(default_factory=dict)  # campo_destino: caminho_na_origem
    paginacao: Paginacao = Field(default_factory=Paginacao)
    janela_dias: int | None = None           # se o endpoint recebe intervalo de datas
    intervalo_segundos: float = 1.0          # cortesia com o servidor municipal

    descoberta: Descoberta | None = None
    notas: str | None = None

    @model_validator(mode="after")
    def _coerencia(self) -> EndpointSpec:
        if self.status != "a_mapear" and not self.url.startswith(("http://", "https://")):
            raise ValueError(f"{self.id}: status {self.status!r} exige url http(s) completa")
        if self.ativo and self.status not in ("mapeado", "validado"):
            raise ValueError(f"{self.id}: só endpoints mapeados/validados podem ficar ativos")
        return self

    def sha256(self) -> str:
        return hash_payload(self.model_dump(mode="json"))


def carregar_arquivo(caminho: Path) -> list[EndpointSpec]:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    itens = dados.get("endpoints", []) if isinstance(dados, dict) else dados
    padrao = dados.get("padrao", {}) if isinstance(dados, dict) else {}
    try:
        return [EndpointSpec.model_validate({**padrao, **item}) for item in itens]
    except Exception as exc:
        raise ValueError(f"{caminho.name}: {exc}") from exc


def carregar_specs(diretorio: Path, incluir_modelos: bool = False) -> list[EndpointSpec]:
    """Lê endpoints/*.yaml. Arquivos iniciados por "_" são modelos/documentação."""
    specs: list[EndpointSpec] = []
    for arq in sorted(Path(diretorio).glob("*.y*ml")):
        if arq.name.startswith("_") and not incluir_modelos:
            continue
        specs.extend(carregar_arquivo(arq))
    ids = [s.id for s in specs]
    duplicados = {i for i in ids if ids.count(i) > 1}
    if duplicados:
        raise ValueError(f"ids de endpoint duplicados: {sorted(duplicados)}")
    return specs
