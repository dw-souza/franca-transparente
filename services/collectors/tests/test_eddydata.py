import base64
import json

import bcrypt
import pytest
import requests

from franca_collectors.eddydata.cliente import EddyDataClient, bundle_ca, js_to_fixed0
from franca_collectors.http import RespostaInvalida

API = "https://eddydata-api.franca.sp.gov.br/api/v1/franca"
SAL = bcrypt.gensalt(rounds=4).decode()  # rounds baixo só para o teste ser rápido


def _jwt(iat: int = 1_000, exp: int = 2_800, id_: int = 0) -> str:
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64({'iat': iat, 'exp': exp, 'id': id_, 'chave': SAL})}.assinatura"


class Relogio:
    def __init__(self, t: float = 1_500):
        self.t = t

    def __call__(self):
        return self.t


def _cliente(sessao, relogio=None):
    return EddyDataClient(sessao, API, delay=0, relogio=relogio or Relogio())


def _rota(paginas=None, tokens=None, falhar_401=0):
    """token-publico + listagem paginada de `empenhos`; os primeiros `falhar_401` GETs devolvem 401."""
    estado = {"tokens": list(tokens or [_jwt()]), "401": falhar_401}

    def rota(metodo, path, params, corpo):
        if path.endswith("/usuarios/token-publico"):
            return 200, {"token": estado["tokens"].pop(0)}
        if estado["401"]:
            estado["401"] -= 1
            return 401, "Unauthorized"
        pag = int(path.split("/")[-2])
        conteudo = (paginas or [[{"id": 1}]])[pag - 1]
        return 200, {"content": conteudo, "totalPages": len(paginas or [[]]), "numberOfElements": 99}

    return rota


@pytest.mark.parametrize(("a", "b", "esperado"), [
    (5, 0, "Infinity"), (-5, 0, "-Infinity"), (0, 0, "NaN"),
    (5, 2, "3"), (-5, 2, "-3"), (7, 2, "4"), (1, 3, "0"), (-1, 3, "-0"),
])
def test_to_fixed_igual_ao_javascript(a, b, esperado):
    # valores conferidos com node: [5/0, ..., -1/3].map(x => x.toFixed(0))
    assert js_to_fixed0(a, b) == esperado


def test_cabecalhos_reproduzem_a_pagina_publica(sessao_fake):
    s, fake = sessao_fake(_rota())
    cab = _cliente(s, Relogio(1_500.25)).cabecalhos()
    assert fake.chamadas[0]["metodo"] == "POST" and fake.chamadas[0]["path"].endswith("/usuarios/token-publico")
    assert cab["Authorization"] == f"JWT {_jwt()}"
    assert cab["agora"] == "1500250"
    assert bcrypt.checkpw(b"Infinity", cab["codigo"].encode())  # token público: id = 0


def test_paginacao_e_url(sessao_fake):
    s, fake = sessao_fake(_rota(paginas=[[{"id": 1}, {"id": 2}], [{"id": 3}]]))
    ids = [r["id"] for r in _cliente(s).paginar("empenhos", {"orgao.id": 1}, limite=2)]
    assert ids == [1, 2, 3]
    gets = [c for c in fake.chamadas if c["metodo"] == "GET"]
    assert [c["path"].split("/franca/")[1] for c in gets] == ["1/empenhos/1/2", "1/empenhos/2/2"]
    assert gets[0]["params"] == {"orgao.id": "1"}


def test_token_renovado_antes_de_expirar(sessao_fake):
    relogio = Relogio(1_500)
    s, fake = sessao_fake(_rota(tokens=[_jwt(exp=2_800), _jwt(iat=2_700, exp=4_500)]))
    cliente = _cliente(s, relogio)
    cliente.get("empenhos/1/1")
    relogio.t = 2_700  # dentro da margem de 120 s antes do exp
    cliente.get("empenhos/1/1")
    assert sum(c["path"].endswith("token-publico") for c in fake.chamadas) == 2


def test_401_renova_o_token_uma_vez(sessao_fake):
    s, fake = sessao_fake(_rota(tokens=[_jwt(), _jwt()], falhar_401=1))
    assert _cliente(s).get("empenhos/1/1")["content"] == [{"id": 1}]
    assert sum(c["path"].endswith("token-publico") for c in fake.chamadas) == 2


def test_401_persistente_falha(sessao_fake):
    s, _ = sessao_fake(_rota(tokens=[_jwt(), _jwt()], falhar_401=5))
    with pytest.raises(requests.HTTPError):
        _cliente(s).get("empenhos/1/1")


def test_resposta_nao_json_falha_fechado(sessao_fake):
    def rota(metodo, path, params, corpo):
        return (200, {"token": _jwt()}) if path.endswith("token-publico") else (200, "<html>manutenção</html>")

    s, _ = sessao_fake(rota)
    with pytest.raises(RespostaInvalida):
        _cliente(s).get("empenhos/1/1")


def test_bundle_ca_inclui_o_intermediario_da_certum():
    from pathlib import Path

    from franca_collectors.eddydata.cliente import INTERMEDIARIO

    assert INTERMEDIARIO.read_text().strip() in Path(bundle_ca()).read_text()
