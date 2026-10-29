"""Cliente da API pública de consulta do PNCP (sem autenticação).

Swagger: https://pncp.gov.br/api/consulta/swagger-ui/index.html
Particularidades tratadas aqui:
  * datas na query em AAAAMMDD;
  * HTTP 204 (sem corpo) quando não há resultados;
  * paginação por `pagina` (1-based) com `totalPaginas` / `paginasRestantes` no corpo;
  * `tamanhoPagina` mínimo 10 e máximo distinto por endpoint;
  * rate limiting (429) — tratado pela sessão com backoff + intervalo mínimo (Throttle).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import requests

from franca_collectors.http import RespostaInvalida, Throttle
from franca_collectors.pncp.dominios import PAGINA_MAX_CONTRATACOES, PAGINA_MAX_CONTRATOS, PAGINA_MIN

log = logging.getLogger(__name__)


def _aaaammdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def janelas(inicio: date, fim: date, dias: int) -> Iterator[tuple[date, date]]:
    """Divide [inicio, fim] em janelas fechadas de até `dias` dias (consultas longas são lentas/instáveis)."""
    if fim < inicio:
        raise ValueError("data final anterior à inicial")
    passo = timedelta(days=max(1, dias))
    atual = inicio
    while atual <= fim:
        ate = min(fim, atual + passo - timedelta(days=1))
        yield atual, ate
        atual = ate + timedelta(days=1)


class PNCPClient:
    def __init__(
        self,
        sessao: requests.Session,
        base_url: str = "https://pncp.gov.br/api/consulta",
        timeout: float = 30.0,
        delay: float = 0.5,
        api_pncp_url: str | None = None,
    ):
        self.sessao = sessao
        self.base_url = base_url.rstrip("/")
        # Itens e resultados ficam na API "pncp" (mesmo host, /api/pncp), não na de consulta.
        self.api_pncp_url = (api_pncp_url or self.base_url.replace("/api/consulta", "/api/pncp")).rstrip("/")
        self.timeout = timeout
        self.throttle = Throttle(delay)
        self.requisicoes = 0

    # ------------------------------------------------------------------ HTTP
    def _get(self, caminho: str, params: dict[str, Any], base: str | None = None) -> Any:
        url = f"{base or self.base_url}{caminho}"
        params = {k: v for k, v in params.items() if v is not None}
        self.throttle.esperar()
        resp = self.sessao.get(url, params=params, timeout=self.timeout)
        self.requisicoes += 1
        log.debug("GET %s %s -> %s", caminho, params, resp.status_code)

        if resp.status_code == 400:
            raise ValueError(f"PNCP rejeitou os parâmetros {params}: {resp.text[:300]}")
        resp.raise_for_status()  # antes do teste de corpo vazio: 429/5xx sem corpo não pode virar "sem resultados"
        if resp.status_code == 204 or not resp.content:
            return None
        if "json" not in resp.headers.get("Content-Type", ""):
            raise RespostaInvalida(
                f"{url} devolveu {resp.headers.get('Content-Type')!r} em vez de JSON "
                "(possível página de desafio/manutenção). Coleta interrompida."
            )
        return resp.json()

    def _paginar(self, caminho: str, params: dict[str, Any], tamanho: int) -> Iterator[dict[str, Any]]:
        pagina = 1
        while True:
            corpo = self._get(caminho, {**params, "pagina": pagina, "tamanhoPagina": tamanho})
            if not corpo:
                return
            registros = corpo.get("data") or []
            yield from registros
            total_paginas = corpo.get("totalPaginas") or 0
            restantes = corpo.get("paginasRestantes")
            if not registros or (restantes is not None and restantes <= 0) or pagina >= total_paginas:
                return
            pagina += 1

    # ------------------------------------------------------------ Endpoints
    def contratacoes_publicacao(
        self,
        inicio: date,
        fim: date,
        modalidade: int,
        codigo_ibge: str | None = None,
        cnpj: str | None = None,
        uf: str | None = None,
        tamanho: int = PAGINA_MAX_CONTRATACOES,
    ) -> Iterator[dict[str, Any]]:
        """GET /v1/contratacoes/publicacao — compras publicadas no período (modalidade obrigatória)."""
        return self._paginar(
            "/v1/contratacoes/publicacao",
            {
                "dataInicial": _aaaammdd(inicio),
                "dataFinal": _aaaammdd(fim),
                "codigoModalidadeContratacao": modalidade,
                "codigoMunicipioIbge": codigo_ibge,
                "cnpj": cnpj,
                "uf": uf,
            },
            max(PAGINA_MIN, min(tamanho, PAGINA_MAX_CONTRATACOES)),
        )

    def contratacoes_proposta(
        self,
        data_final: date,
        codigo_ibge: str | None = None,
        modalidade: int | None = None,
        cnpj: str | None = None,
        tamanho: int = PAGINA_MAX_CONTRATACOES,
    ) -> Iterator[dict[str, Any]]:
        """GET /v1/contratacoes/proposta — compras com recebimento de propostas aberto até `data_final`."""
        return self._paginar(
            "/v1/contratacoes/proposta",
            {
                "dataFinal": _aaaammdd(data_final),
                "codigoMunicipioIbge": codigo_ibge,
                "codigoModalidadeContratacao": modalidade,
                "cnpj": cnpj,
            },
            max(PAGINA_MIN, min(tamanho, PAGINA_MAX_CONTRATACOES)),
        )

    def contratos(
        self,
        inicio: date,
        fim: date,
        cnpj_orgao: str | None = None,
        tamanho: int = PAGINA_MAX_CONTRATOS,
    ) -> Iterator[dict[str, Any]]:
        """GET /v1/contratos — contratos publicados no período. Não filtra por município: use `cnpj_orgao`."""
        return self._paginar(
            "/v1/contratos",
            {"dataInicial": _aaaammdd(inicio), "dataFinal": _aaaammdd(fim), "cnpjOrgao": cnpj_orgao},
            max(PAGINA_MIN, min(tamanho, PAGINA_MAX_CONTRATOS)),
        )

    def itens_compra(self, cnpj: str, ano: int, sequencial: int, tamanho: int = 500) -> list[dict[str, Any]]:
        """GET .../compras/{ano}/{seq}/itens (API pncp). Pagina até somar `/itens/quantidade`, para não depender
        de o servidor respeitar `tamanhoPagina`; se faltar item, falha em vez de gravar a compra incompleta."""
        caminho = f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens"
        total = int(self._get(f"{caminho}/quantidade", {}, base=self.api_pncp_url) or 0)
        itens: list[dict[str, Any]] = []
        pagina = 1
        while len(itens) < total:
            lote = self._get(caminho, {"pagina": pagina, "tamanhoPagina": tamanho}, base=self.api_pncp_url) or []
            if not lote:
                raise RespostaInvalida(f"{caminho}: esperados {total} itens, vieram {len(itens)}")
            itens.extend(lote)
            pagina += 1
        return itens

    def resultados_item(self, cnpj: str, ano: int, sequencial: int, numero_item: int) -> list[dict[str, Any]]:
        """GET /v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens/{n}/resultados (API pncp)."""
        return self._get(f"/v1/orgaos/{cnpj}/compras/{ano}/{sequencial}/itens/{numero_item}/resultados", {},
                         base=self.api_pncp_url) or []
