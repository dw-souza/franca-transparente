-- Os candidatos de REGISTRO_PRECO desfeitos no up não são restaurados (eram incorretos).
DROP VIEW IF EXISTS vw_contratado_x_pago;
CREATE VIEW vw_contratado_x_pago AS
SELECT c.id AS contrato_id, c.id_pncp, c.valor_total AS contratado,
       coalesce(sum(x.empenhado), 0) AS empenhado,
       coalesce(sum(x.liquidado), 0) AS liquidado,
       coalesce(sum(x.pago), 0)      AS pago,
       count(x.id)                   AS empenhos
  FROM contratos c
  LEFT JOIN vw_execucao_empenho x ON x.contrato_id_pncp = c.id_pncp
 GROUP BY c.id, c.id_pncp, c.valor_total;

CREATE OR REPLACE VIEW vw_contratos_municipais_fora_do_pncp AS
SELECT cm.*
  FROM contratos_municipais cm
 WHERE NOT cm.excluido
   AND cm.tipo = 'CONTRATO'
   AND (cm.id_pncp IS NULL OR NOT EXISTS (SELECT 1 FROM contratos c WHERE c.id_pncp = cm.id_pncp));

CREATE OR REPLACE VIEW vw_execucao_empenho AS
SELECT e.id, e.id_fonte, e.ano, e.data_empenho, e.unidade_id, e.fornecedor_id, e.credor_nome,
       e.contrato_id_fonte, e.contrato_id_pncp, e.licitacao_id_pncp,
       e.valor AS empenhado,
       coalesce(l.liquidado, 0) AS liquidado,
       coalesce(p.pago, 0)      AS pago
  FROM empenhos e
  LEFT JOIN (SELECT empenho_id_fonte, sum(valor_liquido(valor, anulacao)) AS liquidado
               FROM liquidacoes GROUP BY empenho_id_fonte) l ON l.empenho_id_fonte = e.id_fonte
  LEFT JOIN (SELECT empenho_id_fonte, sum(valor_liquido(valor, anulacao)) AS pago
               FROM pagamentos GROUP BY empenho_id_fonte) p ON p.empenho_id_fonte = e.id_fonte;

DROP VIEW IF EXISTS vw_vinculo_contrato_pncp;
DROP FUNCTION IF EXISTS processo_normalizado(text);
COMMENT ON COLUMN contratos_municipais.id_pncp IS NULL;
COMMENT ON COLUMN empenhos.contrato_id_pncp IS NULL;
