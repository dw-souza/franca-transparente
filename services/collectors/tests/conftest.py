"""Infra de teste: sessão `requests` com transporte falso (sem rede) e banco PostgreSQL descartável."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from requests.adapters import BaseAdapter

FIXTURES = Path(__file__).parent / "fixtures"
MIGRATIONS = Path(__file__).resolve().parents[3] / "database" / "migrations"

# Tabelas com dados de coleta; domínios semeados (modalidades) ficam.
TABELAS_DADOS = (
    "registros_brutos", "execucoes_coleta", "endpoints_mapeados", "alertas_disparos", "alertas",
    "diario_atos", "diarios_oficiais", "contratos", "licitacoes", "fornecedores", "orgaos",
)


def fixture(nome: str) -> dict:
    return json.loads((FIXTURES / nome).read_text(encoding="utf-8"))


class FakeAdapter(BaseAdapter):
    """Responde com `rota(method, path, params, body) -> (status, json|None)` e registra as chamadas."""

    def __init__(self, rota: Callable):
        super().__init__()
        self.rota = rota
        self.chamadas: list[dict] = []

    def send(self, request, **kwargs):
        partes = urlsplit(request.url)
        params = {k: v[0] for k, v in parse_qs(partes.query).items()}
        corpo = request.body.decode() if isinstance(request.body, bytes) else request.body
        self.chamadas.append({"metodo": request.method, "path": partes.path, "params": params, "corpo": corpo})
        status, dados = self.rota(request.method, partes.path, params, corpo)
        resp = requests.Response()
        resp.status_code = status
        resp.request = request
        resp.url = request.url
        if dados is None:
            resp._content = b""
        elif isinstance(dados, str):
            resp._content = dados.encode()
            resp.headers["Content-Type"] = "text/html"
        else:
            resp._content = json.dumps(dados).encode()
            resp.headers["Content-Type"] = "application/json; charset=utf-8"
        return resp

    def close(self):
        pass


@pytest.fixture
def sessao_fake():
    def _criar(rota: Callable) -> tuple[requests.Session, FakeAdapter]:
        s = requests.Session()
        adaptador = FakeAdapter(rota)
        s.mount("https://", adaptador)
        s.mount("http://", adaptador)
        return s, adaptador

    return _criar


@pytest.fixture
def rota_pncp():
    """Simula a API: modalidade 6 tem 2 páginas; demais modalidades → 204; contratos só para a Prefeitura."""

    def rota(metodo, path, params, corpo):
        if path.endswith("/v1/contratacoes/publicacao"):
            if params.get("codigoModalidadeContratacao") != "6":
                return 204, None
            return 200, fixture(f"contratacoes_p{params['pagina']}.json")
        if path.endswith("/v1/contratacoes/proposta"):
            return 200, fixture("contratacoes_p1.json") | {"totalPaginas": 1, "paginasRestantes": 0}
        if path.endswith("/v1/contratos"):
            if params.get("cnpjOrgao") == "47970769000104":
                return 200, fixture("contratos_p1.json")
            return 204, None
        # API "pncp": itens da compra 12/2026 (2 itens, o 1º com resultado); demais compras sem itens
        if m := re.search(r"/api/pncp/v1/orgaos/\d+/compras/(\d+)/(\d+)/itens(/quantidade|/(\d+)/resultados)?$", path):
            itens = fixture("itens_000012_2026.json") if (m[1], m[2]) == ("2026", "12") else []
            if m[3] == "/quantidade":
                return 200, len(itens)
            if m[4]:
                return 200, fixture("resultados_000012_2026_item1.json") if m[4] == "1" and itens else []
            pagina, tamanho = int(params["pagina"]), int(params["tamanhoPagina"])
            return 200, itens[(pagina - 1) * tamanho: pagina * tamanho]
        return 404, {"erro": "rota desconhecida"}

    return rota


# ------------------------------------------------------------------ PostgreSQL (integração)
def _migrar(conn, sentido: str) -> None:
    arquivos = sorted(MIGRATIONS.glob(f"*.{sentido}.sql"), reverse=sentido == "down")
    assert arquivos, f"nenhuma migration em {MIGRATIONS}"
    for arq in arquivos:
        conn.execute(arq.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def banco_teste():
    """Cria um banco próprio no servidor de TEST_DATABASE_URL/DATABASE_URL e o apaga no fim.

    As migrations rodam up → down → up, o que também valida os .down.sql. Sem servidor, pula.
    """
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL ou DATABASE_URL para os testes de integração")
    try:
        admin = psycopg.connect(url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL indisponível: {exc}")

    nome = sql.Identifier(f"franca_teste_{os.getpid()}")
    admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(nome))
    admin.execute(sql.SQL("CREATE DATABASE {}").format(nome))
    url_teste = make_conninfo(url, dbname=f"franca_teste_{os.getpid()}")
    with psycopg.connect(url_teste, autocommit=True) as conn:
        for sentido in ("up", "down", "up"):
            _migrar(conn, sentido)
    try:
        yield url_teste
    finally:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(nome))
        admin.close()


@pytest.fixture
def pg(banco_teste):
    """Conexão para inspeção, com as tabelas de dados zeradas antes de cada teste."""
    import psycopg

    with psycopg.connect(banco_teste, autocommit=True) as conn:
        conn.execute(f"TRUNCATE {', '.join(TABELAS_DADOS)} RESTART IDENTITY CASCADE")
        yield conn


@pytest.fixture
def sink_pg(banco_teste, pg):
    from franca_collectors.storage.postgres import PostgresSink

    with PostgresSink(banco_teste) as sink:
        yield sink
