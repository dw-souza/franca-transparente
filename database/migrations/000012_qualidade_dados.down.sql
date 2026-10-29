DROP VIEW IF EXISTS vw_licitacoes_por_modalidade;
CREATE VIEW vw_licitacoes_por_modalidade AS
SELECT l.ano, l.modalidade_id, m.nome AS modalidade,
       count(*)                AS qtd,
       sum(l.valor_estimado)   AS valor_estimado,
       sum(l.valor_homologado) AS valor_homologado
  FROM licitacoes l
  LEFT JOIN modalidades_contratacao m ON m.id = l.modalidade_id
 GROUP BY l.ano, l.modalidade_id, m.nome;
DROP VIEW IF EXISTS vw_contratos_qualidade;
DROP VIEW IF EXISTS vw_licitacoes_qualidade;
DROP FUNCTION IF EXISTS modalidade_e_receita(smallint);
