"""Coleta do portal municipal (EddyData): normalização com lista branca, pipeline e views de execução da despesa.

Dados sintéticos no formato real da API (ver dados/eddydata/ da sonda, que não vai para o git).
"""

import json
from datetime import date
from decimal import Decimal

import pytest
from test_eddydata import _jwt

from franca_collectors import cli
from franca_collectors.eddydata.cliente import EddyDataClient
from franca_collectors.eddydata.normalize import (
    data_local,
    mascarar_cpf,
    normalizar_contrato_municipal,
    normalizar_empenho,
)
from franca_collectors.eddydata.pipeline import ColetorEddyData
from franca_collectors.storage import MemoriaSink

API = "https://eddydata-api.franca.sp.gov.br/api/v1/franca"
CNPJ = "47970769000104"

FAV_PJ = {"id": 10, "nome": "DISTRIBUIDORA EXEMPLO LTDA", "cpf_cnpj": "12.345.678/0001-95", "pis": "123",
          "email": "x@exemplo.com", "data_nascimento": None, "endereco": "Rua A", "tipo": {"id": 2, "nome": "PJ"}}
FAV_MEI = {"id": 11, "nome": "FULANO DE TAL 12345678909", "cpf_cnpj": "123.456.789-09", "telefone": "1699"}
FICHA = {"id": 1, "numero": 771,
         "executora": {"codigo": "020701", "nome": "SECRETARIA MUN. DE SAÚDE",
                       "unidade": {"codigo": "020700", "nome": "SECRETARIA MUN. DE SAÚDE", "cpf": "11122233344",
                                   "responsavel": "Secretária"}},
         "despesa": {"codigo": "33903000", "nome": "Material de Consumo"},
         "funcao": {"codigo": "10", "nome": "SAÚDE"}, "subfuncao": {"nome": "ATENÇÃO BÁSICA"},
         "programa": {"nome": "REDE BÁSICA"}, "acao": {"nome": "Manutenção da Atenção Básica"},
         "recurso": {"codigo": "01", "nome": "RECURSOS PRÓPRIOS"}}
CONTRATO = {"id": 501, "numero": "00052026", "ano": 2026, "processo": "06278/2026", "tipo": "CONTRATO",
            "tipo_contrato": "OUTROS", "objeto": "Fornecimento de medicamentos", "valor_contrato": "120000.000000",
            "data_assinatura": "2026-10-15T03:00:00.000Z", "data_inicio": "2026-10-15T03:00:00.000Z",
            "data_termino": "2027-10-14T03:00:00.000Z", "excluido": False, "inativo": False, "sequencial_pncp": 5,
            "gestor_cpf": "99988877766", "favorecido": FAV_PJ,
            "licitacao": {"id": 70, "sequencial_pncp": 12, "ano_pncp": 2026}}
CONTRATO_SO_MUNICIPAL = {**CONTRATO, "id": 502, "numero": "00062026", "sequencial_pncp": None,
                         "valor_contrato": "5000.00", "favorecido": FAV_MEI, "licitacao": None}
