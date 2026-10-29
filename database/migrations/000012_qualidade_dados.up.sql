-- 000012 · Sinais de qualidade de dado
-- Marcam, não escondem: o painel mostra o registro com o alerta ("sinal para checar", nunca acusação).
-- Regras deliberadamente simples e explicáveis; os limiares ficam aqui, num só lugar.

-- Leilão é alienação (receita), não despesa.
CREATE OR REPLACE FUNCTION modalidade_e_receita(smallint) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT $1 IN (1, 13) $$;

CREATE VIEW vw_licitacoes_qualidade AS
WITH limites AS (   -- p99 por modalidade, só onde há casos suficientes para a comparação fazer sentido
    SELECT modalidade_id, percentile_cont(0.99) WITHIN GROUP (ORDER BY valor_estimado) AS p99
      FROM licitacoes
     WHERE valor_estimado > 0
     GROUP BY modalidade_id
    HAVING count(*) >= 20
)
SELECT l.id AS licitacao_id, l.id_pncp,
       CASE WHEN modalidade_e_receita(l.modalidade_id) THEN 'receita' ELSE 'despesa' END AS natureza,
       array_remove(ARRAY[
           CASE WHEN modalidade_e_receita(l.modalidade_id) THEN 'receita' END,
           CASE WHEN l.valor_estimado < 0 THEN 'valor_negativo' END,
           CASE WHEN l.valor_estimado = 0 THEN 'valor_zero' END,
           CASE WHEN l.valor_estimado >= 1e9 OR l.valor_estimado > 10 * lim.p99 THEN 'valor_atipico' END,
           CASE WHEN NOT modalidade_e_receita(l.modalidade_id) AND l.valor_homologado > 0  -- em leilão o lance sobe
                     AND (l.valor_estimado <= 0 OR l.valor_homologado > 2 * l.valor_estimado)
                THEN 'homologado_divergente' END
       ], NULL) AS alertas
  FROM licitacoes l
  LEFT JOIN limites lim ON lim.modalidade_id = l.modalidade_id;

CREATE VIEW vw_contratos_qualidade AS
WITH limite AS (
    SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY valor_total) AS p99 FROM contratos WHERE valor_total > 0
)
SELECT c.id AS contrato_id, c.id_pncp,
       CASE WHEN c.receita THEN 'receita' ELSE 'despesa' END AS natureza,
       array_remove(ARRAY[
           CASE WHEN c.receita THEN 'receita' END,
           CASE WHEN c.valor_total <= 0 THEN 'valor_nao_positivo' END,
           CASE WHEN c.valor_total >= 1e9 OR c.valor_total > 10 * lim.p99 THEN 'valor_atipico' END,
           CASE WHEN c.vigencia_fim < c.vigencia_inicio THEN 'vigencia_invertida' END
       ], NULL) AS alertas
  FROM contratos c CROSS JOIN limite lim;

-- Totais por modalidade: negativos fora das somas e quantos registros têm alerta (coluna nova no fim).
CREATE OR REPLACE VIEW vw_licitacoes_por_modalidade AS
SELECT l.ano, l.modalidade_id, m.nome AS modalidade,
       count(*)                                                       AS qtd,
       sum(l.valor_estimado)   FILTER (WHERE l.valor_estimado >= 0)   AS valor_estimado,
       sum(l.valor_homologado) FILTER (WHERE l.valor_homologado >= 0) AS valor_homologado,
       count(*) FILTER (WHERE cardinality(q.alertas) > 0)             AS qtd_com_alerta
  FROM licitacoes l
  JOIN vw_licitacoes_qualidade q ON q.licitacao_id = l.id
  LEFT JOIN modalidades_contratacao m ON m.id = l.modalidade_id
 GROUP BY l.ano, l.modalidade_id, m.nome;
