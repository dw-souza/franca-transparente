"""Triagem de tráfego capturado (HAR) para achar as APIs internas de um portal.

Uso típico: abrir o portal no navegador com DevTools › Network aberto, navegar pelas telas de
interesse (filtros, paginação, "exportar"), salvar "Save all as HAR" e rodar:

    franca-collect rea har captura.har --host transparencia.franca.sp.gov.br --yaml rascunho.yaml

O analisador agrupa as chamadas que devolvem JSON por (método, URL sem query), mostra parâmetros,
onde está a lista de registros e propõe um esqueleto de EndpointSpec para revisão humana.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

_ESTATICO = re.compile(r"\.(js|css|png|jpe?g|gif|svg|ico|woff2?|ttf|map)(\?|$)", re.IGNORECASE)
_PARAMS_PAGINA = ("pagina", "page", "numeroPagina", "pageNumber", "p")
_PARAMS_TAMANHO = ("tamanhoPagina", "pageSize", "size", "limit", "length", "rows", "per_page")
_PARAMS_OFFSET = ("start", "offset", "skip", "inicio")


@dataclass
class Candidato:
    metodo: str
    url: str
    host: str
    chamadas: int = 0
    status: set[int] = field(default_factory=set)
    params: set[str] = field(default_factory=set)
    params_corpo: set[str] = field(default_factory=set)
    corpo_tipo: str | None = None
    exemplo_params: dict[str, str] = field(default_factory=dict)
    exemplo_corpo: dict[str, Any] = field(default_factory=dict)
    registros_em: str | None = None
    qtd_registros: int = 0
    campos: list[str] = field(default_factory=list)
    bytes_resposta: int = 0

    @property
    def pontuacao(self) -> int:
        """Heurística: listas de objetos com muitos campos são as APIs de dados que interessam."""
        return (self.qtd_registros > 0) * 100 + len(self.campos) * 3 + min(self.chamadas, 10)


def _texto_resposta(conteudo: dict[str, Any]) -> str | None:
    txt = conteudo.get("text")
    if txt is None:
        return None
    if conteudo.get("encoding") == "base64":
        try:
            return base64.b64decode(txt).decode("utf-8", "replace")
        except ValueError:
            return None
    return txt


def localizar_lista(obj: Any, prefixo: str = "", profundidade: int = 0) -> tuple[str | None, list | None]:
    """Acha a maior lista de objetos no JSON (até 4 níveis). Retorna (caminho, lista)."""
    if isinstance(obj, list) and obj and all(isinstance(i, dict) for i in obj[:5]):
        return (prefixo or None), obj
    melhor: tuple[str | None, list | None] = (None, None)
    if isinstance(obj, dict) and profundidade < 4:
        for k, v in obj.items():
            cam, lst = localizar_lista(v, f"{prefixo}.{k}" if prefixo else k, profundidade + 1)
            if lst is not None and (melhor[1] is None or len(lst) > len(melhor[1])):
                melhor = (cam, lst)
    return melhor


def _corpo_requisicao(req: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    post = req.get("postData") or {}
    mime = (post.get("mimeType") or "").lower()
    if "json" in mime and post.get("text"):
        try:
            dados = json.loads(post["text"])
            return "json", dados if isinstance(dados, dict) else {"_": dados}
        except ValueError:
            return "json", {}
    if post.get("params"):
        return "form", {p["name"]: p.get("value", "") for p in post["params"]}
    if "x-www-form-urlencoded" in mime and post.get("text"):
        return "form", dict(parse_qsl(post["text"], keep_blank_values=True))
    return None, {}


def analisar(caminho_har: str | Path, host: str | None = None) -> list[Candidato]:
    har = json.loads(Path(caminho_har).read_text(encoding="utf-8"))
    grupos: dict[tuple[str, str], Candidato] = {}
    for entrada in har.get("log", {}).get("entries", []):
        req, resp = entrada.get("request", {}), entrada.get("response", {})
        url = req.get("url", "")
        partes = urlsplit(url)
        if _ESTATICO.search(partes.path) or (host and host not in (partes.hostname or "")):
            continue
        conteudo = resp.get("content") or {}
        texto = _texto_resposta(conteudo)
        if not texto:
            continue
        try:
            corpo = json.loads(texto)
        except ValueError:
            continue  # só nos interessam respostas JSON (HTML fica para scraping, último recurso)

        base = f"{partes.scheme}://{partes.netloc}{partes.path}"
        chave = (req.get("method", "GET").upper(), base)
        c = grupos.get(chave) or Candidato(metodo=chave[0], url=base, host=partes.hostname or "")
        grupos[chave] = c
        c.chamadas += 1
        c.status.add(resp.get("status", 0))
        qs = dict(parse_qsl(partes.query, keep_blank_values=True))
        c.params |= set(qs)
        c.exemplo_params = c.exemplo_params or qs
        tipo, dados_corpo = _corpo_requisicao(req)
        if tipo:
            c.corpo_tipo = tipo
            c.params_corpo |= set(dados_corpo)
            c.exemplo_corpo = c.exemplo_corpo or dados_corpo
        cam, lista = localizar_lista(corpo)
        if lista is not None and len(lista) >= c.qtd_registros:
            c.registros_em, c.qtd_registros = cam, len(lista)
            c.campos = list(lista[0].keys())
        c.bytes_resposta = max(c.bytes_resposta, len(texto))
    return sorted(grupos.values(), key=lambda c: c.pontuacao, reverse=True)


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_") or "x"


def esqueleto_spec(c: Candidato) -> dict[str, Any]:
    """Rascunho de EndpointSpec. Sempre sai como status a_mapear/ativo false para revisão humana."""
    todos = c.params | c.params_corpo
    em = "corpo" if c.params_corpo and not c.params else "params"
    paginacao: dict[str, Any] = {"tipo": "nenhuma"}
    p_pag = next((p for p in _PARAMS_PAGINA if p in todos), None)
    p_off = next((p for p in _PARAMS_OFFSET if p in todos), None)
    p_tam = next((p for p in _PARAMS_TAMANHO if p in todos), None)
    if p_pag:
        paginacao = {"tipo": "pagina", "parametro": p_pag, "inicio": 1}
    elif p_off:
        paginacao = {"tipo": "offset", "parametro": p_off, "inicio": 0}
    if p_tam and paginacao["tipo"] != "nenhuma":
        paginacao |= {"tamanho_parametro": p_tam, "tamanho": 100, "em": em}

    caminho_url = [p for p in urlsplit(c.url).path.split("/") if p]
    spec: dict[str, Any] = {
        "id": f"{_slug(c.host.split('.')[0])}.{_slug('_'.join(caminho_url[-2:]) or 'raiz')}",
        "portal": c.host,
        "descricao": "TODO: o que este endpoint devolve",
        "status": "a_mapear",
        "ativo": False,
        "metodo": c.metodo,
        "url": c.url,
        "params": {k: v for k, v in c.exemplo_params.items() if k not in (p_pag, p_off, p_tam)},
        "registros_em": c.registros_em,
        "chave": None,
        "mapeamento": {campo: campo for campo in c.campos[:30]},
        "paginacao": paginacao,
        "notas": f"Gerado a partir de HAR: {c.chamadas} chamada(s), {c.qtd_registros} registros na amostra.",
    }
    if c.corpo_tipo:
        spec["corpo_tipo"] = c.corpo_tipo
        spec["corpo"] = {k: v for k, v in c.exemplo_corpo.items() if k not in (p_pag, p_off, p_tam)}
    return spec
