#!/usr/bin/env python3
"""Sonda do Portal da Transparência de Franca (EddyData) — rodada 2: só GET, poucas dezenas de requisições.

Usa o mesmo cliente do coletor (franca_collectors.eddydata.cliente) e responde ao que falta para a Fase 2:
  A. volumes por ano (dimensiona banco e tempo de coleta);
  B. relações: secretaria (ficha → executora → unidade), classificação da despesa e o vínculo
     empenho → contrato/licitação e contrato → licitação (para cruzar com o PNCP);
  C. filtro que funciona em contrato-aditamentos;
  D. tamanho máximo de página aceito;
  E. campos de favorecido, para a lista branca (só nomes e tipos, sem valores).

Uso (na raiz do repositório, com o .venv ativo):
  pip install -e "services/collectors[postgres,dev]"
  python scripts/sonda_eddydata.py
Saída: dados/eddydata/relatorio2.txt (sem dados pessoais) e amostras JSON em dados/eddydata/sonda2/ (com dados
pessoais de credores: ficam fora do git, não publique).
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from franca_collectors.eddydata.cliente import criar_cliente

USER_AGENT = "PainelTransparenciaFranca/0.1 (+https://github.com/dw-souza/franca-transparente)"
SAIDA = Path("dados/eddydata")
AMOSTRAS = SAIDA / "sonda2"
FIM = date.today()
INICIO = FIM - timedelta(days=30)
SENSIVEL = re.compile(r"cpf|rg$|senha|chave|token|email|telefone|celular|nascimento|endereco|cep|banco|agencia|"
                      r"conta|pis|nis|responsavel|ordenador|tesoureiro|presidente|assinatura|gestor", re.I)

linhas: list[str] = []


def log(msg: str = "") -> None:
    print(msg)
    linhas.append(msg)


def valor(d, caminho: str):
    for parte in caminho.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(parte)
    return d


def mostrar(registro: dict, caminhos: list[str]) -> None:
    for c in caminhos:
        v = valor(registro, c)
        chave = c.split(".")[-1]
        if chave == "cpf_cnpj" and v:
            digitos = re.sub(r"\W", "", str(v))
            v = f"<{'CNPJ' if len(digitos) == 14 else 'CPF' if len(digitos) == 11 else '?'} oculto>"
        elif SENSIVEL.search(chave) and v not in (None, ""):
            v = "<oculto>"
        elif isinstance(v, dict):
            v = f"{{{', '.join(sorted(v)[:25])}}}"
        elif isinstance(v, str) and len(v) > 80:
            v = v[:80] + "…"
        log(f"     {c:42} {v}")


def main() -> int:
    AMOSTRAS.mkdir(parents=True, exist_ok=True)
    cli = criar_cliente(USER_AGENT, delay=1.5)
    log(f"sonda EddyData (rodada 2) {time.strftime('%F %T')} · amostras de {INICIO} a {FIM}")
    orgao = cli.orgao_id()
    log(f"órgão id={orgao}")
    base = {"ignoreCondObrig": "true", "orgao.id": orgao}

    def get(nome, caminho, params, salvar=True):
        t = time.time()
        try:
            dados = cli.get(caminho, params)
        except Exception as exc:  # noqa: BLE001 - a sonda registra a falha e segue
            log(f"\n== {nome}: FALHOU ({type(exc).__name__}) {str(exc)[:300]}")
            return None
        log(f"\n== {nome}: total={dados.get('numberOfElements')} páginas={dados.get('totalPages')} "
            f"veio={len(dados.get('content') or [])} ({time.time() - t:.1f}s)")
        if salvar:
            (AMOSTRAS / f"{nome}.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2))
        return dados

    # A. volumes por ano -------------------------------------------------------------------------
    log("\n######## A. volumes por ano (limite 1, só o total)")
    datas = {"licitacoes": "data_abertura", "contratos": "data_inicio", "empenhos": "data_empenho",
             "liquidacoes": "data_liquidacao", "pagamentos": "data_pagamento"}
    for recurso, campo in datas.items():
        for ano in (2024, 2025, 2026):
            periodo = {f"{campo}$ge": f"{ano}-01-01", f"{campo}$le": f"{ano}-12-31"}
            get(f"volume_{recurso}_{ano}", f"{recurso}/1/1", {**base, **periodo}, salvar=False)
    ano_2025 = {"data_empenho$ge": "2025-01-01", "data_empenho$le": "2025-12-31"}
    for rel in ("contrato", "licitacao"):
        get(f"volume_empenhos_2025_com_{rel}", "empenhos/1/1", {**base, **ano_2025, f"{rel}$not_null": ""},
            salvar=False)

    # B. relações --------------------------------------------------------------------------------
    log("\n######## B. relações")
    mes_emp = {"data_empenho$ge": INICIO.isoformat(), "data_empenho$le": FIM.isoformat()}
    rel_emp = ("favorecido,subelemento,modalidade,contrato,licitacao,ficha,ficha.executora,ficha.executora.unidade,"
               "ficha.despesa,ficha.funcao,ficha.subfuncao,ficha.programa,ficha.acao,ficha.recurso")
    d = get("empenhos_com_contrato", "empenhos/1/3",
            {**base, **mes_emp, "contrato$not_null": "", "relations": rel_emp})
    for r in (d or {}).get("content") or []:
        log("   -- empenho")
        mostrar(r, ["numero", "especie", "tipo_empenho", "valor_empenho", "processo", "sequencial_pncp",
                    "favorecido.nome", "favorecido.cpf_cnpj", "subelemento.codigo", "subelemento.nome",
                    "modalidade.codigo", "modalidade.nome",
                    "ficha.numero", "ficha.executora.codigo", "ficha.executora.nome",
                    "ficha.executora.unidade.codigo", "ficha.executora.unidade.nome",
                    "ficha.despesa.codigo", "ficha.despesa.nome", "ficha.funcao.codigo", "ficha.funcao.nome",
                    "ficha.subfuncao.nome", "ficha.programa.nome", "ficha.acao.nome", "ficha.recurso.codigo",
                    "ficha.recurso.nome", "contrato", "contrato.numero", "contrato.ano", "contrato.sequencial_pncp",
                    "contrato.processo", "contrato.valor_contrato", "licitacao", "licitacao.numero",
                    "licitacao.processo", "licitacao.sequencial_pncp"])

    mes_ctr = {"data_inicio$ge": INICIO.isoformat(), "data_inicio$le": FIM.isoformat()}
    d = get("contratos_com_licitacao", "contratos/1/3", {**base, **mes_ctr, "excluido": "false",
            "relations": "favorecido,licitacao,licitacao.modalidade,modalidade"})
    for r in (d or {}).get("content") or []:
        log("   -- contrato")
        mostrar(r, ["numero", "ano", "tipo", "tipo_contrato", "processo", "sequencial_pncp", "cadastrado_pncp",
                    "excluido", "inativo", "valor_contrato", "data_assinatura", "data_termino", "favorecido.nome",
                    "favorecido.cpf_cnpj", "modalidade.nome", "licitacao.numero", "licitacao.processo",
                    "licitacao.sequencial_pncp", "licitacao.modalidade.nome"])

    mes_lic = {"data_abertura$ge": INICIO.isoformat(), "data_abertura$le": FIM.isoformat()}
    get("licitacoes_com_modalidade", "licitacoes/1/3", {**base, **mes_lic, "relations": "modalidade"})

    # C. aditamentos -----------------------------------------------------------------------------
    log("\n######## C. contrato-aditamentos: qual filtro funciona")
    semestre = {"data_aditamento$ge": (FIM - timedelta(days=180)).isoformat(),
                "data_aditamento$le": FIM.isoformat(), "relations": "contrato"}
    variantes = {
        "contrato.orgao.id": {"ignoreCondObrig": "true", "contrato.orgao.id": orgao},
        "so_data": {"ignoreCondObrig": "true"},
        "contrato.orgao.id_sem_ignore": {"contrato.orgao.id": orgao},
    }
    for nome, extra in variantes.items():
        d = get(f"aditamentos_{nome}", "contrato-aditamentos/1/3", {**semestre, **extra})
        for r in (d or {}).get("content") or []:
            mostrar(r, ["numero", "tipo", "finalidade", "data_aditamento", "valor_total", "valor_aditado",
                        "sequencial_pncp", "contrato.numero", "contrato.ano", "contrato.sequencial_pncp"])

    # D. tamanho de página -----------------------------------------------------------------------
    log("\n######## D. tamanho máximo de página (empenhos de uma semana, sem relações)")
    semana = {**base, "data_empenho$ge": (FIM - timedelta(days=7)).isoformat(), "data_empenho$le": FIM.isoformat()}
    for limite in (100, 500, 1000):
        get(f"pagina_{limite}", f"empenhos/1/{limite}", semana, salvar=False)

    # E. campos de favorecido --------------------------------------------------------------------
    log("\n######## E. campos de favorecido (nomes e tipos; valores omitidos)")
    d = get("favorecido_campos", "favorecidos/1/1", {"ignoreCondObrig": "true", "relations": "tipo"},
            salvar=False)
    for r in (d or {}).get("content") or []:
        for k in sorted(r):
            v = r[k]
            tipo = type(v).__name__ if not isinstance(v, dict) else "{" + ",".join(sorted(v)[:8]) + "}"
            log(f"     {k:32} {tipo}{'  <- sensível' if SENSIVEL.search(k) else ''}")

    log(f"\nrequisições: {cli.requisicoes}")
    return 0


if __name__ == "__main__":
    try:
        codigo = main()
    finally:  # grava o relatório mesmo se a sonda parar no meio
        SAIDA.mkdir(parents=True, exist_ok=True)
        (SAIDA / "relatorio2.txt").write_text("\n".join(linhas) + "\n", encoding="utf-8")
        print(f"\nrelatório em {SAIDA / 'relatorio2.txt'}; amostras em {AMOSTRAS}/")
    sys.exit(codigo)
