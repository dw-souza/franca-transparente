# apps/web

Painel cívico em Next.js (App Router) + TypeScript + Tailwind + shadcn/ui. A iniciar depois da API.

Telas do MVP:

- **Início**: cards de `vw_painel_resumo` (total contratado no ano, contratos, licitações abertas, fornecedores),
  ranking de `vw_contratado_por_fornecedor`, gasto por unidade (`vw_contratado_por_unidade`).
- **Licitações e contratos**: tabela com filtros (unidade/secretaria, faixa de valor, status, período,
  modalidade) e busca textual; modal de detalhe com o resumo em linguagem simples (`resumo_ia`) e link à fonte.
- **Fornecedor**: histórico de contratos, valor acumulado, matriz/filiais (`cnpj_raiz`).
- **Alertas**: assinatura com confirmação por e-mail.

Consome somente a API (`NEXT_PUBLIC_API_URL`); nunca acessa o banco direto.
