-- 000014 · "Fora do PNCP" só para contratos propriamente ditos
-- No sistema municipal, tipo REGISTRO_PRECO são contratações a partir de ata de registro de preço; no PNCP elas
-- aparecem como atas, não como contratos. Compará-las com /contratos gerava falso alarme (57 de 87 em out/2026).
CREATE OR REPLACE VIEW vw_contratos_municipais_fora_do_pncp AS
SELECT cm.*
  FROM contratos_municipais cm
 WHERE NOT cm.excluido
   AND cm.tipo = 'CONTRATO'
   AND (cm.id_pncp IS NULL OR NOT EXISTS (SELECT 1 FROM contratos c WHERE c.id_pncp = cm.id_pncp));
