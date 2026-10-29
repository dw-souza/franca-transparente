"""Integração com PostgreSQL: sink, triggers, busca textual e views das migrations.

Rodam num banco descartável (fixture `banco_teste`) e são pulados sem servidor disponível.
"""

import copy
from datetime import date, datetime, timedelta

import pytest
from conftest import fixture

from franca_collectors.config import ENDPOINTS_DIR_PADRAO
from franca_collectors.models import RegistroBruto
from franca_collectors.normalizacao import FUSO_BRASILIA
from franca_collectors.pncp.client import PNCPClient
from franca_collectors.pncp.normalize import normalizar_contratacao, normalizar_contrato
from franca_collectors.pncp.pipeline import ColetorPNCP
from franca_collectors.rea.spec import carregar_specs
from franca_collectors.storage.postgres import PostgresSink

pytestmark = pytest.mark.integracao

LIC_12 = "47970769000104-1-000012/2026"  # compra de medicamentos; o contrato 0 aponta para ela
CONTRATO_0 = "47970769000104-2-000005/2026"


def contratacao(i: int = 0, arquivo: str = "contratacoes_p1.json", **campos_pncp):
    bruto = copy.deepcopy(fixture(arquivo)["data"][i]) | campos_pncp
    return normalizar_contratacao(bruto)


def contrato(i: int = 0, **campos_pncp):
    bruto = copy.deepcopy(fixture("contratos_p1.json")["data"][i]) | campos_pncp
    return normalizar_contrato(bruto)


