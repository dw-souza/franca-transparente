"""Configuração lida de variáveis de ambiente (ver .env.example na raiz do repositório)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from franca_collectors.pncp.dominios import MODALIDADES

PACOTE_DIR = Path(__file__).resolve().parent
ENDPOINTS_DIR_PADRAO = PACOTE_DIR.parent / "endpoints"


def _lista(valor: str | None) -> tuple[str, ...]:
    return tuple(p.strip() for p in (valor or "").split(",") if p.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str | None = None
    pncp_base_url: str = "https://pncp.gov.br/api/consulta"
    codigo_ibge: str = "3516200"  # Franca-SP
    # CNPJs de órgãos de Franca consultados em /v1/contratos (que não filtra por município).
    # Os CNPJs que aparecem nas contratações do município são somados automaticamente.
    cnpjs_orgaos: tuple[str, ...] = ("47970769000104",)  # Prefeitura Municipal de Franca
    modalidades: tuple[int, ...] = field(default_factory=lambda: tuple(MODALIDADES))
    janela_dias: int = 30
    http_timeout: float = 30.0
    http_delay: float = 0.5  # pausa entre requisições: a API do PNCP devolve 429 em rajadas
    http_retries: int = 5
    user_agent: str = "PainelTransparenciaFranca/0.1 (+https://github.com/dw-souza/franca-transparente)"
    endpoints_dir: Path = ENDPOINTS_DIR_PADRAO

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ.get
        padrao = cls()
        modalidades = _lista(e("PNCP_MODALIDADES"))
        return cls(
            database_url=e("DATABASE_URL") or None,
            pncp_base_url=(e("PNCP_BASE_URL") or padrao.pncp_base_url).rstrip("/"),
            codigo_ibge=e("CODIGO_IBGE") or padrao.codigo_ibge,
            cnpjs_orgaos=_lista(e("ORGAOS_CNPJ")) or padrao.cnpjs_orgaos,
            modalidades=tuple(int(m) for m in modalidades) or padrao.modalidades,
            janela_dias=int(e("PNCP_JANELA_DIAS") or padrao.janela_dias),
            http_timeout=float(e("HTTP_TIMEOUT_SEGUNDOS") or padrao.http_timeout),
            http_delay=float(e("HTTP_DELAY_SEGUNDOS") or padrao.http_delay),
            http_retries=int(e("HTTP_RETRIES") or padrao.http_retries),
            user_agent=e("HTTP_USER_AGENT") or padrao.user_agent,
            endpoints_dir=Path(e("ENDPOINTS_DIR") or padrao.endpoints_dir),
        )
