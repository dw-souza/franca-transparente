#!/usr/bin/env python3
"""Sonda do Portal da Transparência de Franca (EddyData): poucas leituras, só GET, para mapear a API.

Reproduz o que a página pública faz para qualquer visitante anônimo:
  1. POST usuarios/token-publico  → JWT com {iat, id, chave}
  2. em cada GET, os cabeçalhos Authorization ("JWT " + token), agora (epoch ms) e
     codigo = bcrypt(((agora - iat) / id).toFixed(0), sal=chave)

O servidor não envia o certificado intermediário; baixamos o da Certum (endereço do próprio certificado)
e montamos um bundle com o certifi. A verificação TLS continua ligada.

Uso (na raiz do repositório):
  .venv/bin/pip install bcrypt
  .venv/bin/python scripts/sonda_eddydata.py
Saída: dados/eddydata/relatorio.txt e uma amostra JSON por recurso (dados/ está no .gitignore).
As amostras podem conter dados pessoais (CPF de credor pessoa física): não publique.
"""

from __future__ import annotations

import base64
import json
import math
import ssl
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import bcrypt
import certifi
import requests

API = "https://eddydata-api.franca.sp.gov.br/api/v1/franca"
CIDADE = 1
CODIGO_ORGAO = "020000"  # environment.orgao do bundle do portal
INTERMEDIARIO = "http://certumdvtlsg2r39ca.repository.certum.pl/certumdvtlsg2r39ca.cer"
USER_AGENT = "PainelTransparenciaFranca/0.1 (+https://github.com/dw-souza/franca-transparente)"
PAUSA = 2.0  # segundos entre requisições
SAIDA = Path("dados/eddydata")

FIM = date.today()
INICIO = FIM - timedelta(days=30)

# recurso → (campo de data usado pela tela pública, relations da tela pública)
RECURSOS = {
    "licitacoes": ("data_abertura", None),
    "contratos": ("data_inicio", "orgao,favorecido"),
    "empenhos": ("data_empenho", "favorecido,subelemento,compra,ficha,ficha.acao"),
    "liquidacoes": ("data_liquidacao", "empenho,empenho.favorecido"),
    "pagamentos": ("data_pagamento", "conta,liquidacao,liquidacao.empenho,liquidacao.empenho.favorecido,exercicio,orgao"),
    "atas-registro-precos": (None, None),
    "contrato-aditamentos": (None, None),
}

log_linhas: list[str] = []


def log(msg: str = "") -> None:
    print(msg)
    log_linhas.append(msg)


def bundle_ca() -> str:
    destino = SAIDA / "ca-bundle.pem"
    if not destino.exists():
        der = urllib.request.urlopen(INTERMEDIARIO, timeout=30).read()
        pem = ssl.DER_cert_to_PEM_cert(der) if not der.startswith(b"-----BEGIN") else der.decode()
        destino.write_text(Path(certifi.where()).read_text() + "\n" + pem)
    return str(destino)


def claims(token: str) -> dict:
    corpo = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(corpo + "=" * (-len(corpo) % 4)))


def js_to_fixed0(numerador: int, divisor: int) -> str:
    """`(numerador / divisor).toFixed(0)` com a semântica do JavaScript.

    O token público vem com id=0: no JS a divisão dá Infinity (ou NaN para 0/0), e toFixed devolve o texto.
    toFixed arredonda meio para cima no módulo, diferente do arredondamento bancário do Python.
    """
    if divisor == 0:
        return "NaN" if numerador == 0 else ("Infinity" if numerador > 0 else "-Infinity")
    x = numerador / divisor
    n = math.floor(abs(x) + 0.5)
    return f"-{n}" if x < 0 else str(n)  # o JS também devolve "-0"