ATA_SO_MUNICIPAL = {**CONTRATO_SO_MUNICIPAL, "id": 503, "tipo": "REGISTRO_PRECO"}  # vira ata no PNCP, não contrato
EMPENHOS = [
    {"id": 9001, "numero": 26214, "especie": "EMO", "tipo_empenho": "O", "valor_empenho": "100000.00",
     "data_empenho": "2026-10-16T03:00:00.000Z", "processo": "06278/2026",
     "historico": "Empenho ref. contrato 0005/2026, fiscal CPF 123.456.789-09", "favorecido": FAV_PJ,
     "subelemento": {"codigo": "33903009001", "nome": "MEDICAMENTOS"},
     "modalidade": {"codigo": "8", "nome": "PREGÃO - ELETRÔNICO"}, "ficha": FICHA,
     "contrato": {"id": 501, "ano": 2026, "sequencial_pncp": 5}, "licitacao": {"sequencial_pncp": 12, "ano_pncp": 2026}},
    {"id": 9002, "numero": 26300, "especie": "EOA", "tipo_empenho": "O", "valor_empenho": "-10000.00",
     "data_empenho": "2026-10-20T03:00:00.000Z", "historico": "ANULAÇÃO PARCIAL", "favorecido": FAV_PJ,
     "ficha": FICHA, "contrato": {"id": 501, "ano": 2026, "sequencial_pncp": 5}, "licitacao": None},
]
LIQUIDACOES = [
    {"id": 8001, "valor_liquidado": "60000.00", "data_liquidacao": "2026-10-21T03:00:00.000Z", "anulacao": False,
     "anulado_total": False, "documento": "NF 1", "empenho": {"id": 9001}},
    {"id": 8002, "valor_liquidado": "5000.00", "data_liquidacao": "2026-10-22T03:00:00.000Z", "anulacao": True,
     "anulado_total": False, "documento": "NF 1", "empenho": {"id": 9001}},
]
PAGAMENTOS = [
    {"id": 7001, "valor_pago": "40000.00", "valor_retido": "1000.00", "data_pagamento": "2026-10-25T03:00:00.000Z",
     "anulacao": False, "anulado_total": False, "situacao": "E", "documento": "OP 1",
     "liquidacao": {"id": 8001, "empenho": {"id": 9001}}},
]
ADITAMENTOS = [
    {"id": 9457, "numero": "1", "finalidade": "1º ADITIVO - PRAZO - 12 MESES", "valor_total": "50500.0000",
     "data_aditamento": "2026-10-26T03:00:00.000Z", "mudanca_vigencia": True, "contrato": {"id": 501}},
]
POR_RECURSO = {"contratos": [CONTRATO, CONTRATO_SO_MUNICIPAL, ATA_SO_MUNICIPAL], "contrato-aditamentos": ADITAMENTOS,
               "empenhos": EMPENHOS, "liquidacoes": LIQUIDACOES, "pagamentos": PAGAMENTOS}


