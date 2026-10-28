import json
from datetime import date

import pytest
import yaml
from test_rea import _har

from franca_collectors import cli
from franca_collectors.config import ENDPOINTS_DIR_PADRAO
from franca_collectors.rea.spec import carregar_specs


@pytest.fixture
def ambiente(monkeypatch):
    """Configuração previsível, independente do .env de quem roda os testes."""
    for var in ("DATABASE_URL", "ENDPOINTS_DIR", "PNCP_BASE_URL", "CODIGO_IBGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ORGAOS_CNPJ", "47970769000104")
    monkeypatch.setenv("PNCP_MODALIDADES", "6")
    monkeypatch.setenv("HTTP_DELAY_SEGUNDOS", "0")
    return monkeypatch


@pytest.fixture
def pncp_fake(ambiente, sessao_fake):
    """Troca a sessão HTTP real pela falsa; devolve uma função para escolher a rota."""

    def _usar(rota):
        sessao, adaptador = sessao_fake(rota)
        ambiente.setattr(cli, "criar_sessao", lambda *a, **k: sessao)
        return adaptador

    return _usar


def _linhas_jsonl(caminho):
    return [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------------ pncp
def test_pncp_coletar_jsonl(pncp_fake, rota_pncp, tmp_path, capsys):
    pncp_fake(rota_pncp)
    saida = tmp_path / "coleta.jsonl"
    rc = cli.main(["pncp", "coletar", "--desde", "2026-10-01", "--ate", "2026-10-27",
                   "--saida", "jsonl", "--arquivo", str(saida)])
    assert rc == 0
    tipos = [r["tipo"] for r in _linhas_jsonl(saida)]
    assert tipos.count("licitacao") == 3 and tipos.count("contrato") == 3
    assert "payload_bruto" not in _linhas_jsonl(saida)[0]["dados"]
    err = capsys.readouterr().err
    assert "PNCP 3516200 2026-10-01 → 2026-10-27" in err and "órgãos (CNPJ): 47970769000104" in err


def test_pncp_coletar_respeita_modalidades_e_sem_contratos(pncp_fake, rota_pncp, capsys):
    adaptador = pncp_fake(rota_pncp)
    assert cli.main(["pncp", "coletar", "--desde", "2026-10-01", "--ate", "2026-10-27",
                     "--modalidades", "8,9", "--sem-contratos"]) == 0
    assert {c["params"]["codigoModalidadeContratacao"] for c in adaptador.chamadas} == {"8", "9"}
    assert not any(c["path"].endswith("/v1/contratos") for c in adaptador.chamadas)


def test_pncp_coletar_devolve_1_quando_ha_erros(pncp_fake):
    ruim = {"data": [{"numeroControlePNCP": "x"}], "totalPaginas": 1, "paginasRestantes": 0}
    pncp_fake(lambda *a: (200, ruim))
    assert cli.main(["pncp", "coletar", "--desde", "2026-10-01", "--ate", "2026-10-02", "--sem-contratos"]) == 1


def test_pncp_abertas_console(pncp_fake, rota_pncp, capsys):
    adaptador = pncp_fake(rota_pncp)
    assert cli.main(["pncp", "abertas", "--dias", "30"]) == 0
    assert all(c["path"].endswith("/v1/contratacoes/proposta") for c in adaptador.chamadas)
    out = capsys.readouterr()
    assert "[LICITAÇÃO]" in out.out and "Propostas abertas" in out.err


def test_saida_postgres_sem_database_url_aborta(pncp_fake, rota_pncp):
    pncp_fake(rota_pncp)
    with pytest.raises(SystemExit, match="DATABASE_URL"):
        cli.main(["pncp", "coletar", "--saida", "postgres"])


# ------------------------------------------------------------------------- rea
def test_rea_listar_esconde_modelos_e_validar_inclui(ambiente, capsys):
    assert cli.main(["rea", "listar"]) == 0
    listados = capsys.readouterr().out
    assert "transparencia.despesas.empenhos" in listados and "exemplo." not in listados

    assert cli.main(["rea", "validar"]) == 0
    assert "exemplo.despesas.empenhos" in capsys.readouterr().out


@pytest.mark.parametrize(("args", "mensagem"), [
    (["rea", "executar", "nao.existe"], "endpoint não encontrado"),
    (["rea", "executar", "transparencia.despesas.empenhos"], "está inativo"),
])
def test_rea_executar_recusa_endpoint_invalido(ambiente, capsys, args, mensagem):
    assert cli.main(args) == 2
    assert mensagem in capsys.readouterr().err


def test_rea_har_gera_rascunhos_validos(ambiente, tmp_path, capsys):
    rascunho = tmp_path / "rascunho.yaml"
    assert cli.main(["rea", "har", str(_har(tmp_path)), "--host", "transparencia.exemplo.gov.br",
                     "--yaml", str(rascunho)]) == 0
    assert "/api/licitacoes/pesquisar" in capsys.readouterr().out
    endpoints = yaml.safe_load(rascunho.read_text(encoding="utf-8"))["endpoints"]
    assert len(endpoints) == 2 and all(e["status"] == "a_mapear" for e in endpoints)


# ------------------------------------------------------------------- postgres
@pytest.mark.integracao
def test_rea_sincronizar_e_coleta_incremental_no_postgres(ambiente, pncp_fake, rota_pncp, banco_teste, pg):
    ambiente.setenv("DATABASE_URL", banco_teste)
    pncp_fake(rota_pncp)

    assert cli.main(["rea", "sincronizar"]) == 0
    assert pg.execute("SELECT count(*) FROM endpoints_mapeados").fetchone()[0] == \
        len(carregar_specs(ENDPOINTS_DIR_PADRAO))

    args = ["pncp", "coletar", "--desde", "2026-10-01", "--ate", "2026-10-27", "--saida", "postgres"]
    assert cli.main(args) == 0
    assert cli.main([*args, "--incremental"]) == 0
    janelas = pg.execute("SELECT janela_inicio FROM execucoes_coleta WHERE coletor = 'pncp.contratacoes' "
                         "ORDER BY id").fetchall()
    assert [j[0] for j in janelas] == [date(2026, 10, 1), date(2026, 10, 24)]
    assert pg.execute("SELECT count(*) FROM licitacoes").fetchone()[0] == 3