def _pncp_data_hora(dias: int) -> str:
    return (datetime.now(FUSO_BRASILIA) + timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S")


def _um(pg, sql: str, params=None):
    return pg.execute(sql, params).fetchone()


# ------------------------------------------------------------------------ schema
def test_migrations_up_down_up_deixam_schema_completo(pg):
    tabelas = {r[0] for r in pg.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert {"orgaos", "fornecedores", "licitacoes", "contratos", "diarios_oficiais", "diario_atos", "alertas",
            "alertas_disparos", "endpoints_mapeados", "execucoes_coleta", "registros_brutos"} <= tabelas
    views = {r[0] for r in pg.execute("SELECT viewname FROM pg_views WHERE schemaname = 'public'")}
    assert {"vw_painel_resumo", "vw_licitacoes_abertas", "vw_contratado_por_fornecedor",
            "vw_contratado_por_unidade", "vw_licitacoes_por_modalidade"} <= views
    assert _um(pg, "SELECT count(*) FROM modalidades_contratacao")[0] >= 13
    assert _um(pg, "SELECT normalizar_documento('12.ABC.345/01de-35')")[0] == "12ABC34501DE35"


# ------------------------------------------------------------------------ upsert
def test_licitacao_upsert_idempotente(sink_pg, pg, banco_teste):
    assert sink_pg.salvar_licitacao(contratacao()) == "inserido"
    assert sink_pg.salvar_licitacao(contratacao()) == "inalterado"
    with PostgresSink(banco_teste) as outro:  # sem cache de ids: o banco decide sozinho
        assert outro.salvar_licitacao(contratacao()) == "inalterado"
    assert sink_pg.salvar_licitacao(contratacao(situacaoCompraNome="Suspensa")) == "atualizado"

    status, bruto, total = _um(pg, "SELECT status, payload_bruto->>'situacaoCompraNome', count(*) OVER () "
                                   "FROM licitacoes")
    assert (status, bruto, total) == ("Suspensa", "Suspensa", 1)
    assert _um(pg, "SELECT count(*) FROM orgaos")[0] == 1


def test_resumo_ia_so_e_invalidado_quando_objeto_muda(sink_pg, pg):
    sink_pg.salvar_licitacao(contratacao())
    pg.execute("UPDATE licitacoes SET resumo_ia = 'resumo', resumo_ia_modelo = 'm', resumo_ia_em = now()")

    sink_pg.salvar_licitacao(contratacao(situacaoCompraNome="Suspensa"))
    assert _um(pg, "SELECT resumo_ia FROM licitacoes")[0] == "resumo"

    sink_pg.salvar_licitacao(contratacao(objetoCompra="Aquisição de vacinas"))
    assert _um(pg, "SELECT resumo_ia, resumo_ia_modelo, resumo_ia_em FROM licitacoes") == (None, None, None)


@pytest.mark.parametrize("contrato_primeiro", [True, False], ids=["contrato-antes", "licitacao-antes"])
def test_vinculo_contrato_licitacao_em_qualquer_ordem(sink_pg, pg, contrato_primeiro):
    if contrato_primeiro:
        sink_pg.salvar_contrato(contrato())
        assert _um(pg, "SELECT licitacao_id FROM contratos")[0] is None
        sink_pg.salvar_licitacao(contratacao())
    else:
        sink_pg.salvar_licitacao(contratacao())
        sink_pg.salvar_contrato(contrato())

    vinculo, esperado = _um(pg, "SELECT c.licitacao_id, l.id FROM contratos c, licitacoes l "
                                "WHERE c.id_pncp = %s AND l.id_pncp = %s", (CONTRATO_0, LIC_12))
    assert vinculo == esperado


def test_documentos_pj_alfanumerico_e_pf(sink_pg, pg):
    for i in range(3):
        assert sink_pg.salvar_contrato(contrato(i)) == "inserido"
    linhas = {r[0]: r[1:] for r in pg.execute("SELECT cnpj_cpf, tipo_pessoa, cnpj_raiz FROM fornecedores")}
    assert linhas == {"12345678000195": ("PJ", "12345678"), "12ABC34501DE35": ("PJ", "12ABC345"),
                      "12345678909": ("PF", None)}


def test_razao_social_da_receita_prevalece_sobre_o_pncp(banco_teste, pg):
    with PostgresSink(banco_teste) as sink:
        sink.salvar_contrato(contrato())
    with PostgresSink(banco_teste) as sink:
        sink.salvar_contrato(contrato(nomeRazaoSocialFornecedor="NOME NOVO NO PNCP"))
    assert _um(pg, "SELECT razao_social FROM fornecedores")[0] == "NOME NOVO NO PNCP"

    pg.execute("UPDATE fornecedores SET razao_social = 'NOME DA RECEITA', enriquecido_em = now()")
    with PostgresSink(banco_teste) as sink:
        sink.salvar_contrato(contrato(nomeRazaoSocialFornecedor="OUTRO NOME NO PNCP"))
    assert _um(pg, "SELECT razao_social FROM fornecedores")[0] == "NOME DA RECEITA"


def test_falha_de_um_registro_nao_envenena_os_seguintes(sink_pg, pg):
    import psycopg

    # Primeiro registro do órgão viola um CHECK (CNPJ inválido do fornecedor): o órgão criado na mesma
    # transação é desfeito e não pode continuar no cache de ids.
    with pytest.raises(psycopg.errors.CheckViolation):
        sink_pg.salvar_contrato(contrato(niFornecedor="123"))
    assert _um(pg, "SELECT count(*) FROM orgaos")[0] == 0

    assert sink_pg.salvar_licitacao(contratacao(1)) == "inserido"
    assert sink_pg.salvar_contrato(contrato()) == "inserido"


def test_valor_negativo_da_fonte_e_gravado(sink_pg, pg):
    assert sink_pg.salvar_licitacao(contratacao(valorTotalEstimado=-36)) == "inserido"
    assert _um(pg, "SELECT valor_estimado FROM licitacoes")[0] == -36


# --------------------------------------------------------------- coleta e REA
def test_execucoes_e_cursor_incremental(sink_pg, pg):
    assert sink_pg.ultima_janela("pncp.teste") is None
    ok = sink_pg.iniciar_execucao("pncp.teste", {"modalidades": [6]}, date(2026, 10, 1), date(2026, 10, 10))
    sink_pg.finalizar_execucao(ok, "sucesso", 5, 4, 0)
    falha = sink_pg.iniciar_execucao("pncp.teste", {}, date(2026, 10, 11), date(2026, 10, 20))
    sink_pg.finalizar_execucao(falha, "erro", 0, 0, 1, "fonte fora do ar")

    assert sink_pg.ultima_janela("pncp.teste") == date(2026, 10, 10)
    assert _um(pg, "SELECT status, registros_lidos, registros_gravados, finalizado_em IS NOT NULL, "
                   "parametros FROM execucoes_coleta WHERE id = %s", (ok,)) == \
        ("sucesso", 5, 4, True, {"modalidades": [6]})
    assert _um(pg, "SELECT erro FROM execucoes_coleta WHERE id = %s", (falha,))[0] == "fonte fora do ar"


def test_endpoint_rea_e_registros_brutos(sink_pg, pg):
    spec = next(s for s in carregar_specs(ENDPOINTS_DIR_PADRAO, incluir_modelos=True)
                if s.id == "exemplo.despesas.empenhos")
    for _ in range(2):
        sink_pg.sincronizar_endpoint(spec.model_dump(mode="json"), spec.sha256())
    assert _um(pg, "SELECT count(*), max(spec_sha256) FROM endpoints_mapeados") == (1, spec.sha256())

    execucao = sink_pg.iniciar_execucao(f"rea:{spec.id}", {}, endpoint_id=spec.id)
    r = RegistroBruto(endpoint_id=spec.id, chave="7|2026", payload={"numeroEmpenho": "7"},
                      mapeado={"valor_empenhado": 70.0}, payload_hash="a" * 64)
    assert sink_pg.salvar_registro_bruto(r, execucao) == "inserido"
    assert sink_pg.salvar_registro_bruto(r, execucao) == "inalterado"
    mudou = r.model_copy(update={"payload": {"numeroEmpenho": "7", "pago": 1}, "payload_hash": "b" * 64})
    assert sink_pg.salvar_registro_bruto(mudou, execucao) == "atualizado"
    assert _um(pg, "SELECT payload, mapeado, execucao_id FROM registros_brutos") == \
        ({"numeroEmpenho": "7", "pago": 1}, {"valor_empenhado": 70.0}, execucao)


# ---------------------------------------------------------- busca e painel
@pytest.mark.parametrize(("consulta", "esperado"), [
    ("medicamento basica", [LIC_12]),                     # sem acento e no singular
    ("pavimentacao asfaltica", ["47970769000104-1-000013/2026"]),
    ("vacina", []),
])
def test_busca_textual_portugues_sem_acento(sink_pg, pg, consulta, esperado):
    for i in range(2):
        sink_pg.salvar_licitacao(contratacao(i))
    ids = [r[0] for r in pg.execute(
        "SELECT id_pncp FROM licitacoes WHERE busca @@ websearch_to_tsquery('pt_unaccent', %s)", (consulta,))]
    assert ids == esperado


def test_views_do_painel(sink_pg, pg):
    sink_pg.salvar_licitacao(contratacao(0, dataEncerramentoProposta=_pncp_data_hora(10)))      # aberta
    sink_pg.salvar_licitacao(contratacao(1, dataEncerramentoProposta=_pncp_data_hora(-1)))      # encerrada
    sink_pg.salvar_licitacao(contratacao(0, "contratacoes_p2.json",
                                         dataEncerramentoProposta=_pncp_data_hora(10)))         # revogada
    hoje = date.today().isoformat()
    sink_pg.salvar_contrato(contrato(0, dataAssinatura=hoje))                  # 120.000,00
    sink_pg.salvar_contrato(contrato(1, dataAssinatura=hoje, receita=True))    # receita: fora das somas
    sink_pg.salvar_contrato(contrato(2, dataAssinatura=hoje))                  # 4.500,00

    assert [r[0] for r in pg.execute("SELECT id_pncp FROM vw_licitacoes_abertas")] == [LIC_12]

    resumo = _um(pg, "SELECT ano, total_contratado_ano, contratos_ano, licitacoes_abertas, fornecedores_ano "
                     "FROM vw_painel_resumo")
    assert resumo == (date.today().year, 124500, 3, 1, 3)

    por_fornecedor = dict(pg.execute("SELECT cnpj_cpf, valor_total FROM vw_contratado_por_fornecedor"))
    assert por_fornecedor == {"12345678000195": 120000, "12345678909": 4500}
    assert _um(pg, "SELECT sum(valor_total) FROM vw_contratado_por_unidade")[0] == 124500
    assert _um(pg, "SELECT sum(qtd) FROM vw_licitacoes_por_modalidade")[0] == 3


# ---------------------------------------------------------------- ponta a ponta
def test_pipeline_pncp_grava_no_postgres_e_retoma(sessao_fake, rota_pncp, sink_pg, pg):
    s, _ = sessao_fake(rota_pncp)
    coletor = ColetorPNCP(PNCPClient(s, "https://pncp.gov.br/api/consulta", delay=0), sink_pg, "3516200",
                          cnpjs_orgaos=(), modalidades=(6, 8))
    primeira = coletor.coletar(date(2026, 10, 1), date(2026, 10, 27))
    segunda = coletor.coletar(date(2026, 10, 1), date(2026, 10, 27))

    assert primeira.contratacoes.resultados["inserido"] == 3 and primeira.contratos.resultados["inserido"] == 3
    assert segunda.contratacoes.resultados["inalterado"] == 3 and segunda.contratos.resultados["inalterado"] == 3
    assert _um(pg, "SELECT (SELECT count(*) FROM licitacoes), (SELECT count(*) FROM contratos), "
                   "(SELECT count(*) FROM contratos WHERE licitacao_id IS NOT NULL)") == (3, 3, 1)
    assert [r[0] for r in pg.execute("SELECT DISTINCT status FROM execucoes_coleta")] == ["sucesso"]
    assert coletor.inicio_incremental(date(2026, 1, 1)) == date(2026, 10, 24)


# --------------------------------------------------------------- qualidade de dado
def _alertas(pg, view: str, id_pncp: str) -> tuple[str, list[str]]:
    return _um(pg, f"SELECT natureza, alertas FROM {view} WHERE id_pncp = %s", (id_pncp,))


def test_alertas_de_qualidade_das_licitacoes(sink_pg, pg):
    sink_pg.salvar_licitacao(contratacao(0, valorTotalEstimado=-36, valorTotalHomologado=900000))
    sink_pg.salvar_licitacao(contratacao(1, valorTotalEstimado=2_000_000_000))
    sink_pg.salvar_licitacao(contratacao(0, "contratacoes_p2.json", modalidadeId=1, valorTotalEstimado=100,
                                         valorTotalHomologado=500))       # leilão: lance acima do estimado é normal

    assert _alertas(pg, "vw_licitacoes_qualidade", LIC_12) == \
        ("despesa", ["valor_negativo", "homologado_divergente"])
    assert _alertas(pg, "vw_licitacoes_qualidade", "47970769000104-1-000013/2026") == ("despesa", ["valor_atipico"])
    assert _alertas(pg, "vw_licitacoes_qualidade", "47970769000104-1-000014/2026") == ("receita", ["receita"])

    # Somas por modalidade ignoram o negativo; a contagem de alertas aparece
    linha = _um(pg, "SELECT qtd, valor_estimado, qtd_com_alerta FROM vw_licitacoes_por_modalidade "
                    "WHERE modalidade_id = 6")
    assert linha == (2, 2_000_000_000, 2)


def test_alertas_de_qualidade_dos_contratos(sink_pg, pg):
    sink_pg.salvar_contrato(contrato(0))
    sink_pg.salvar_contrato(contrato(1, valorGlobal=0, valorInicial=0, receita=True))
    assert _alertas(pg, "vw_contratos_qualidade", CONTRATO_0) == ("despesa", [])
    assert _alertas(pg, "vw_contratos_qualidade", "47970769000104-2-000006/2026") == \
        ("receita", ["receita", "valor_nao_positivo"])
