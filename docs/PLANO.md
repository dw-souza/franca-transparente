# Plano de trabalho

Checklist vivo do Painel de Transparência Cívica de Franca-SP. Marque `[x]` ao concluir e anote a data quando
ajudar. Itens com **(MVP)** fazem parte da primeira versão pública: radar de licitações e contratos, Diário
Oficial inteligente e painel web.

Legenda: `[x]` feito · `[ ]` a fazer · `[~]` em andamento ou parcial · 🔒 depende de decisão ou de terceiros

---

## Fase 0 — Fundação

- [x] Monorepo: `database/`, `services/collectors`, `services/api`, `apps/web`, `docs/`
- [x] Migrations 000001–000009 (órgãos, fornecedores, licitações, contratos, diários, alertas, coleta, views)
- [x] `docker-compose.yml` (Postgres 16 + migrate + collector) e `.env.example`
- [x] Ambiente local validado no Mac: Docker, `.venv` Python, Go 1.25 via mise (2026-10-28)
- [x] Senha forte do Postgres e User-Agent identificado no `.env`
- [x] Testes: 43 em Python (unitários + integração com banco descartável) e Go; `make test` (2026-10-28)
- [x] Cobertura dos coletores em 91%; `ruff` limpo
- [x] Primeiro commit e repositório remoto: `github.com/dw-souza/franca-transparente` (2026-10-28)
- [x] CI em `.github/workflows/ci.yml` (Python + ruff + Postgres, Go + gofmt/vet/test), verde no GitHub (2026-10-28)
- [x] `LICENSE` (AGPL-3.0, texto oficial) e `CONTRIBUTING.md` (2026-10-28)

## Fase 1 — Radar PNCP (MVP)

- [x] Coletor de contratações e contratos, incremental e idempotente
- [x] Campos conferidos contra a API real (2026-10-28)
- [x] Órgãos de Franca no PNCP identificados: Prefeitura, Câmara, Faculdade de Direito, Uni-FACEF
- [x] Carga histórica desde 2023-04-01: 3.075 licitações e 1.483 contratos, todos vinculados à licitação (2026-10-28).
  Franca só passa a publicar no PNCP em volume a partir de 2024.
- [x] Órgãos descobertos na carga longa e somados a `ORGAOS_CNPJ`: FEAC e SASSOM (6 no total)
- [x] Coleta diária no GitHub Actions (`.github/workflows/coleta.yml`, 06:00 de Brasília): migrations, incremental
  do PNCP e radar de propostas abertas, gravando no Neon (2026-10-29)
- [x] Histórico recarregado no Neon desde 2023-04-01: 3.121 licitações e 1.484 contratos, sem erros (2026-10-29)
- [x] Itens e resultados por item (migration 000011, `pncp itens`, view `vw_precos_itens`): fila por compra,
  ~17 itens por compra, limite de 60 min por dia no workflow até completar o histórico (2026-10-29)
- [x] Termos aditivos: Franca não publica no PNCP (15 maiores contratos de 2024 sem termos); vêm do EddyData
  (`contrato-aditamentos`, Fase 2)
- [x] Valores negativos da fonte aceitos no banco (migration 000010); o PNCP publica erros como estimado = -36
- [x] Qualidade de dado (migration 000012): `vw_licitacoes_qualidade` e `vw_contratos_qualidade` com natureza
  (receita/despesa) e alertas (valor negativo/zero/atípico, homologado divergente, vigência invertida);
  somas por modalidade sem negativos (2026-10-29)

## Fase 2 — Portal da Transparência (EddyData)

- [x] Portal real identificado: `eddydata.franca.sp.gov.br/transparencia` (o domínio antigo do backlog não existe)
- [x] API interna e recursos mapeados a partir do bundle JS (ver `services/collectors/endpoints/franca.yaml`)
- [x] Cadeia SSL incompleta diagnosticada (falta o intermediário Certum DV TLS G2 R39 CA)
- [x] Decidido: reproduzir a assinatura do token público (2026-10-28)
- [x] Sonda `scripts/sonda_eddydata.py` validou token, assinatura e listagens (2026-10-28)
- [ ] Registrar a exceção à "falha fechada" em `http.py` e liberar a regra de permissão no Claude Code (ou o usuário roda as coletas)
- [~] Bundle de CA com o intermediário (feito na sonda; falta versionar no coletor; nunca `verify=False`)
- [ ] Autenticação pública (token + cabeçalhos `agora`/`codigo`) no executor REA, renovando o token a cada 30 min
- [ ] Mapear relações que trazem a secretaria (ficha → unidade executora) e os filtros de `contrato-aditamentos`
- [ ] Lista branca de campos por recurso (favorecido e órgão trazem dados pessoais e `chave_acesso`)
- [ ] Specs YAML ativas: `licitacoes`, `contratos`, `contrato-aditamentos`, `empenhos`, `liquidacoes`, `pagamentos`, `favorecidos`
- [ ] Tabela de despesas (empenho → liquidação → pagamento) e migration correspondente
- [ ] Cruzamento contrato PNCP × empenhos/pagamentos (valor contratado × valor pago)
- [ ] Secretaria real de cada despesa, substituindo a aproximação por `unidade_nome`

