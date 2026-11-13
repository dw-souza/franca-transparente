#!/usr/bin/env bash
# Prepara uma VM Ubuntu (22.04/24.04, ARM ou x86) no Brasil como runner do job "eddydata" do workflow Coleta.
#
# O portal municipal (rede da Prefeitura) não aceita conexões dos datacenters do GitHub, e pode recusar também
# IPs de datacenter brasileiros: por isso o primeiro passo é testar a conexão e parar se ela não abrir.
#
# Uso, na VM:
#   bash runner_vm.sh <TOKEN>
# O token de registro vale 1 hora. Gere no seu Mac com:
#   gh api -X POST repos/dw-souza/franca-transparente/actions/runners/registration-token --jq .token
# ou em Settings → Actions → Runners → New self-hosted runner.
set -euo pipefail

REPO_URL="https://github.com/dw-souza/franca-transparente"
TOKEN="${1:?informe o token de registro do runner (veja o cabeçalho deste script)}"
PORTAL="eddydata-api.franca.sp.gov.br"

echo "== 1. Conexão com o portal municipal a partir desta VM"
# time_connect > 0 = a conexão TCP abriu (mesmo que o TLS falhe depois pela cadeia incompleta do servidor)
CONECTOU="$(curl -s -o /dev/null --connect-timeout 10 -m 20 -w '%{time_connect}' "https://$PORTAL/" || true)"
if [ -n "$CONECTOU" ] && [ "$CONECTOU" != "0.000000" ]; then
  echo "   ok: $PORTAL:443 abre daqui"
else
  echo "   FALHOU: esta VM não alcança $PORTAL:443."
  echo "   O firewall da Prefeitura também bloqueia este datacenter; não adianta instalar o runner aqui."
  exit 1
fi

echo "== 2. Pacotes"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip git curl tar

echo "== 3. Runner do GitHub Actions"
case "$(uname -m)" in
  x86_64) ARQ=x64 ;;
  aarch64|arm64) ARQ=arm64 ;;
  *) echo "arquitetura não suportada: $(uname -m)"; exit 1 ;;
esac
VERSAO="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
  | grep -m1 '"tag_name"' | sed -E 's/.*"v([^"]+)".*/\1/')"
mkdir -p "$HOME/actions-runner" && cd "$HOME/actions-runner"
curl -fsSL -o runner.tgz \
  "https://github.com/actions/runner/releases/download/v$VERSAO/actions-runner-linux-$ARQ-$VERSAO.tar.gz"
tar xzf runner.tgz && rm runner.tgz
./config.sh --unattended --url "$REPO_URL" --token "$TOKEN" \
  --labels brasil --name "franca-br-$(hostname)" --replace

echo "== 4. Serviço (sobe sozinho após reinício)"
sudo ./svc.sh install "$USER"
sudo ./svc.sh start
sudo ./svc.sh status | head -5

echo
echo "Pronto. Confira em $REPO_URL/settings/actions/runners (status Idle) e dispare Actions → Coleta → Run workflow."
