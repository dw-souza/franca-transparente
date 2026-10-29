"""Itens e resultados das contratações (API pncp): normalização, paginação e gravação no Postgres."""

from datetime import date
from decimal import Decimal

import pytest
from conftest import fixture

from franca_collectors.http import RespostaInvalida
from franca_collectors.pncp.client import PNCPClient
from franca_collectors.pncp.normalize import normalizar_item
from franca_collectors.pncp.pipeline import ColetorPNCP
from franca_collectors.storage import MemoriaSink

LIC_12 = "47970769000104-1-000012/2026"


def cliente(sessao):
    return PNCPClient(sessao, "https://pncp.gov.br/api/consulta", delay=0)


def coletor(sessao, sink):
    return ColetorPNCP(cliente(sessao), sink, "3516200", modalidades=(6,))


def test_normaliza_item_com_resultado():
    bruto = fixture("itens_000012_2026.json")[0]
    item = normalizar_item(bruto, fixture("resultados_000012_2026_item1.json"))
    assert item.numero_item == 1 and item.material_servico == "M" and item.situacao == "Homologado"
    assert item.valor_unitario_estimado == Decimal("0.49") and item.quantidade == Decimal("1650000.0")
    (r,) = item.resultados
    assert r.fornecedor.cnpj_cpf == "59225268000174" and r.valor_unitario_homologado == Decimal("0.48")
    assert r.data_resultado == date(2025, 10, 2) and r.porte_fornecedor == "Demais"


def test_itens_paginam_ate_completar_a_quantidade(sessao_fake, rota_pncp):
    s, fake = sessao_fake(rota_pncp)
    itens = cliente(s).itens_compra("47970769000104", 2026, 12, tamanho=1)
    assert [i["numeroItem"] for i in itens] == [1, 2]
    caminhos = [c["path"] for c in fake.chamadas]
    assert caminhos[0].startswith("/api/pncp/") and caminhos[0].endswith("/itens/quantidade")
    assert len(caminhos) == 3  # quantidade + 2 páginas de 1


def test_itens_faltando_falham_fechado(sessao_fake):
    def rota(metodo, path, params, corpo):
        return 200, (5 if path.endswith("/quantidade") else [] if params.get("pagina") == "2" else [{"numeroItem": 1}])

    s, _ = sessao_fake(rota)
    with pytest.raises(RespostaInvalida):
        cliente(s).itens_compra("47970769000104", 2026, 12, tamanho=1)


def test_coleta_de_itens_em_memoria(sessao_fake, rota_pncp):
    s, _ = sessao_fake(rota_pncp)
    sink = MemoriaSink()
    c = coletor(s, sink)
    c.coletar(date(2026, 10, 1), date(2026, 10, 27), incluir_contratos=False)
    stats = c.coletar_itens()
    assert stats.lidos == 3 and stats.erros == 0
    assert [i.numero_item for i in sink.itens[LIC_12]] == [1, 2]
    assert sink.itens[LIC_12][0].resultados[0].fornecedor.razao_social == "Soquimica Laboratórios Ltda"


# ------------------------------------------------------------------- Postgres
@pytest.mark.integracao
def test_itens_gravados_idempotentes_e_reabertos_quando_a_compra_muda(sessao_fake, rota_pncp, sink_pg, pg):
    s, _ = sessao_fake(rota_pncp)
    c = coletor(s, sink_pg)
    c.coletar(date(2026, 10, 1), date(2026, 10, 27), incluir_contratos=False)

    primeira = c.coletar_itens()
    assert primeira.lidos == 3 and dict(primeira.resultados) == {"inserido": 2}
    assert sink_pg.licitacoes_sem_itens(10) == []
    linhas = pg.execute("SELECT numero_item, situacao, valor_unitario_estimado FROM licitacao_itens "
                        "ORDER BY numero_item").fetchall()
    assert linhas == [(1, "Homologado", Decimal("0.4900")), (2, "Deserto", Decimal("0.1234"))]
    preco = pg.execute("SELECT valor_unitario_homologado, fornecedor, tipo_pessoa FROM vw_precos_itens "
                       "WHERE numero_item = 1").fetchone()
    assert preco == (Decimal("0.4800"), "Soquimica Laboratórios Ltda", "PJ")

    # Fila vazia: nada a fazer
    assert c.coletar_itens().lidos == 0

    # A compra é atualizada na fonte depois da coleta de itens: volta para a fila; itens iguais não reescrevem
    pg.execute("UPDATE licitacoes SET data_atualizacao_fonte = now() + interval '1 minute' WHERE id_pncp = %s",
               (LIC_12,))
    assert [a["id_pncp"] for a in sink_pg.licitacoes_sem_itens(10)] == [LIC_12]
    segunda = c.coletar_itens()
    assert segunda.lidos == 1 and dict(segunda.resultados) == {"inalterado": 2}
    assert pg.execute("SELECT count(*) FROM licitacao_item_resultados").fetchone()[0] == 1


@pytest.mark.integracao
def test_compra_removida_do_pncp_nao_trava_a_fila(sessao_fake, rota_pncp, sink_pg, pg):
    def rota(metodo, path, params, corpo):
        if "/api/pncp/" in path:
            return 404, {"message": "Compra não encontrada"}
        return rota_pncp(metodo, path, params, corpo)

    s, _ = sessao_fake(rota)
    c = coletor(s, sink_pg)
    c.coletar(date(2026, 10, 1), date(2026, 10, 27), incluir_contratos=False)
    assert c.coletar_itens().erros == 0
    assert sink_pg.licitacoes_sem_itens(10) == []
    assert pg.execute("SELECT count(*) FROM licitacao_itens").fetchone()[0] == 0


@pytest.mark.integracao
def test_limite_e_prazo(sessao_fake, rota_pncp, sink_pg):
    s, _ = sessao_fake(rota_pncp)
    c = coletor(s, sink_pg)
    c.coletar(date(2026, 10, 1), date(2026, 10, 27), incluir_contratos=False)
    assert c.coletar_itens(limite=1).lidos == 1
    assert c.coletar_itens(minutos=0.000001).lidos == 0  # prazo já esgotado antes da primeira compra
    assert len(sink_pg.licitacoes_sem_itens(10)) == 2
