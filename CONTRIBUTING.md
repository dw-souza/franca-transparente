# Como contribuir

Obrigado pelo interesse no Painel de Transparência Cívica de Franca-SP. O plano de trabalho, com o que está
feito e o que falta, fica em [`docs/PLANO.md`](docs/PLANO.md): é o melhor lugar para escolher uma tarefa.

## Ambiente local

Requisitos: Docker, Python 3.11+ e Go (versão em `services/api/go.mod`).

```bash
cp .env.example .env                 # troque a senha e o contato do User-Agent
make up                              # Postgres 16 + migrations
python3 -m venv .venv && .venv/bin/pip install -e "services/collectors[postgres,dev]"
make test                            # Python (unitários + integração) e Go
```

Os testes de integração criam um banco descartável (`franca_teste_<pid>`) no Postgres apontado por
`TEST_DATABASE_URL` ou `DATABASE_URL` e o apagam no fim. Sem banco disponível, eles são pulados.

## Antes de abrir um PR

- `make test` passando e `ruff check services/collectors` limpo; o CI roda os dois.
- Mudança de schema: nova migration `NNNNNN_nome.up.sql` com o `.down.sql` correspondente. Os testes aplicam
  up → down → up, então o down precisa funcionar.
- Código e comentários em português, seguindo o estilo do arquivo ao redor.
- Marque no `docs/PLANO.md` os itens que o PR conclui.

## Regras para coletar dados

- Seja educado com as fontes: intervalo entre requisições, retry com backoff e User-Agent com contato.
- Guarde o registro original (`payload_bruto`) para auditoria e reprocessamento.
- Falha fechada: se a fonte devolver algo inesperado (HTML no lugar de JSON, página de desafio), a coleta para
  em vez de gravar dado duvidoso. A exceção documentada é o acesso anônimo do portal EddyData da Prefeitura,
  que reproduz o que a própria página pública faz (ver `services/collectors/endpoints/franca.yaml`).
- Nunca desligue a verificação TLS (`verify=False`); se a cadeia estiver incompleta, inclua o intermediário.

## Dados pessoais (LGPD)

- CPF de fornecedor pessoa física e contatos de quem assina alertas são dados pessoais: a API pública os mascara.
- Colete só uma lista branca de campos. Objetos como `favorecido` do portal municipal trazem dados bancários e
  pessoais que não devem entrar no banco.
- Amostras e capturas (`dados/`, `*.har`) ficam fora do git; não as anexe a issues ou PRs.

## Licença

Ao contribuir, você concorda que sua contribuição seja distribuída sob a [AGPL-3.0](LICENSE).
