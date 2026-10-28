from datetime import date, datetime
from decimal import Decimal
from itertools import pairwise

import pytest
import requests
from conftest import fixture

from franca_collectors.http import RespostaInvalida
from franca_collectors.normalizacao import FUSO_BRASILIA
from franca_collectors.pncp.client import PNCPClient, janelas
from franca_collectors.pncp.normalize import normalizar_contratacao, normalizar_contrato
from franca_collectors.pncp.pipeline import COLETOR_CONTRATACOES, ColetorPNCP
from franca_collectors.storage import MemoriaSink

IBGE = "3516200"


def cliente(sessao):
    return PNCPClient(sessao, "https://pncp.gov.br/api/consulta", delay=0)


# ------------------------------------------------------------------------ cliente
def test_janelas_cobrem_o_periodo_sem_sobreposicao():
    js = list(janelas(date(2026, 1, 1), date(2026, 3, 15), 30))
    assert js[0] == (date(2026, 1, 1), date(2026, 1, 30))
    assert js[-1][1] == date(2026, 3, 15)
    assert all(b < a2 for (_, b), (a2, _) in pairwise(js))


def test_paginacao_e_parametros(sessao_fake, rota_pncp):
    s, fake = sessao_fake(rota_pncp)
    regs = list(cliente(s).contratacoes_publicacao(date(2026, 10, 1), date(2026, 10, 27), 6, codigo_ibge=IBGE))
    assert len(regs) == 4
    assert [c["params"]["pagina"] for c in fake.chamadas] == ["1", "2"]
    p = fake.chamadas[0]["params"]
    assert p["dataInicial"] == "20261001" and p["dataFinal"] == "20261027"
    assert p["codigoMunicipioIbge"] == IBGE and p["tamanhoPagina"] == "50"
    assert "cnpj" not in p  # None não vai para a query


def test_204_significa_sem_resultados(sessao_fake, rota_pncp):
    s, _ = sessao_fake(rota_pncp)
    assert list(cliente(s).contratacoes_publicacao(date(2026, 10, 1), date(2026, 10, 2), 8)) == []


@pytest.mark.parametrize("status", [429, 503])
def test_erro_sem_corpo_nao_vira_sem_resultados(sessao_fake, status):
    s, _ = sessao_fake(lambda *a: (status, None))
    with pytest.raises(requests.HTTPError):
        list(cliente(s).contratacoes_publicacao(date(2026, 10, 1), date(2026, 10, 2), 6))


def test_html_no_lugar_de_json_falha_fechado(sessao_fake):
    s, _ = sessao_fake(lambda *a: (200, "<html>desafio</html>"))
    with pytest.raises(RespostaInvalida):
        list(cliente(s).contratos(date(2026, 10, 1), date(2026, 10, 2), "47970769000104"))


# ------------------------------------------------------------------- normalização
def test_normaliza_contratacao():
    l = normalizar_contratacao(fixture("contratacoes_p1.json")["data"][0])
    assert l.id_pncp == "47970769000104-1-000012/2026"
    assert l.orgao.cnpj == "47970769000104" and l.orgao.esfera == "M"
    assert l.objeto == "Aquisição de medicamentos para a rede básica de saúde"  # espaços colapsados
    assert l.valor_estimado == Decimal("150000.50")
    assert l.data_abertura == datetime(2026, 10, 6, 8, 0, tzinfo=FUSO_BRASILIA)
    assert l.modalidade_id == 6 and l.srp is True and l.status == "Divulgada no PNCP"
    assert l.unidade_nome == "SECRETARIA MUNICIPAL DE SAUDE"
    assert l.amparo_legal.startswith("Lei 14.133")
    assert len(l.payload_hash) == 64 and l.payload_bruto["anoCompra"] == 2026


