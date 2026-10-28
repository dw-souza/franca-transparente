"""Linha de comando: `python -m franca_collectors ...` ou `franca-collect ...`.

Exemplos:
  franca-collect pncp coletar --desde 2026-01-01 --ate 2026-01-31            # exibe no console
  franca-collect pncp coletar --incremental --saida postgres                  # rotina diária
  franca-collect pncp abertas --dias 30 --saida jsonl --arquivo abertas.jsonl
  franca-collect rea listar
  franca-collect rea sincronizar                                             # YAML → endpoints_mapeados
  franca-collect rea executar transparencia.despesas.empenhos --desde 2026-10-01
  franca-collect rea har captura.har --host transparencia.franca.sp.gov.br --yaml rascunho.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

import yaml

from franca_collectors.config import Settings
from franca_collectors.http import criar_sessao
from franca_collectors.pncp.client import PNCPClient
from franca_collectors.pncp.pipeline import ColetorPNCP
from franca_collectors.storage import criar_sink


def _data(s: str) -> date:
    return date.fromisoformat(s)


def _args_saida(p: argparse.ArgumentParser) -> None:
    p.add_argument("--saida", choices=("console", "jsonl", "postgres"), default="console")
    p.add_argument("--arquivo", help="arquivo de saída para --saida jsonl")


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="franca-collect", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="grupo", required=True)

    pncp = sub.add_parser("pncp", help="Portal Nacional de Contratações Públicas").add_subparsers(
        dest="acao", required=True)
    c = pncp.add_parser("coletar", help="contratações e contratos publicados num período")
    c.add_argument("--desde", type=_data, default=date.today() - timedelta(days=7))
    c.add_argument("--ate", type=_data, default=date.today())
    c.add_argument("--incremental", action="store_true",
                   help="retoma da última janela com sucesso registrada no destino")
    c.add_argument("--modalidades", help="códigos separados por vírgula (padrão: todas)")
    c.add_argument("--sem-contratos", action="store_true")
    c.add_argument("--todas-esferas", action="store_true",
                   help="inclui unidades estaduais/federais sediadas no município")
    _args_saida(c)
    a = pncp.add_parser("abertas", help="radar: licitações recebendo propostas")
    a.add_argument("--dias", type=int, default=60, help="encerramento até N dias à frente")
    _args_saida(a)

    rea = sub.add_parser("rea", help="endpoints mapeados por engenharia reversa").add_subparsers(
        dest="acao", required=True)
    rea.add_parser("listar")
    rea.add_parser("validar", help="valida todos os YAML (inclusive modelos)")
    rea.add_parser("sincronizar", help="espelha os YAML na tabela endpoints_mapeados")
    e = rea.add_parser("executar")
    e.add_argument("endpoint_id")
    e.add_argument("--desde", type=_data)
    e.add_argument("--ate", type=_data)
    e.add_argument("--forcar", action="store_true", help="executa mesmo se ativo: false")
    _args_saida(e)
    h = rea.add_parser("har", help="triagem de um arquivo HAR")
    h.add_argument("arquivo")
    h.add_argument("--host")
    h.add_argument("--top", type=int, default=15)
    h.add_argument("--yaml", help="grava rascunhos de spec dos candidatos com registros")
    return ap


def _cmd_pncp(args, cfg: Settings) -> int:
    sessao = criar_sessao(cfg.user_agent, cfg.http_retries)
    cliente = PNCPClient(sessao, cfg.pncp_base_url, cfg.http_timeout, cfg.http_delay)
    modalidades = tuple(int(m) for m in args.modalidades.split(",")) if getattr(args, "modalidades", None) \
        else cfg.modalidades
    with criar_sink(args.saida, cfg.database_url, args.arquivo) as sink:
        coletor = ColetorPNCP(cliente, sink, cfg.codigo_ibge, cfg.cnpjs_orgaos, modalidades, cfg.janela_dias,
                              esferas=None if getattr(args, "todas_esferas", False) else ("M",))
        if args.acao == "abertas":
            stats = coletor.coletar_propostas_abertas(date.today() + timedelta(days=args.dias))
            print(f"\nPropostas abertas: {stats}", file=sys.stderr)
            return 0
        inicio = coletor.inicio_incremental(args.desde) if args.incremental else args.desde
        resumo = coletor.coletar(inicio, args.ate, incluir_contratos=not args.sem_contratos)
        print(f"\nPNCP {cfg.codigo_ibge} {inicio} → {args.ate} ({resumo.requisicoes} requisições)\n"
              f"  contratações: {resumo.contratacoes}\n  contratos:    {resumo.contratos}\n"
              f"  órgãos (CNPJ): {', '.join(sorted(resumo.cnpjs_orgaos))}", file=sys.stderr)
        return 1 if (resumo.contratacoes.erros or resumo.contratos.erros) else 0


def _cmd_rea(args, cfg: Settings) -> int:
    from franca_collectors.rea import har
    from franca_collectors.rea.runner import coletar_endpoint
    from franca_collectors.rea.spec import carregar_specs

    if args.acao == "har":
        candidatos = har.analisar(args.arquivo, args.host)
        for c in candidatos[: args.top]:
            print(f"{c.metodo:4} {c.url}\n     chamadas={c.chamadas} status={sorted(c.status)} "
                  f"params={sorted(c.params)} corpo={sorted(c.params_corpo)}\n"
                  f"     registros_em={c.registros_em!r} n={c.qtd_registros} campos={c.campos[:12]}")
        if args.yaml:
            rascunhos = [har.esqueleto_spec(c) for c in candidatos[: args.top] if c.qtd_registros]
            with open(args.yaml, "w", encoding="utf-8") as f:
                yaml.safe_dump({"endpoints": rascunhos}, f, allow_unicode=True, sort_keys=False)
            print(f"\n{len(rascunhos)} rascunho(s) em {args.yaml}", file=sys.stderr)
        return 0

    specs = carregar_specs(cfg.endpoints_dir, incluir_modelos=args.acao == "validar")
    if args.acao in ("listar", "validar"):
        for s in specs:
            print(f"{'●' if s.ativo else '○'} {s.id:45} {s.status:12} {s.metodo:4} {s.url}")
        print(f"\n{len(specs)} endpoint(s) válidos em {cfg.endpoints_dir}", file=sys.stderr)
        return 0
    if args.acao == "sincronizar":
        with criar_sink("postgres", cfg.database_url) as sink:
            for s in specs:
                sink.sincronizar_endpoint(s.model_dump(mode="json"), s.sha256())
        print(f"{len(specs)} endpoint(s) sincronizados", file=sys.stderr)
        return 0
    if args.acao == "executar":
        spec = next((s for s in specs if s.id == args.endpoint_id), None)
        if spec is None:
            print(f"endpoint não encontrado: {args.endpoint_id}", file=sys.stderr)
            return 2
        if not spec.ativo and not args.forcar:
            print(f"{spec.id} está inativo (status={spec.status}); use --forcar para testar", file=sys.stderr)
            return 2
        with criar_sink(args.saida, cfg.database_url, args.arquivo) as sink:
            if args.saida == "postgres":
                sink.sincronizar_endpoint(spec.model_dump(mode="json"), spec.sha256())
            stats = coletar_endpoint(criar_sessao(cfg.user_agent, cfg.http_retries), spec, sink,
                                     args.desde, args.ate)
        print(f"{spec.id}: {stats}", file=sys.stderr)
        return 1 if stats.erros else 0
    return 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    cfg = Settings.from_env()
    return _cmd_pncp(args, cfg) if args.grupo == "pncp" else _cmd_rea(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
