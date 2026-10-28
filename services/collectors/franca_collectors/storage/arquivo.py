"""Destinos sem banco: console (inspeção humana), JSON Lines (pipelines/arquivo) e memória (testes)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Any

from franca_collectors.models import Contrato, Licitacao, RegistroBruto
from franca_collectors.storage.base import Resultado, Sink


def _brl(valor) -> str:
    if valor is None:
        return "—"
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class ConsoleSink(Sink):
    nome = "console"

    def __init__(self, saida: IO[str] | None = None):
        self.saida = saida or sys.stdout
        self._vistos: set[str] = set()

    def _linha(self, chave: str, texto: str) -> Resultado:
        if chave in self._vistos:
            return "inalterado"
        self._vistos.add(chave)
        print(texto, file=self.saida)
        return "inserido"

    def salvar_licitacao(self, l: Licitacao) -> Resultado:
        quando = l.data_publicacao.strftime("%d/%m/%Y") if l.data_publicacao else "—"
        return self._linha(
            l.id_pncp,
            f"[LICITAÇÃO] {quando} · {l.modalidade_nome or '?'} · {l.status}\n"
            f"  {l.id_pncp} · {l.orgao.razao_social} / {l.unidade_nome or '—'}\n"
            f"  {l.objeto[:160]}\n  estimado: {_brl(l.valor_estimado)}",
        )

    def salvar_contrato(self, c: Contrato) -> Resultado:
        quando = c.data_assinatura.strftime("%d/%m/%Y") if c.data_assinatura else "—"
        return self._linha(
            c.id_pncp,
            f"[CONTRATO]  {quando} · {c.tipo_contrato or 'Contrato'} · {_brl(c.valor_total)}\n"
            f"  {c.id_pncp} · fornecedor {c.fornecedor.razao_social} ({c.fornecedor.cnpj_cpf})\n"
            f"  {c.objeto[:160]}",
        )

    def salvar_registro_bruto(self, r: RegistroBruto, execucao_id: int | None = None) -> Resultado:
        return self._linha(f"{r.endpoint_id}:{r.chave}", f"[{r.endpoint_id}] {r.chave} {r.mapeado or r.payload}")


class JsonlSink(Sink):
    """Uma linha JSON por registro: {"tipo": ..., "dados": {...}}."""

    nome = "jsonl"

    def __init__(self, caminho: str | Path, incluir_bruto: bool = False):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._f = self.caminho.open("a", encoding="utf-8")
        self._excluir = None if incluir_bruto else {"payload_bruto"}

    def _gravar(self, tipo: str, dados: dict[str, Any]) -> Resultado:
        self._f.write(json.dumps({"tipo": tipo, "dados": dados}, ensure_ascii=False, default=str) + "\n")
        return "inserido"

    def salvar_licitacao(self, l: Licitacao) -> Resultado:
        return self._gravar("licitacao", l.model_dump(mode="json", exclude=self._excluir))

    def salvar_contrato(self, c: Contrato) -> Resultado:
        return self._gravar("contrato", c.model_dump(mode="json", exclude=self._excluir))

    def salvar_registro_bruto(self, r: RegistroBruto, execucao_id: int | None = None) -> Resultado:
        return self._gravar("registro_bruto", r.model_dump(mode="json"))

    def close(self) -> None:
        self._f.close()


class MemoriaSink(Sink):
    """Guarda tudo em dicionários; deduplica por id como o banco faria."""

    nome = "memoria"

    def __init__(self):
        self.licitacoes: dict[str, Licitacao] = {}
        self.contratos: dict[str, Contrato] = {}
        self.brutos: dict[tuple[str, str], RegistroBruto] = {}
        self.execucoes: list[dict[str, Any]] = []

    @staticmethod
    def _upsert(tabela: dict, chave, novo) -> Resultado:
        antigo = tabela.get(chave)
        tabela[chave] = novo
        if antigo is None:
            return "inserido"
        return "inalterado" if antigo.payload_hash == novo.payload_hash else "atualizado"

    def salvar_licitacao(self, l: Licitacao) -> Resultado:
        return self._upsert(self.licitacoes, l.id_pncp, l)

    def salvar_contrato(self, c: Contrato) -> Resultado:
        return self._upsert(self.contratos, c.id_pncp, c)

    def salvar_registro_bruto(self, r: RegistroBruto, execucao_id: int | None = None) -> Resultado:
        return self._upsert(self.brutos, (r.endpoint_id, r.chave), r)

    def iniciar_execucao(self, coletor, parametros, janela_inicio=None, janela_fim=None, endpoint_id=None):
        self.execucoes.append({"coletor": coletor, "parametros": parametros, "status": "executando",
                               "janela_inicio": janela_inicio, "janela_fim": janela_fim})
        return len(self.execucoes)

    def finalizar_execucao(self, execucao_id, status, lidos, gravados, erros, erro=None):
        self.execucoes[execucao_id - 1].update(status=status, lidos=lidos, gravados=gravados,
                                               erros=erros, erro=erro)

    def ultima_janela(self, coletor):
        fins = [e["janela_fim"] for e in self.execucoes
                if e["coletor"] == coletor and e["status"] == "sucesso" and e["janela_fim"]]
        return max(fins) if fins else None
