CREATE OR REPLACE VIEW vw_contratos_municipais_fora_do_pncp AS
SELECT cm.*
  FROM contratos_municipais cm
 WHERE NOT cm.excluido
   AND (cm.id_pncp IS NULL OR NOT EXISTS (SELECT 1 FROM contratos c WHERE c.id_pncp = cm.id_pncp));
