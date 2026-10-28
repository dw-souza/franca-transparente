import base64
import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs

import pytest
import yaml

from franca_collectors.config import ENDPOINTS_DIR_PADRAO
from franca_collectors.rea import har
from franca_collectors.rea.runner import coletar_endpoint, renderizar
from franca_collectors.rea.spec import EndpointSpec, carregar_specs
from franca_collectors.storage import MemoriaSink


def test_yaml_do_repositorio_sao_validos():
    specs = carregar_specs(ENDPOINTS_DIR_PADRAO, incluir_modelos=True)
    ids = {s.id for s in specs}
    assert "exemplo.despesas.empenhos" in ids and "transparencia.despesas.empenhos" in ids
    assert not any(s.ativo for s in specs)  # nada roda sem mapeamento confirmado


def test_modelos_ficam_fora_da_execucao():
    assert all(not s.id.startswith("exemplo.") for s in carregar_specs(ENDPOINTS_DIR_PADRAO))


def test_spec_rejeita_ativo_sem_mapeamento():
    with pytest.raises(ValueError):
        EndpointSpec(id="a.b", portal="x", url="https://x", ativo=True, status="a_mapear")


def test_spec_rejeita_campo_desconhecido():
    with pytest.raises(ValueError):
        EndpointSpec(id="a.b", portal="x", url="https://x", urll="erro de digitação")


def test_renderizar_templates():
    ctx = {"data_inicio": date(2026, 10, 1), "ano": 2026}
    assert renderizar({"d": "{data_inicio:%d/%m/%Y}", "l": ["{ano}"], "n": 5}, ctx) == \
        {"d": "01/10/2026", "l": ["2026"], "n": 5}
    with pytest.raises(KeyError):
        renderizar("{nao_existe}", ctx)


def test_executa_spec_modelo_com_paginacao_offset_no_corpo(sessao_fake):
    spec = next(s for s in carregar_specs(ENDPOINTS_DIR_PADRAO, incluir_modelos=True)
                if s.id == "exemplo.despesas.empenhos").model_copy(update={"intervalo_segundos": 0})
    base = [{"numeroEmpenho": str(i), "exercicio": 2026, "credor": {"cnpjCpf": "1", "nome": f"C{i}"},
             "valores": {"empenhado": i * 10.0, "pago": 0}} for i in range(150)]

    def rota(metodo, path, params, corpo):
        f = {k: v[0] for k, v in parse_qs(corpo).items()}
        ini, tam = int(f["start"]), int(f["length"])
        return 200, {"draw": 1, "recordsTotal": 150, "data": base[ini:ini + tam]}

    s, fake = sessao_fake(rota)
    sink = MemoriaSink()
    stats = coletar_endpoint(s, spec, sink, date(2026, 10, 1), date(2026, 10, 20))
    assert stats.lidos == 150 and len(sink.brutos) == 150
    assert [parse_qs(c["corpo"])["start"][0] for c in fake.chamadas] == ["0", "100"]
    assert parse_qs(fake.chamadas[0]["corpo"])["dataInicial"] == ["01/10/2026"]
    r = sink.brutos[("exemplo.despesas.empenhos", "7|2026")]
    assert r.mapeado["credor_nome"] == "C7" and r.mapeado["valor_empenhado"] == 70.0


def _har(tmp_path: Path) -> Path:
    def entrada(url, corpo, metodo="GET", mime="application/json", post=None, b64=False):
        txt = json.dumps(corpo)
        content = {"mimeType": mime, "text": base64.b64encode(txt.encode()).decode() if b64 else txt}
        if b64:
            content["encoding"] = "base64"
        req = {"method": metodo, "url": url}
        if post:
            req["postData"] = post
        return {"request": req, "response": {"status": 200, "content": content}}

    host = "https://transparencia.exemplo.gov.br"
    entries = [
        entrada(f"{host}/app.js", {"x": 1}),
        entrada(f"{host}/api/menu", {"itens": ["a", "b"]}),
        entrada(f"{host}/api/licitacoes/pesquisar?pagina=1&tamanhoPagina=20&ano=2026",
                {"total": 2, "resultado": {"itens": [{"id": 1, "objeto": "x", "valor": 1.0},
                                                     {"id": 2, "objeto": "y", "valor": 2.0}]}}, b64=True),
        entrada(f"{host}/api/licitacoes/pesquisar?pagina=2&tamanhoPagina=20&ano=2026",
                {"total": 2, "resultado": {"itens": []}}),
        entrada(f"{host}/Despesas/Empenhos", {"data": [{"empenho": "1", "credor": "A"}]}, metodo="POST",
                post={"mimeType": "application/x-www-form-urlencoded",
                      "params": [{"name": "start", "value": "0"}, {"name": "length", "value": "10"},
                                 {"name": "exercicio", "value": "2026"}]}),
        entrada("https://www.google-analytics.com/collect", {"ok": True}),
    ]
    p = tmp_path / "captura.har"
    p.write_text(json.dumps({"log": {"entries": entries}}))
    return p


def test_har_encontra_apis_de_dados(tmp_path):
    cands = har.analisar(_har(tmp_path), host="transparencia.exemplo.gov.br")
    urls = [c.url for c in cands]
    assert urls[0].endswith("/api/licitacoes/pesquisar")      # lista com mais campos vem primeiro
    assert not any("app.js" in u or "google" in u for u in urls)
    lic = cands[0]
    assert lic.chamadas == 2 and lic.registros_em == "resultado.itens" and lic.campos == ["id", "objeto", "valor"]

    spec_lic = har.esqueleto_spec(lic)
    assert spec_lic["paginacao"]["tipo"] == "pagina" and spec_lic["params"] == {"ano": "2026"}
    emp = next(c for c in cands if c.url.endswith("/Despesas/Empenhos"))
    spec_emp = har.esqueleto_spec(emp)
    assert spec_emp["paginacao"] | {} == {"tipo": "offset", "parametro": "start", "inicio": 0,
                                          "tamanho_parametro": "length", "tamanho": 100, "em": "corpo"}
    # Rascunhos gerados são specs válidas (após yaml round-trip)
    for sp in (spec_lic, spec_emp):
        EndpointSpec.model_validate(yaml.safe_load(yaml.safe_dump(sp)))