def rota_eddydata(metodo, path, params, corpo):
    if path.endswith("/usuarios/token-publico"):
        return 200, {"token": _jwt(iat=0, exp=10**12)}
    if path.endswith("/orgaos/filtrar"):
        return 200, {"content": [{"id": 1, "codigo": "020000", "nome": "MUNICÍPIO DE FRANCA",
                                  "cnpj": "47.970.769/0001-04", "chave_acesso": "segredo"}], "totalPages": 1}
    recurso, pagina, limite = path.split("/franca/1/")[1].split("/")
    registros = POR_RECURSO[recurso]
    i, n = (int(pagina) - 1) * int(limite), int(limite)
    return 200, {"content": registros[i:i + n], "totalPages": -(-len(registros) // n), "numberOfElements": len(registros)}


def cliente(sessao):
    return EddyDataClient(sessao, API, delay=0)


# ------------------------------------------------------------------ normalização
def test_empenho_lista_branca_e_vinculos():
    e = normalizar_empenho(EMPENHOS[0], CNPJ)
    assert e.unidade.codigo == "020700" and e.unidade.nome == "SECRETARIA MUN. DE SAÚDE"
    assert e.contrato_id_pncp == f"{CNPJ}-2-000005/2026" and e.licitacao_id_pncp == f"{CNPJ}-1-000012/2026"
    assert e.contrato_id_fonte == 501 and e.data_empenho == date(2026, 10, 16) and e.ano == 2026
    assert e.historico == "Empenho ref. contrato 0005/2026, fiscal CPF ***.***.***-**"
    assert e.fornecedor.cnpj_cpf == "12345678000195" and e.fornecedor.tipo_pessoa == "PJ"
    despejo = json.dumps(e.model_dump(mode="json"))
    for sensivel in ("x@exemplo.com", "Rua A", "11122233344", "Secretária", "pis"):
        assert sensivel not in despejo


def test_contrato_mei_com_cpf_no_nome_e_sem_pncp():
    c = normalizar_contrato_municipal(CONTRATO_SO_MUNICIPAL, CNPJ)
    assert c.fornecedor.tipo_pessoa == "PF" and c.fornecedor.cnpj_cpf == "12345678909"
    assert c.credor_nome == "FULANO DE TAL ***.***.***-**"
    assert c.id_pncp is None and c.licitacao_id_pncp is None
    assert "99988877766" not in json.dumps(c.model_dump(mode="json"))  # gestor_cpf fica de fora


def test_datas_em_utc_viram_data_de_brasilia():
    assert data_local("2026-09-28T03:00:00.000Z") == date(2026, 9, 28)
    assert data_local("2026-09-29T02:00:00.000Z") == date(2026, 9, 28)  # 23h do dia 28 em Brasília
    assert mascarar_cpf("doc 12345678909 e 1234567890123") == "doc ***.***.***-** e 1234567890123"


# ------------------------------------------------------------------ pipeline
def test_pipeline_em_memoria_e_filtros(sessao_fake):
    s, fake = sessao_fake(rota_eddydata)
    sink = MemoriaSink()
    resumo = ColetorEddyData(cliente(s), sink).coletar(date(2026, 10, 1), date(2026, 10, 31))
    assert {t: r.lidos for t, r in resumo.items()} == \
        {"contrato": 3, "aditamento": 1, "empenho": 2, "liquidacao": 2, "pagamento": 1}
    assert all(r.erros == 0 for r in resumo.values())
    gets = {c["path"].split("/franca/1/")[1].split("/")[0]: c["params"] for c in fake.chamadas
            if c["metodo"] == "GET" and "/orgaos/" not in c["path"]}
    assert gets["contrato-aditamentos"]["contrato.orgao.id"] == "1"
    assert gets["empenhos"]["data_empenho$ge"] == "2026-10-01" and gets["empenhos"]["orgao.id"] == "1"
    assert all(c["path"].endswith("/1000") for c in fake.chamadas if "/empenhos/" in c["path"])


def test_incremental_por_recurso(sessao_fake):
    s, _ = sessao_fake(rota_eddydata)
    sink = MemoriaSink()
    coletor = ColetorEddyData(cliente(s), sink)
    assert coletor.inicio_incremental("empenho", date(2026, 1, 1)) == date(2026, 1, 1)
    coletor.coletar(date(2026, 10, 1), date(2026, 10, 31), ["empenho"])
    assert coletor.inicio_incremental("empenho", date(2026, 1, 1)) == date(2026, 10, 16)
    assert coletor.inicio_incremental("pagamento", date(2026, 1, 1)) == date(2026, 1, 1)


def test_cli_eddydata_jsonl_e_recurso_invalido(sessao_fake, monkeypatch, tmp_path, capsys):
    s, _ = sessao_fake(rota_eddydata)
    from franca_collectors.eddydata import cliente as mod_cliente

    monkeypatch.setattr(mod_cliente, "criar_cliente", lambda *a, **k: cliente(s))
    assert cli.main(["eddydata", "coletar", "--recursos", "empenho,xyz"]) == 2
    saida = tmp_path / "e.jsonl"
    assert cli.main(["eddydata", "coletar", "--desde", "2026-10-01", "--ate", "2026-10-31",
                     "--recursos", "empenho,pagamento", "--saida", "jsonl", "--arquivo", str(saida)]) == 0
    tipos = [json.loads(linha)["tipo"] for linha in saida.read_text().splitlines()]
    assert tipos == ["empenho", "empenho", "pagamento"]


# ------------------------------------------------------------------ Postgres
@pytest.mark.integracao
def test_execucao_da_despesa_no_postgres(sessao_fake, rota_pncp, sink_pg, pg):
    from franca_collectors.pncp.client import PNCPClient
    from franca_collectors.pncp.pipeline import ColetorPNCP

    sp, _ = sessao_fake(rota_pncp)   # contratos do PNCP primeiro (o contrato 000005/2026 vale 120 mil)
    ColetorPNCP(PNCPClient(sp, delay=0), sink_pg, "3516200", modalidades=(6,)).coletar(
        date(2026, 10, 1), date(2026, 10, 27))
    nome_pncp = pg.execute("SELECT razao_social FROM fornecedores WHERE cnpj_cpf = '12345678000195'").fetchone()

    s, _ = sessao_fake(rota_eddydata)
    coletor = ColetorEddyData(cliente(s), sink_pg)
    coletor.coletar(date(2026, 10, 1), date(2026, 10, 31))

    # Empenho 9001: 100 mil empenhados, 60 mil liquidados − 5 mil anulados, 40 mil pagos; 9002 anula 10 mil
    x = pg.execute("SELECT empenhado, liquidado, pago FROM vw_execucao_empenho WHERE id_fonte = 9001").fetchone()
    assert x == (Decimal("100000.00"), Decimal("55000.00"), Decimal("40000.00"))
    assert pg.execute("SELECT secretaria, empenhado, liquidado, pago FROM vw_despesa_por_secretaria").fetchall() == \
        [("SECRETARIA MUN. DE SAÚDE", Decimal("90000.00"), Decimal("55000.00"), Decimal("40000.00"))]

    cxp = pg.execute("SELECT contratado, empenhado, pago, empenhos FROM vw_contratado_x_pago "
                     "WHERE id_pncp = %s", (f"{CNPJ}-2-000005/2026",)).fetchone()
    assert cxp == (Decimal("120000.00"), Decimal("90000.00"), Decimal("40000.00"), 2)

    fora = [r[0] for r in pg.execute("SELECT id_fonte FROM vw_contratos_municipais_fora_do_pncp")]
    assert fora == [502]
    assert pg.execute("SELECT count(*) FROM contrato_aditamentos WHERE contrato_id_fonte = 501").fetchone()[0] == 1
    # Nome do fornecedor que veio do PNCP não é sobrescrito pelo do sistema municipal
    assert pg.execute("SELECT razao_social FROM fornecedores WHERE cnpj_cpf = '12345678000195'").fetchone() == \
        nome_pncp
    # Órgão: reaproveita o do PNCP (mesmo CNPJ), não cria outro
    assert pg.execute("SELECT count(*) FROM orgaos WHERE cnpj = %s", (CNPJ,)).fetchone()[0] == 1

    # Reexecução idempotente
    resumo = coletor.coletar(date(2026, 10, 1), date(2026, 10, 31))
    assert all(set(r.resultados) == {"inalterado"} for r in resumo.values())


@pytest.mark.integracao
def test_sink_novo_sem_cache_cria_e_reaproveita_orgao(banco_teste, pg):
    """Regressão: o SQL de garantir órgão só roda com o cache vazio (bug de tipos no 1º run real)."""
    from franca_collectors.storage.postgres import PostgresSink

    for _ in range(2):  # 1º sink cria o órgão; 2º, também sem cache, reaproveita
        with PostgresSink(banco_teste) as sink:
            assert sink.salvar_municipal("empenho", normalizar_empenho(EMPENHOS[0], "11222333000181")) in \
                ("inserido", "inalterado")
            assert sink.salvar_municipal("contrato", normalizar_contrato_municipal(CONTRATO, "11222333000181")) in \
                ("inserido", "inalterado")
    assert pg.execute("SELECT count(*) FROM orgaos WHERE cnpj = '11222333000181'").fetchone()[0] == 1
    assert pg.execute("SELECT count(*) FROM empenhos").fetchone()[0] == 1
