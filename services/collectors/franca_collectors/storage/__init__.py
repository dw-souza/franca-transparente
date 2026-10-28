from __future__ import annotations

from franca_collectors.storage.arquivo import ConsoleSink, JsonlSink, MemoriaSink
from franca_collectors.storage.base import Resultado, Sink


def criar_sink(tipo: str, database_url: str | None = None, arquivo: str | None = None) -> Sink:
    if tipo == "console":
        return ConsoleSink()
    if tipo == "jsonl":
        return JsonlSink(arquivo or "dados/coleta.jsonl")
    if tipo == "postgres":
        if not database_url:
            raise SystemExit("DATABASE_URL não definido (veja .env.example)")
        from franca_collectors.storage.postgres import PostgresSink

        return PostgresSink(database_url)
    raise SystemExit(f"saída desconhecida: {tipo}")


__all__ = ["ConsoleSink", "JsonlSink", "MemoriaSink", "Resultado", "Sink", "criar_sink"]