def test_normaliza_contratos_pj_alfanumerico_e_pf():
    pj, alfa, pf = (normalizar_contrato(r) for r in fixture("contratos_p1.json")["data"])
    assert pj.fornecedor.cnpj_cpf == "12345678000195"
    assert pj.id_pncp_compra == "47970769000104-1-000012/2026"
    assert pj.valor_total == Decimal("120000.00") and pj.vigencia_fim == date(2027, 10, 14)
    assert pj.tipo_contrato == "Contrato (termo inicial)" and pj.categoria_processo == "Compras"
    assert alfa.fornecedor.cnpj_cpf == "12ABC34501DE35"  # CNPJ alfanumérico (2026+)
    assert pf.fornecedor.tipo_pessoa == "PF" and pf.fornecedor.cnpj_cpf == "12345678909"


def test_valor_string_vira_decimal_exato():
    l = normalizar_contratacao(fixture("contratacoes_p2.json")["data"][0])
    assert l.valor_estimado == Decimal("98765.43") and l.status == "Revogada"


# ----------------------------------------------------------------------- pipeline
def test_pipeline_completo(sessao_fake, rota_pncp):
    s, fake = sessao_fake(rota_pncp)
    sink = MemoriaSink()
    coletor = ColetorPNCP(cliente(s), sink, IBGE, cnpjs_orgaos=(), modalidades=(6, 8))
    resumo = coletor.coletar(date(2026, 10, 1), date(2026, 10, 27))

    assert set(sink.licitacoes) == {f"47970769000104-1-{n:06d}/2026" for n in (12, 13, 14)}
    assert resumo.contratacoes.descartados == 1           # unidade estadual sediada em Franca
    assert resumo.cnpjs_orgaos == {"47970769000104"}      # descoberto, não configurado
    assert len(sink.contratos) == 3
    assert [e["status"] for e in sink.execucoes] == ["sucesso", "sucesso"]
    assert any(c["path"].endswith("/v1/contratos") for c in fake.chamadas)

    # Reexecução é idempotente
    resumo2 = coletor.coletar(date(2026, 10, 1), date(2026, 10, 27))
    assert resumo2.contratacoes.resultados["inalterado"] == 3
    assert resumo2.contratacoes.resultados["inserido"] == 0


def test_todas_esferas_inclui_unidade_estadual(sessao_fake, rota_pncp):
    s, _ = sessao_fake(rota_pncp)
    sink = MemoriaSink()
    ColetorPNCP(cliente(s), sink, IBGE, modalidades=(6,), esferas=None).coletar(
        date(2026, 10, 1), date(2026, 10, 27), incluir_contratos=False)
    assert len(sink.licitacoes) == 4


def test_incremental_retoma_com_sobreposicao(sessao_fake, rota_pncp):
    s, _ = sessao_fake(rota_pncp)
    sink = MemoriaSink()
    coletor = ColetorPNCP(cliente(s), sink, IBGE, modalidades=(6,))
    assert coletor.inicio_incremental(date(2026, 1, 1)) == date(2026, 1, 1)
    sink.execucoes.append({"coletor": COLETOR_CONTRATACOES, "status": "sucesso", "janela_fim": date(2026, 10, 20)})
    assert coletor.inicio_incremental(date(2026, 1, 1)) == date(2026, 10, 17)


def test_registro_invalido_nao_derruba_coleta(sessao_fake):
    ruim = {"data": [{"numeroControlePNCP": "x"}, fixture("contratacoes_p1.json")["data"][0]],
            "totalPaginas": 1, "paginasRestantes": 0}
    s, _ = sessao_fake(lambda *a: (200, ruim))
    sink = MemoriaSink()
    resumo = ColetorPNCP(cliente(s), sink, IBGE, modalidades=(6,)).coletar(
        date(2026, 10, 1), date(2026, 10, 2), incluir_contratos=False)
    assert resumo.contratacoes.erros == 1 and len(sink.licitacoes) == 1
    assert sink.execucoes[0]["status"] == "parcial"
