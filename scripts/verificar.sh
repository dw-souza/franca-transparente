#!/usr/bin/env bash
# Reexecuta no seu Mac as verificações que falharam ou não puderam rodar no ambiente da Claude.
# Uso: ./scripts/verificar.sh        (a saída também vai para verificacao.log, que a Claude consegue ler)
set -u
cd "$(dirname "$0")/.."
exec > >(tee verificacao.log) 2>&1
ok()    { echo "  ✅ $*"; }
falha() { echo "  ❌ $*"; }
dias()  { date -v"$1"d +%Y%m%d 2>/dev/null || date -d "$1 days" +%Y%m%d; }   # macOS | Linux
echo "verificação $(date '+%F %T') em $(uname -sm)"

echo "== 1. Ferramentas"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then PY=$c; break; fi
done
[ -n "$PY" ] && ok "Python: $($PY --version)" || falha "Python >= 3.11 não encontrado (brew install python@3.12)"
for t in docker go; do command -v $t >/dev/null && ok "$t: $($t --version 2>&1 | head -1)" || falha "$t ausente"; done
docker info >/dev/null 2>&1 && ok "Docker daemon rodando" || falha "Docker daemon parado (abra o Docker Desktop)"

echo "== 2. API do PNCP ao vivo (antes: bloqueada por allowlist)"
URL="https://pncp.gov.br/api/consulta/v1/contratacoes/proposta?dataFinal=$(dias +60)&codigoMunicipioIbge=3516200&pagina=1&tamanhoPagina=10"
code=$(curl -sS -m 30 -o /tmp/pncp_amostra.json -w "%{http_code}" "$URL") || code="erro"
echo "  HTTP $code"
if [ "$code" = 200 ] && [ -n "$PY" ]; then
  $PY - <<'PYEOF'
import json
d = json.load(open("/tmp/pncp_amostra.json"))
regs = d.get("data") or []
print(f"  totalRegistros={d.get('totalRegistros')} totalPaginas={d.get('totalPaginas')} paginasRestantes={d.get('paginasRestantes')}")
esperados = ["numeroControlePNCP","anoCompra","sequencialCompra","numeroCompra","processo","objetoCompra",
  "modalidadeId","modalidadeNome","modoDisputaNome","srp","valorTotalEstimado","valorTotalHomologado",
  "dataPublicacaoPncp","dataAberturaProposta","dataEncerramentoProposta","situacaoCompraId",
  "situacaoCompraNome","linkSistemaOrigem","dataAtualizacaoGlobal","orgaoEntidade","unidadeOrgao","amparoLegal"]
if regs:
    r = regs[0]
    faltando = [k for k in esperados if k not in r]
    print("  ✅ todos os campos esperados presentes" if not faltando else f"  ❌ campos ausentes: {faltando}")
    print(f"  campos extras: {sorted(set(r) - set(esperados))}")
    print(f"  orgaoEntidade={sorted((r.get('orgaoEntidade') or {}).keys())}")
    print(f"  unidadeOrgao={sorted((r.get('unidadeOrgao') or {}).keys())}")
    print(f"  exemplo: {r.get('numeroControlePNCP')} | {(r.get('objetoCompra') or '')[:80]}")
else:
    print("  (nenhuma licitação aberta agora; campos não conferidos)")
PYEOF
elif [ "$code" = 204 ]; then echo "  (204: nada aberto agora)"; fi

echo "== 3. Ambiente Python com psycopg + testes (antes: PyPI bloqueado)"
if [ -n "$PY" ]; then
  [ -d .venv ] || $PY -m venv .venv
  .venv/bin/pip install -q --upgrade pip >/dev/null
  if .venv/bin/pip install -q -e "services/collectors[postgres,dev]"; then
    ok "dependências instaladas ($(.venv/bin/python -c 'import psycopg; print("psycopg", psycopg.__version__)'))"
    (cd services/collectors && ../../.venv/bin/python -m pytest -q 2>&1 | tail -3)
  else falha "pip install falhou"; fi
fi

echo "== 4. Docker: Postgres 16 + migrations (antes: sem daemon; tag do migrate não conferida)"
[ -f .env ] || { cp .env.example .env; echo "  .env criado a partir do exemplo"; }
if docker compose up -d db migrate 2>&1 | tail -5; then
  for i in $(seq 1 30); do st=$(docker compose ps -a migrate --format '{{.State}}' 2>/dev/null); [ "$st" = exited ] && break; sleep 2; done
  docker compose logs migrate 2>&1 | tail -4
  rc=$(docker compose ps -a migrate --format '{{.ExitCode}}' 2>/dev/null)
  [ "$rc" = 0 ] && ok "migrations aplicadas" || falha "migrate saiu com código $rc"
fi

echo "== 5. Coleta real curta (7 dias) no Postgres via psycopg (antes: nunca testado com psycopg)"
if [ -x .venv/bin/python ] && [ "${rc:-1}" = 0 ]; then
  set -a; . ./.env; set +a
  (cd services/collectors && ../../.venv/bin/python -m franca_collectors pncp coletar \
      --desde "$(date -v-7d +%F 2>/dev/null || date -d '-7 days' +%F)" --saida postgres 2>&1 | tail -8)
  docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
    "select (select count(*) from licitacoes) licitacoes, (select count(*) from contratos) contratos,
            (select count(*) from fornecedores) fornecedores, (select count(*) from orgaos) orgaos;" \
    -c "select coletor, status, registros_lidos, registros_gravados, registros_erro from execucoes_coleta order by id desc limit 4;"
fi
echo "== fim. Log em verificacao.log"
