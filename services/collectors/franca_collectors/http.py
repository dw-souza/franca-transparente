"""Sessão HTTP educada: retries com backoff, respeito a Retry-After e intervalo mínimo entre chamadas."""

from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def criar_sessao(user_agent: str, retries: int = 5, backoff: float = 1.5) -> requests.Session:
    sessao = requests.Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adaptador = HTTPAdapter(max_retries=retry)
    sessao.mount("https://", adaptador)
    sessao.mount("http://", adaptador)
    sessao.headers.update({"User-Agent": user_agent, "Accept": "application/json"})
    return sessao


class Throttle:
    """Garante um intervalo mínimo entre requisições ao mesmo serviço."""

    def __init__(self, intervalo: float):
        self.intervalo = max(0.0, intervalo)
        self._ultimo = 0.0

    def esperar(self) -> None:
        if not self.intervalo:
            return
        restante = self.intervalo - (time.monotonic() - self._ultimo)
        if restante > 0:
            time.sleep(restante)
        self._ultimo = time.monotonic()


class RespostaInvalida(RuntimeError):
    """A fonte respondeu algo que não é o JSON esperado (página de desafio, HTML de erro...).

    O coletor falha fechado: nunca tenta contornar CAPTCHA/WAF nem grava dado duvidoso.
    """
