-- 000009 · Views que alimentam os cards e relatórios do painel
-- Views simples no MVP; viram MATERIALIZED quando o volume pedir.

-- Licitações recebendo propostas agora
CREATE VIEW vw_licitacoes_abertas AS
SELECT l.id, l.id_pncp, o.razao_social AS orgao, l.unidade_nome, l.numero, l.ano,
       m.nome AS modalidade, l.objeto, l.valor_estimado,
       l.data_abertura, l.data_encerramento, l.link_sistema_origem
  FROM licitacoes l
  JOIN orgaos o ON o.id = l.orgao_id
  LEFT JOIN modalidades_contratacao m ON m.id = l.modalidade_id
 WHERE l.data_encerramento > now()
   AND l.status NOT IN ('Revogada', 'Anulada', 'Suspensa');

-- Gasto contratado por fornecedor e ano (ranking "Maiores fornecedores")
CREATE VIEW vw_contratado_por_fornecedor AS
SELECT f.id AS fornecedor_id, f.cnpj_cpf, f.tipo_pessoa, f.razao_social, f.cnpj_raiz,
       extract(year FROM c.data_assinatura)::int AS ano,
       count(*)           AS qtd_contratos,
       sum(c.valor_total) AS valor_total
  FROM contratos c
  JOIN fornecedores f ON f.id = c.fornecedor_id
 WHERE NOT c.receita
 GROUP BY f.id, extract(year FROM c.data_assinatura);  -- expressão explícita: contratos também tem coluna "ano"

-- Gasto por órgão / unidade compradora (≈ secretaria) e ano
CREATE VIEW vw_contratado_por_unidade AS
SELECT o.id AS orgao_id, o.razao_social AS orgao, c.unidade_nome,
       extract(year FROM c.data_assinatura)::int AS ano,
       count(*)           AS qtd_contratos,
       sum(c.valor_total) AS valor_total
  FROM contratos c
  JOIN orgaos o ON o.id = c.orgao_id
 WHERE NOT c.receita
 GROUP BY o.id, c.unidade_nome, extract(year FROM c.data_assinatura);

-- Contratações por modalidade e ano (proporção de dispensas/inexigibilidades é indicador clássico)
CREATE VIEW vw_licitacoes_por_modalidade AS
SELECT l.ano, l.modalidade_id, m.nome AS modalidade,
       count(*)                AS qtd,
       sum(l.valor_estimado)   AS valor_estimado,
       sum(l.valor_homologado) AS valor_homologado
  FROM licitacoes l
  LEFT JOIN modalidades_contratacao m ON m.id = l.modalidade_id
 GROUP BY l.ano, l.modalidade_id, m.nome;

-- Cards do topo do painel
CREATE VIEW vw_painel_resumo AS
SELECT extract(year FROM now())::int AS ano,
       (SELECT coalesce(sum(valor_total), 0) FROM contratos
         WHERE NOT receita AND data_assinatura >= date_trunc('year', now()))       AS total_contratado_ano,
       (SELECT count(*) FROM contratos
         WHERE data_assinatura >= date_trunc('year', now()))                       AS contratos_ano,
       (SELECT count(*) FROM vw_licitacoes_abertas)                                AS licitacoes_abertas,
       (SELECT count(DISTINCT fornecedor_id) FROM contratos
         WHERE data_assinatura >= date_trunc('year', now()))                       AS fornecedores_ano;
