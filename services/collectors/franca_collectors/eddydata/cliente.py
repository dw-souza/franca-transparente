"""Cliente da API do Portal da Transparência de Franca (sistema EddyData).

Reproduz o acesso anônimo que a própria página pública faz (https://eddydata.franca.sp.gov.br/transparencia/):

1. ``POST usuarios/token-publico`` devolve ``{"token": <JWT>}`` com ``iat``, ``exp`` (30 min), ``id`` e ``chave``;
2. cada requisição leva ``Authorization: JWT <token>``, ``agora`` (epoch em ms) e
   ``codigo = bcrypt(((agora - iat) / id).toFixed(0), sal=chave)``. O token público tem ``id = 0``, então o
   texto assinado é ``"Infinity"``, exatamente como no navegador.

É a exceção documentada à regra de "falha fechada" (ver ``franca_collectors.http``): a assinatura é uma barreira
do portal, não um controle de acesso a dado restrito. O uso foi decidido pelo mantenedor do projeto. Respostas
que não sejam JSON continuam interrompendo a coleta.

O servidor não envia o certificado intermediário da Certum; ele vai junto do pacote e é somado ao ``certifi``.
A verificação TLS nunca é desligada.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import bcrypt
import certifi
import requests

from franca_collectors.http import RespostaInvalida, Throttle

log = logging.getLogger(__name__)

API_PADRAO = "https://eddydata-api.franca.sp.gov.br/api/v1/franca"
CIDADE = 1
CODIGO_ORGAO = "020000"  # environment.orgao do bundle do portal: Município de Franca
INTERMEDIARIO = Path(__file__).with_name("certum_dv_tls_g2_r39_ca.pem")
MARGEM_TOKEN_S = 120  # renova o token antes de expirar


def bundle_ca() -> str:
    """Caminho de um bundle com as raízes do certifi + o intermediário da Certum."""
    destino = Path(tempfile.gettempdir()) / "franca-collectors-eddydata-ca.pem"
    conteudo = Path(certifi.where()).read_text() + "\n" + INTERMEDIARIO.read_text()
    if not destino.exists() or destino.read_text() != conteudo:
        destino.write_text(conteudo)
    return str(destino)


def js_to_fixed0(numerador: int, divisor: int) -> str:
    """``(numerador / divisor).toFixed(0)`` com a semântica do JavaScript.

    Divisão por zero dá Infinity/-Infinity/NaN; toFixed arredonda meio para cima no módulo e preserva "-0".
    """
    if divisor == 0:
        return "NaN" if numerador == 0 else ("Infinity" if numerador > 0 else "-Infinity")
    x = numerador / divisor
    n = math.floor(abs(x) + 0.5)
    return f"-{n}" if x < 0 else str(n)


def claims_jwt(token: str) -> dict[str, Any]:
    """Payload do JWT, sem verificar a assinatura (só lemos os campos que o navegador também lê)."""
    corpo = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))


class EddyDataClient:
    def __init__(
        self,
        sessao: requests.Session,
        base_url: str = API_PADRAO,
        timeout: float = 60.0,
        delay: float = 1.0,
        cidade: int = CIDADE,
        relogio=time.time,
    ):
        self.sessao = sessao
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.throttle = Throttle(delay)
        self.cidade = cidade
        self.relogio = relogio
        self.requisicoes = 0
        self._token: str | None = None
        self._claims: dict[str, Any] = {}

    # ------------------------------------------------------------------ autenticação
    def _token_valido(self) -> bool:
        exp = self._claims.get("exp")
        return bool(self._token) and (exp is None or self.relogio() < float(exp) - MARGEM_TOKEN_S)

    def autenticar(self) -> None:
        self.throttle.esperar()
        resp = self.sessao.post(f"{self.base_url}/usuarios/token-publico",
                                headers={"Content-Type": "application/json"}, timeout=self.timeout)
        self.requisicoes += 1
        resp.raise_for_status()
        token = resp.json().get("token")
        if not isinstance(token, str) or token.count(".") != 2:
            raise RespostaInvalida("token-publico não devolveu um JWT")
        self._token, self._claims = token, claims_jwt(token)
        log.debug("token público obtido (exp=%s)", self._claims.get("exp"))

    def cabecalhos(self) -> dict[str, str]:
        if not self._token_valido():
            self.autenticar()
        agora = int(self.relogio() * 1000)
        texto = js_to_fixed0(agora - int(self._claims["iat"]), int(self._claims["id"]))
        codigo = bcrypt.hashpw(texto.encode(), str(self._claims["chave"]).encode()).decode()
        return {"Authorization": f"JWT {self._token}", "Content-Type": "application/json",
                "agora": str(agora), "codigo": codigo}

    # ------------------------------------------------------------------ HTTP
    def get(self, caminho: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{self.cidade}/{caminho.lstrip('/')}"
        for tentativa in (1, 2):
            self.throttle.esperar()
            resp = self.sessao.get(url, params=params, headers=self.cabecalhos(), timeout=self.timeout)
            self.requisicoes += 1
            if resp.status_code == 401 and tentativa == 1:  # token revogado/expirado no servidor: renova uma vez
                self._token = None
                continue
            break
        if "json" not in resp.headers.get("Content-Type", ""):
            resp.raise_for_status()
            raise RespostaInvalida(f"{url} devolveu {resp.headers.get('Content-Type')!r} em vez de JSON")
        if resp.status_code >= 400:
            raise requests.HTTPError(f"{resp.status_code} em {url}: {resp.text[:300]}", response=resp)
        return resp.json()

    def paginar(self, recurso: str, params: dict[str, Any], limite: int = 100) -> Iterator[dict[str, Any]]:
        """Percorre ``{recurso}/{pagina}/{limite}``; a resposta traz ``content`` e ``totalPages``."""
        pagina = 1
        while True:
            dados = self.get(f"{recurso}/{pagina}/{limite}", params)
            registros = dados.get("content") or []
            yield from registros
            if not registros or pagina >= int(dados.get("totalPages") or 0):
                return
            pagina += 1

    def orgao(self, codigo: str = CODIGO_ORGAO) -> dict[str, Any]:
        """Órgão do portal (id interno e CNPJ). Só id, código, nome e CNPJ: o objeto traz até chave de acesso."""
        dados = self.get("orgaos/filtrar", {"codigo": codigo, "cidade.id": self.cidade})
        conteudo = dados.get("content") or []
        if not conteudo:
            raise RespostaInvalida(f"órgão {codigo} não encontrado no EddyData")
        o = conteudo[0]
        return {"id": int(o["id"]), "codigo": o.get("codigo"), "nome": o.get("nome"), "cnpj": o.get("cnpj")}

    def orgao_id(self, codigo: str = CODIGO_ORGAO) -> int:
        return self.orgao(codigo)["id"]


def criar_cliente(user_agent: str, retries: int = 5, **kwargs) -> EddyDataClient:
    from franca_collectors.http import criar_sessao

    sessao = criar_sessao(user_agent, retries)
    sessao.verify = bundle_ca()
    return EddyDataClient(sessao, **kwargs)
