# franca-collectors

Coletores do Painel de Transparência de Franca-SP: PNCP (pronto), endpoints mapeados via REA (estrutura
pronta, endpoints a mapear) e Diário Oficial (próxima etapa).

```bash
pip install -e ".[postgres,dev]"
python -m franca_collectors --help
python -m franca_collectors pncp coletar --desde 2026-10-01 --ate 2026-10-27   # console
python -m franca_collectors rea listar
pytest
```

Configuração por variáveis de ambiente: ver `.env.example` na raiz. Detalhes de arquitetura no README raiz
e o fluxo de mapeamento em `docs/rea.md`.
