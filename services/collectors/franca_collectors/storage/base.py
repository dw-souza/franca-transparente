"""Contrato comum dos destinos de gravação ("sinks")."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from franca_collectors.models import Contrato, Licitacao, LicitacaoItem, RegistroBruto

Resultado = Literal["inserido", "atualizado", "inalterado", "ignorado"]


class Sink:
    """Implementação no-op; destinos concretos sobrescrevem o que suportam."""

    nome = "base"

    def salvar_licitacao(self, licitacao: Licitacao) -> Resultado:
        raise NotImplementedError

    def salvar_contrato(self, contrato: Contrato) -> Resultado:
        raise NotImplementedError

    def salvar_registro_bruto(self, registro: RegistroBruto, execucao_id: int | None = None) -> Resultado:
        raise NotImplementedError

    def licitacoes_sem_itens(self, limite: int) -> list[dict[str, Any]]:
        """Fila da coleta de itens: compras nunca coletadas ou atualizadas na fonte depois da última coleta.

        Cada item: {"id_pncp", "cnpj", "ano", "sequencial"}.
        """
        raise NotImplementedError

    def salvar_itens(self, id_pncp: str, itens: list[LicitacaoItem]) -> dict[str, int]:
        """Grava itens e resultados de uma compra e marca a compra como coletada. Devolve contagens por resultado."""
        raise NotImplementedError

    def sincronizar_endpoint(self, spec: dict[str, Any], spec_sha256: str) -> None:
        """Espelha um endpoint do registro REA (YAML) no banco. Sem efeito fora do Postgres."""

    def iniciar_execucao(
        self,
        coletor: str,
        parametros: dict[str, Any],
        janela_inicio: date | None = None,
        janela_fim: date | None = None,
        endpoint_id: str | None = None,
    ) -> int | None:
        return None

    def finalizar_execucao(
        self,
        execucao_id: int | None,
        status: str,
        lidos: int,
        gravados: int,
        erros: int,
        erro: str | None = None,
    ) -> None:
        return None

    def ultima_janela(self, coletor: str) -> date | None:
        """Fim da última janela coletada com sucesso (cursor da coleta incremental)."""
        return None

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
