"""Orquestração da coleta PNCP para um município.

Fase 1 — contratações (/contratacoes/publicacao) filtradas por código IBGE, uma consulta por modalidade.
Fase 2 — contratos (/contratos), que a API só filtra por CNPJ do órgão: consultamos os CNPJs
         configurados + os descobertos na fase 1. Assim um fundo municipal com CNPJ próprio que
         apareça no PNCP passa a ter seus contratos coletados sem configuração manual.

Unidades de outras esferas sediadas na cidade (estaduais/federais) são descartadas por padrão
(`esferas=("M",)`), já que o painel é sobre o município.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import requests
from pydantic import ValidationError

from franca_collectors.models import Contrato, Licitacao
from franca_collectors.pncp.client import PNCPClient, janelas
from franca_collectors.pncp.normalize import normalizar_contratacao, normalizar_contrato, normalizar_item
from franca_collectors.storage.base import Sink

log = logging.getLogger(__name__)

COLETOR_CONTRATACOES = "pncp.contratacoes"
COLETOR_CONTRATOS = "pncp.contratos"
COLETOR_ITENS = "pncp.itens"
SOBREPOSICAO_INCREMENTAL = timedelta(days=3)  # republicações/retificações tardias


@dataclass
class Estatisticas:
    lidos: int = 0
    erros: int = 0
    descartados: int = 0
    resultados: Counter = field(default_factory=Counter)

    @property
    def gravados(self) -> int:
        return self.resultados["inserido"] + self.resultados["atualizado"]

    def __str__(self) -> str:
        r = self.resultados
        return (f"lidos={self.lidos} inseridos={r['inserido']} atualizados={r['atualizado']} "
                f"inalterados={r['inalterado']} descartados={self.descartados} erros={self.erros}")


@dataclass
class ResumoColeta:
    contratacoes: Estatisticas = field(default_factory=Estatisticas)
    contratos: Estatisticas = field(default_factory=Estatisticas)
    cnpjs_orgaos: set[str] = field(default_factory=set)
    requisicoes: int = 0


def _processar(
    registros: Iterable[dict[str, Any]],
    normalizar: Callable[[dict[str, Any]], Licitacao | Contrato],
    salvar: Callable[[Any], str],
    stats: Estatisticas,
    aceitar: Callable[[Any], bool],
    depois: Callable[[Any], None] | None = None,
) -> None:
    for raw in registros:
        stats.lidos += 1
        try:
            item = normalizar(raw)
        except (ValidationError, KeyError, TypeError, ValueError) as exc:
            stats.erros += 1
            log.warning("registro inválido (%s): %s", raw.get("numeroControlePNCP", "?"), exc)
            continue
        if not aceitar(item):
            stats.descartados += 1
            continue
        try:
            stats.resultados[salvar(item)] += 1
        except Exception as exc:  # noqa: BLE001 - erro de gravação de uma linha não derruba a coleta
            stats.erros += 1
            log.error("falha ao gravar %s: %s", item.id_pncp, exc)
            continue
        if depois:
            depois(item)


class ColetorPNCP:
    def __init__(
        self,
        cliente: PNCPClient,
        sink: Sink,
        codigo_ibge: str,
        cnpjs_orgaos: Iterable[str] = (),
        modalidades: Iterable[int] = (),
        janela_dias: int = 30,
        esferas: tuple[str, ...] | None = ("M",),
    ):
        self.cliente = cliente
        self.sink = sink
        self.codigo_ibge = codigo_ibge
        self.cnpjs_configurados = {c for c in cnpjs_orgaos if c}
        self.modalidades = tuple(modalidades)
        self.janela_dias = janela_dias
        self.esferas = esferas

    # ----------------------------------------------------------- filtros
    def _da_esfera(self, item: Licitacao | Contrato) -> bool:
        return not self.esferas or item.orgao.esfera is None or item.orgao.esfera in self.esferas

    def _aceitar_contratacao(self, l: Licitacao) -> bool:
        return self._da_esfera(l) and (l.orgao.codigo_ibge in (None, self.codigo_ibge))

    def _aceitar_contrato(self, c: Contrato) -> bool:
        # /contratos filtra por CNPJ; ainda assim conferimos a unidade (órgãos com unidades em várias cidades)
        return self._da_esfera(c) and (c.orgao.codigo_ibge in (None, self.codigo_ibge))

    # ----------------------------------------------------------- execução
    def _executar(self, coletor: str, inicio: date, fim: date, parametros: dict,
                  corpo: Callable[[Estatisticas], None]) -> Estatisticas:
        stats = Estatisticas()
        exec_id = self.sink.iniciar_execucao(coletor, parametros, inicio, fim)
        try:
            corpo(stats)
        except Exception as exc:
            self.sink.finalizar_execucao(exec_id, "erro", stats.lidos, stats.gravados, stats.erros, str(exc))
            raise
        status = "parcial" if stats.erros else "sucesso"
        self.sink.finalizar_execucao(exec_id, status, stats.lidos, stats.gravados, stats.erros)
        log.info("%s %s→%s: %s", coletor, inicio, fim, stats)
        return stats

    def coletar_contratacoes(self, inicio: date, fim: date, resumo: ResumoColeta) -> None:
        for a, b in janelas(inicio, fim, self.janela_dias):
            def corpo(stats: Estatisticas, a=a, b=b) -> None:
                for modalidade in self.modalidades:
                    _processar(
                        self.cliente.contratacoes_publicacao(a, b, modalidade, codigo_ibge=self.codigo_ibge),
                        normalizar_contratacao, self.sink.salvar_licitacao, stats,
                        self._aceitar_contratacao, lambda l: resumo.cnpjs_orgaos.add(l.orgao.cnpj),
                    )

            s = self._executar(COLETOR_CONTRATACOES, a, b,
                               {"codigo_ibge": self.codigo_ibge, "modalidades": list(self.modalidades)}, corpo)
            _somar(resumo.contratacoes, s)

    def coletar_contratos(self, inicio: date, fim: date, cnpjs: Iterable[str], resumo: ResumoColeta) -> None:
        cnpjs = sorted(set(cnpjs))
        for a, b in janelas(inicio, fim, self.janela_dias):
            def corpo(stats: Estatisticas, a=a, b=b) -> None:
                for cnpj in cnpjs:
                    _processar(self.cliente.contratos(a, b, cnpj_orgao=cnpj), normalizar_contrato,
                               self.sink.salvar_contrato, stats, self._aceitar_contrato)

            s = self._executar(COLETOR_CONTRATOS, a, b, {"cnpjs_orgaos": cnpjs}, corpo)
            _somar(resumo.contratos, s)

    def coletar(self, inicio: date, fim: date, incluir_contratos: bool = True) -> ResumoColeta:
        resumo = ResumoColeta()
        resumo.cnpjs_orgaos |= self.cnpjs_configurados
        self.coletar_contratacoes(inicio, fim, resumo)
        if incluir_contratos:
            self.coletar_contratos(inicio, fim, resumo.cnpjs_orgaos, resumo)
        resumo.requisicoes = self.cliente.requisicoes
        return resumo

    def coletar_propostas_abertas(self, ate: date) -> Estatisticas:
        """Radar: compras do município com recebimento de propostas aberto até `ate`."""
        hoje = date.today()

        def corpo(stats: Estatisticas) -> None:
            _processar(self.cliente.contratacoes_proposta(ate, codigo_ibge=self.codigo_ibge),
                       normalizar_contratacao, self.sink.salvar_licitacao, stats, self._aceitar_contratacao)

        return self._executar("pncp.propostas_abertas", hoje, ate, {"codigo_ibge": self.codigo_ibge}, corpo)

    def coletar_itens(self, limite: int = 500, minutos: float | None = None) -> Estatisticas:
        """Itens e resultados das compras pendentes (nunca coletadas ou atualizadas na fonte depois da última
        coleta). `minutos` limita a duração: o que sobrar fica para a próxima execução.

        `lidos` conta compras; `resultados` conta itens. Erro de rede/limite derruba a execução (falha fechada);
        erro de normalização ou gravação de uma compra só conta em `erros`.
        """
        prazo = time.monotonic() + minutos * 60 if minutos else None
        hoje = date.today()

        def corpo(stats: Estatisticas) -> None:
            for alvo in self.sink.licitacoes_sem_itens(limite):
                if prazo is not None and time.monotonic() >= prazo:
                    log.info("itens: tempo esgotado após %d compras; o restante fica para a próxima execução",
                             stats.lidos)
                    return
                stats.lidos += 1
                cnpj, ano, seq = alvo["cnpj"], alvo["ano"], alvo["sequencial"]
                try:
                    brutos = self.cliente.itens_compra(cnpj, ano, seq)
                except requests.HTTPError as exc:
                    if exc.response is None or exc.response.status_code != 404:
                        raise
                    brutos = []  # compra removida do PNCP: marca como coletada para não travar a fila
                try:
                    itens = [normalizar_item(r, self.cliente.resultados_item(cnpj, ano, seq, r["numeroItem"])
                                             if r.get("temResultado") else None) for r in brutos]
                except (ValidationError, KeyError, ValueError) as exc:
                    stats.erros += 1
                    log.warning("itens de %s inválidos: %s", alvo["id_pncp"], exc)
                    continue
                try:
                    stats.resultados.update(self.sink.salvar_itens(alvo["id_pncp"], itens))
                except Exception as exc:  # noqa: BLE001 - erro de gravação de uma compra não derruba a coleta
                    stats.erros += 1
                    log.error("falha ao gravar itens de %s: %s", alvo["id_pncp"], exc)

        return self._executar(COLETOR_ITENS, hoje, hoje, {"limite": limite, "minutos": minutos}, corpo)

    def inicio_incremental(self, padrao: date) -> date:
        """Retoma da última janela com sucesso (com sobreposição) ou usa `padrao`."""
        ultimo = self.sink.ultima_janela(COLETOR_CONTRATACOES)
        return max(padrao, ultimo - SOBREPOSICAO_INCREMENTAL) if ultimo else padrao


def _somar(total: Estatisticas, parcial: Estatisticas) -> None:
    total.lidos += parcial.lidos
    total.erros += parcial.erros
    total.descartados += parcial.descartados
    total.resultados.update(parcial.resultados)