def descrever(dados) -> str:
    """Resumo da forma do JSON: chaves de topo, totais e campos do primeiro registro."""
    if isinstance(dados, list):
        primeiro = dados[0] if dados else None
        return f"lista com {len(dados)} item(ns); campos do 1º: {sorted(primeiro)[:40] if isinstance(primeiro, dict) else primeiro!r}"
    if isinstance(dados, dict):
        partes = [f"chaves: {sorted(dados)[:20]}"]
        for k, v in dados.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                partes.append(f"{k}={v}")
            if isinstance(v, list) and v and isinstance(v[0], dict):
                partes.append(f"'{k}' tem {len(v)} registro(s); campos do 1º: {sorted(v[0])[:40]}")
        return "; ".join(partes)
    return repr(dados)[:200]


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.verify = bundle_ca()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    log(f"sonda EddyData {time.strftime('%F %T')} · período {INICIO} → {FIM}")

    # 1. token público
    r = s.post(f"{API}/usuarios/token-publico", headers={"Content-Type": "application/json"}, timeout=30)
    log(f"\n== token-publico: HTTP {r.status_code} {r.headers.get('content-type')}")
    try:
        corpo = r.json()
    except ValueError:
        log(f"   resposta não é JSON: {r.text[:300]!r}")
        return 1
    token = corpo.get("token") if isinstance(corpo, dict) else corpo
    if not isinstance(token, str) or token.count(".") != 2:
        log(f"   formato inesperado: {json.dumps(corpo, ensure_ascii=False)[:500]}")
        return 1
    if isinstance(corpo, dict):
        log(f"   outras chaves da resposta: {sorted(k for k in corpo if k != 'token')}")
    c = claims(token)
    log(f"   claims do JWT: {sorted(c)} · iat={c.get('iat')} exp={c.get('exp')} id={c.get('id')} "
        f"sistema={c.get('sistema')} administrador={c.get('administrador')}")
    log(f"   sal bcrypt: prefixo {str(c.get('chave'))[:7]!r}, {len(str(c.get('chave')))} caracteres")
    autorizacao = "JWT " + token  # a página guarda login.token = 'JWT ' + dados.token

    def assinados() -> dict:
        agora = int(time.time() * 1000)
        comparar = js_to_fixed0(agora - int(c["iat"]), int(c["id"]))
        codigo = bcrypt.hashpw(comparar.encode(), str(c["chave"]).encode()).decode()
        # O serviço base das listagens manda o horário em "agora"; uma variante antiga usa "data".
        return {"Authorization": autorizacao, "Content-Type": "application/json",
                "agora": str(agora), "data": str(agora), "codigo": codigo}

    log(f"   hash gerado: prefixo {assinados()['codigo'][:7]!r}")

    def get(caminho: str, params: dict | None = None, nome: str | None = None):
        time.sleep(PAUSA)
        r = s.get(f"{API}/{CIDADE}/{caminho}", params=params, headers=assinados(), timeout=60)
        log(f"\n== GET {caminho} {params or ''}\n   HTTP {r.status_code} {r.headers.get('content-type')} {len(r.content)} bytes")
        try:
            dados = r.json()
        except ValueError:
            log(f"   não é JSON: {r.text[:300]!r}")
            return None
        log(f"   {descrever(dados)}")
        if r.status_code >= 400:
            log(f"   corpo: {json.dumps(dados, ensure_ascii=False)[:400]}")
        elif nome:
            (SAIDA / f"{nome}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2))
        return dados

    # 2. órgão e exercício, pelas mesmas rotas que a página usa ao abrir (environment: orgao '020000', cidade 1)
    orgao_id = 1
    orgaos = get("orgaos/filtrar", {"codigo": CODIGO_ORGAO, "cidade.id": CIDADE, "relations": "brasao"}, nome="orgaos")
    conteudo = orgaos.get("content") if isinstance(orgaos, dict) else None
    if conteudo:
        o = conteudo[0]
        orgao_id = o.get("id", orgao_id)
        log(f"   órgão id={o.get('id')} codigo={o.get('codigo')} cnpj={o.get('cnpj')} nome={o.get('nome')}")
    get("exercicios/filtrar", {"ano": FIM.year, "cidade_id": CIDADE}, nome="exercicios")

    # 3. uma página pequena de cada recurso, com os filtros que a tela pública usa
    for recurso, (campo_data, relations) in RECURSOS.items():
        params = {"ignoreCondObrig": "true", "orgao.id": orgao_id}
        if campo_data:
            params |= {f"{campo_data}$ge": INICIO.isoformat(), f"{campo_data}$le": FIM.isoformat()}
        if relations:
            params["relations"] = relations
        get(f"{recurso}/1/3", params, nome=recurso)
    return 0


if __name__ == "__main__":
    try:
        codigo_saida = main()
    finally:  # grava o relatório mesmo se a sonda parar no meio
        SAIDA.mkdir(parents=True, exist_ok=True)
        (SAIDA / "relatorio.txt").write_text("\n".join(log_linhas) + "\n", encoding="utf-8")
        print(f"\nrelatório em {SAIDA / 'relatorio.txt'}; amostras JSON em {SAIDA}/")
    sys.exit(codigo_saida)
