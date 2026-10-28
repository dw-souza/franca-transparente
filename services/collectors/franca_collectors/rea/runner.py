"""Executor genérico de endpoints declarados em YAML."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date
from typing import Any

import requests

from franca_collectors.http import RespostaInvalida, Throttle
from franca_collectors.models import RegistroBruto
from franca_collectors.normalizacao import caminho, hash_payload
from franca_collectors.pncp.client import janelas
from franca_collectors.pncp.pipeline import Estatisticas
from franca_collectors.rea.spec import EndpointSpec
from franca_collectors.storage.base import Sink

log = logging.getLogger(__name__)


class _Contexto(dict):
    def __missing__(self, chave: str):
        raise KeyError(f"variável de template desconhecida: {{{chave}}} (disponíveis: {sorted(self)})")


def renderizar(valor: Any, contexto: dict[str, Any]) -> Any:
    """Aplica str.format_map recursivamente: "{data_inicio:%d/%m/%Y}" → "01/10/2026"."""
    if isinstance(valor, str):
        return valor.format_map(_Contexto(contexto))
    if isinstance(valor, dict):
        return {k: renderizar(v, contexto) for k, v in valor.items()}
    if isinstance(valor, list):
        return [renderizar(v, contexto) for v in valor]
    return valor


class ExecutorEndpoint:
    def __init__(self, sessao: requests.Session, spec: EndpointSpec, timeout: float = 30.0):
        self.sessao = sessao
        self.spec = spec
        self.timeout = timeout
        self.throttle = Throttle(spec.intervalo_segundos)

    def _requisitar(self, params: dict[str, Any], corpo: dict[str, Any] | None) -> Any:
        s = self.spec
        self.throttle.esperar()
        kwargs: dict[str, Any] = {"params": params or None, "headers": s.headers or None, "timeout": self.timeout}
        if corpo is not None:
            kwargs["json" if s.corpo_tipo == "json" else "data"] = corpo
        resp = self.sessao.request(s.metodo, s.url, **kwargs)
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError as exc:
            raise RespostaInvalida(f"{s.id}: resposta não é JSON ({resp.headers.get('Content-Type')})") from exc

    def registros(self, contexto: dict[str, Any]) -> Iterator[dict[str, Any]]:
        s, pag = self.spec, self.spec.paginacao
        params = renderizar(s.params, contexto)
        corpo = renderizar(s.corpo, contexto) if s.corpo is not None else None
        alvo = corpo if (pag.em == "corpo" and corpo is not None) else params
        if pag.tamanho_parametro and pag.tamanho:
            alvo[pag.tamanho_parametro] = pag.tamanho

        posicao = pag.inicio
        for n in range(1, pag.max_paginas + 1):
            if pag.tipo != "nenhuma":
                alvo[pag.parametro] = posicao
            corpo_resp = self._requisitar(params, corpo)
            itens = caminho(corpo_resp, s.registros_em)
            if itens is None:
                itens = []
            if not isinstance(itens, list):
                raise RespostaInvalida(f"{s.id}: '{s.registros_em}' não aponta para uma lista")
            yield from itens

            if pag.tipo == "nenhuma" or not itens:
                return
            if pag.tamanho and len(itens) < pag.tamanho:
                return
            total = caminho(corpo_resp, pag.total_paginas_em) if pag.total_paginas_em else None
            if total is not None and n >= int(total):
                return
            posicao += len(itens) if pag.tipo == "offset" else 1
        log.warning("%s: atingiu max_paginas=%s", s.id, pag.max_paginas)

    def para_registro(self, raw: dict[str, Any]) -> RegistroBruto:
        s = self.spec
        campos = [s.chave] if isinstance(s.chave, str) else (s.chave or [])
        partes = [caminho(raw, c) for c in campos]
        chave = "|".join(str(p) for p in partes) if campos and all(p is not None for p in partes) \
            else hash_payload(raw)
        mapeado = {destino: caminho(raw, origem) for destino, origem in s.mapeamento.items()} or None
        return RegistroBruto(endpoint_id=s.id, chave=chave, payload=raw, mapeado=mapeado,
                             payload_hash=hash_payload(raw))


def coletar_endpoint(
    sessao: requests.Session,
    spec: EndpointSpec,
    sink: Sink,
    inicio: date | None = None,
    fim: date | None = None,
    extra: dict[str, Any] | None = None,
) -> Estatisticas:
    executor = ExecutorEndpoint(sessao, spec)
    hoje = date.today()
    inicio, fim = inicio or hoje, fim or hoje
    blocos = janelas(inicio, fim, spec.janela_dias) if spec.janela_dias else [(inicio, fim)]
    total = Estatisticas()
    for a, b in blocos:
        ctx = {"data_inicio": a, "data_fim": b, "ano": a.year, **(extra or {})}
        exec_id = sink.iniciar_execucao(f"rea:{spec.id}", {"contexto": {k: str(v) for k, v in ctx.items()}},
                                        a, b, endpoint_id=spec.id)
        stats = Estatisticas()
        try:
            for raw in executor.registros(ctx):
                stats.lidos += 1
                try:
                    stats.resultados[sink.salvar_registro_bruto(executor.para_registro(raw), exec_id)] += 1
                except Exception as exc:  # noqa: BLE001 - um registro ruim não derruba a coleta
                    stats.erros += 1
                    log.error("%s: falha ao gravar registro: %s", spec.id, exc)
        except Exception as exc:
            sink.finalizar_execucao(exec_id, "erro", stats.lidos, stats.gravados, stats.erros, str(exc))
            raise
        sink.finalizar_execucao(exec_id, "parcial" if stats.erros else "sucesso",
                                stats.lidos, stats.gravados, stats.erros)
        total.lidos += stats.lidos
        total.erros += stats.erros
        total.resultados.update(stats.resultados)
    return total
