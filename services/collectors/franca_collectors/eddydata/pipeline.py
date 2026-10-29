"""Orquestração da coleta do portal municipal (EddyData).

Um recurso por vez, em janelas mensais pelo campo de data que a própria tela pública usa, páginas de 1.000
registros (aceito pela API) e só as relações necessárias para a lista branca da normalização.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial
from typing import Any

from franca_collectors.eddydata.cliente import EddyDataClient
from franca_collectors.eddydata.normalize import (
    normalizar_aditamento,
    normalizar_contrato_municipal,
    normalizar_empenho,
    normalizar_liquidacao,
    normalizar_pagamento,
)
from franca_collectors.normalizacao import normalizar_documento
from franca_collectors.pncp.client import janelas
from franca_collectors.pncp.pipeline import Estatisticas, _processar
from franca_collectors.storage.base import Sink

log = logging.getLogger(__name__)

SOBREPOSICAO_INCREMENTAL = timedelta(days=15)  # anulações e alterações lançadas com atraso
LIMITE_PAGINA = 1000


@dataclass(frozen=True)
class Recurso:
    tipo: str               # chave em Sink.salvar_municipal
    caminho: str            # recurso na API
    campo_data: str
    relations: str
    filtro_orgao: str = "orgao.id"
    precisa_cnpj: bool = False


RECURSOS: dict[str, Recurso] = {r.tipo: r for r in (
    Recurso("contrato", "contratos", "data_inicio", "favorecido,licitacao", precisa_cnpj=True),
    Recurso("aditamento", "contrato-aditamentos", "data_aditamento", "contrato", filtro_orgao="contrato.orgao.id"),
    Recurso("empenho", "empenhos", "data_empenho",
            "favorecido,subelemento,modalidade,contrato,licitacao,ficha,ficha.executora,ficha.executora.unidade,"
            "ficha.despesa,ficha.funcao,ficha.subfuncao,ficha.programa,ficha.acao,ficha.recurso",
            precisa_cnpj=True),
    Recurso("liquidacao", "liquidacoes", "data_liquidacao", "empenho"),
    Recurso("pagamento", "pagamentos", "data_pagamento", "liquidacao,liquidacao.empenho"),
)}

_NORMALIZADORES: dict[str, Callable[..., Any]] = {
    "contrato": normalizar_contrato_municipal,
    "aditamento": normalizar_aditamento,
    "empenho": normalizar_empenho,
    "liquidacao": normalizar_liquidacao,
    "pagamento": normalizar_pagamento,
}


def coletor_de(tipo: str) -> str:
    return f"eddydata.{tipo}"


class ColetorEddyData:
    def __init__(self, cliente: EddyDataClient, sink: Sink, janela_dias: int = 31):
        self.cliente = cliente
        self.sink = sink
        self.janela_dias = janela_dias
        self._orgao: dict[str, Any] | None = None

    @property
    def orgao(self) -> dict[str, Any]:
        if self._orgao is None:
            self._orgao = self.cliente.orgao()
            self._orgao["cnpj"] = normalizar_documento(self._orgao["cnpj"])
        return self._orgao

    def coletar_recurso(self, tipo: str, inicio: date, fim: date) -> Estatisticas:
        rec = RECURSOS[tipo]
        normalizar = _NORMALIZADORES[tipo]
        if rec.precisa_cnpj:
            normalizar = partial(normalizar, orgao_cnpj=self.orgao["cnpj"])
        total = Estatisticas()
        for a, b in janelas(inicio, fim, self.janela_dias):
            stats = Estatisticas()
            params = {"ignoreCondObrig": "true", rec.filtro_orgao: self.orgao["id"], "relations": rec.relations,
                      f"{rec.campo_data}$ge": a.isoformat(), f"{rec.campo_data}$le": b.isoformat()}
            exec_id = self.sink.iniciar_execucao(coletor_de(tipo), {"recurso": rec.caminho}, a, b)
            try:
                _processar(self.cliente.paginar(rec.caminho, params, LIMITE_PAGINA), normalizar,
                           lambda r, t=tipo: self.sink.salvar_municipal(t, r), stats)
            except Exception as exc:
                self.sink.finalizar_execucao(exec_id, "erro", stats.lidos, stats.gravados, stats.erros, str(exc))
                raise
            self.sink.finalizar_execucao(exec_id, "parcial" if stats.erros else "sucesso",
                                         stats.lidos, stats.gravados, stats.erros)
            log.info("%s %s→%s: %s", coletor_de(tipo), a, b, stats)
            total.lidos += stats.lidos
            total.erros += stats.erros
            total.resultados.update(stats.resultados)
        return total

    def inicio_incremental(self, tipo: str, padrao: date) -> date:
        ultimo = self.sink.ultima_janela(coletor_de(tipo))
        return max(padrao, ultimo - SOBREPOSICAO_INCREMENTAL) if ultimo else padrao

    def coletar(self, inicio: date, fim: date, tipos: Iterable[str] = tuple(RECURSOS),
                incremental: bool = False) -> dict[str, Estatisticas]:
        resumo = {}
        for tipo in tipos:
            a = self.inicio_incremental(tipo, inicio) if incremental else inicio
            resumo[tipo] = self.coletar_recurso(tipo, a, fim)
        return resumo