## Fase 3 — API Go (MVP)

- [x] Esqueleto com `/healthz`, desligamento gracioso e teste
- [ ] Conexão pgx com pool e configuração por `DATABASE_URL`; `docker-compose` com o serviço `api`
- [ ] Resolver o conflito da porta 8080 local (ou `API_PORT=8081`)
- [ ] `GET /painel/resumo` (`vw_painel_resumo`)
- [ ] `GET /licitacoes` com filtros (unidade, modalidade, status, faixa de valor, período) e busca full-text
- [ ] `GET /licitacoes/abertas` e `GET /licitacoes/{id}`
- [ ] `GET /contratos` com os mesmos filtros e `GET /contratos/{id}`
- [ ] `GET /fornecedores` (busca por nome/CNPJ) e `GET /fornecedores/{id}` com histórico e agrupamento por `cnpj_raiz`
- [ ] Rankings: por fornecedor, por unidade/secretaria, por modalidade
- [ ] LGPD: CPF de pessoa física mascarado em todas as respostas (com teste)
- [ ] Paginação, CORS (`API_CORS_ORIGINS`), limites de taxa e cache HTTP
- [ ] Documentação OpenAPI
- [ ] Testes de integração dos repositórios contra Postgres

## Fase 4 — Painel web Next.js (MVP)

- [ ] Projeto Next.js (App Router) + TypeScript + Tailwind + shadcn/ui em `apps/web`
- [ ] Início: cards (total contratado no ano, contratos, licitações abertas, fornecedores) e rankings
- [ ] Licitações e contratos: tabela com filtros, busca e paginação
- [ ] Modal/página de detalhe com resumo em linguagem simples e link para a fonte
- [ ] Página do fornecedor
- [ ] Acessibilidade (WCAG AA), responsivo, modo escuro
- [ ] Página "Sobre os dados": fontes, atualização, limitações e metodologia

## Fase 5 — Diário Oficial inteligente (MVP)

- [x] Verificado que o Querido Diário não cobre Franca (2026-10-28)
- [ ] Localizar o portal oficial do DOMF e o padrão de publicação das edições
- [ ] Spider de edições (data, número, URL do PDF) para `diarios_oficiais`, com carga histórica
- [ ] Extração de texto com `pdfplumber` e OCR para edições escaneadas
- [ ] Segmentação em atos (`diario_atos`): portarias, extratos de contrato, homologações, nomeações
- [ ] Extração estruturada com LLM (Structured Outputs) e validação por schema
- [ ] Vínculo dos atos com licitações/contratos do banco
- [ ] Busca full-text nos atos via API e tela no painel

## Fase 6 — Resumos por IA

- [ ] Worker que consome a fila `resumo_ia IS NULL` de licitações e contratos
- [ ] Prompt e schema de saída; registro de modelo e data (`resumo_ia_modelo`, `resumo_ia_em`)
- [ ] Controle de custo (lote, limite diário) e reprocessamento quando o objeto muda (já previsto no upsert)
- [ ] Revisão amostral da qualidade dos resumos

## Fase 7 — Alertas

- [ ] Assinatura por e-mail com confirmação (double opt-in) e descadastro
- [ ] Regras: palavra-chave, órgão/unidade, modalidade, faixa de valor
- [ ] Disparo deduplicado via `alertas_disparos`; provedor de e-mail
- [ ] LGPD: base legal, retenção e exclusão dos contatos

## Fase 8 — Sinais de risco (inspirado no Serenata de Amor)

- [ ] Fracionamento de despesa (várias dispensas do mesmo objeto/fornecedor em curto prazo)
- [ ] Concentração de fornecedores por unidade e por `cnpj_raiz`
- [ ] Fornecedor recém-aberto ou com situação cadastral irregular (enriquecimento pela Receita Federal)
- [ ] Inconsistências de vigência e valores fora da curva
- [ ] Contratado × pago (depende da Fase 2)
- [ ] Linguagem cuidadosa no painel: "sinal para checar", nunca acusação

## Fase 9 — Publicação e operação

- [ ] Escolha de hospedagem e estimativa de custo
- [ ] Deploy de banco, API, web e rotinas de coleta
- [ ] Backups do Postgres e teste de restauração
- [ ] Monitoramento das coletas (falhas, volume anômalo, mudanças de schema na fonte)
- [ ] Domínio, HTTPS e política de privacidade

---

## Decisões pendentes

- 🔒 Provedor e modelo de LLM para resumos e extração do DOMF (Fases 5 e 6)
- [~] Hospedagem: banco no Neon (plano Free, 1 GB, via Vercel); API, web e destino de longo prazo ainda abertos (Fase 9)
