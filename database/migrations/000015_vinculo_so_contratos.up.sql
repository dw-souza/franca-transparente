-- 000015 · Vínculo contrato municipal ↔ contrato do PNCP validado; aditivos no contratado × pago
--
-- O sequencial_pncp do sistema municipal não basta sozinho:
-- * em REGISTRO_PRECO ele é o da ATA (outra numeração): 0 de 497 casos batiam em valor ou processo;
-- * mesmo no tipo CONTRATO, ~20% apontam para um contrato do PNCP com outro processo e outro valor.
-- O vínculo agora só vale quando confirmado: sequencial + (processo ou valor), ou, na falta dele, um único contrato
-- do PNCP com o mesmo processo e o mesmo fornecedor. contratos_municipais.id_pncp e empenhos.contrato_id_pncp
-- passam a ser só candidatos; as views usam vw_vinculo_contrato_pncp.

-- Candidatos de REGISTRO_PRECO são sempre errados (o coletor já não os monta): limpa o que foi gravado antes.
UPDATE empenhos e
   SET contrato_id_pncp = NULL
  FROM contratos_municipais cm
 WHERE cm.fonte = e.fonte AND cm.id_fonte = e.contrato_id_fonte
   AND cm.tipo IS DISTINCT FROM 'CONTRATO'
   AND e.contrato_id_pncp IS NOT NULL;
UPDATE contratos_municipais SET id_pncp = NULL WHERE tipo IS DISTINCT FROM 'CONTRATO' AND id_pncp IS NOT NULL;

COMMENT ON COLUMN contratos_municipais.id_pncp IS
    'Candidato montado com sequencial_pncp + ano; o vínculo confirmado está em vw_vinculo_contrato_pncp.';
COMMENT ON COLUMN empenhos.contrato_id_pncp IS
    'Candidato montado pelo coletor; as views usam o vínculo confirmado (vw_vinculo_contrato_pncp).';

-- "06278/2025" = "6278/2025"; ignora pontuação e zeros à esquerda.
CREATE OR REPLACE FUNCTION processo_normalizado(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT nullif(regexp_replace(regexp_replace($1, '[^0-9/]', '', 'g'), '^0+', ''), '') $$;

CREATE VIEW vw_vinculo_contrato_pncp AS
WITH por_sequencial AS (
    SELECT cm.fonte, cm.id_fonte, c.id_pncp,
           CASE WHEN processo_normalizado(c.processo) = processo_normalizado(cm.processo) THEN 'sequencial+processo'
                WHEN abs(c.valor_total - cm.valor) <= 0.01 * greatest(abs(c.valor_total), 1) THEN 'sequencial+valor'
           END AS criterio
      FROM contratos_municipais cm
      JOIN contratos c ON c.id_pncp = cm.id_pncp
     WHERE cm.tipo = 'CONTRATO'
),
confirmados AS (SELECT * FROM por_sequencial WHERE criterio IS NOT NULL),
por_processo AS (
    SELECT cm.fonte, cm.id_fonte, min(c.id_pncp) AS id_pncp, 'processo+fornecedor' AS criterio
      FROM contratos_municipais cm
      JOIN contratos c ON processo_normalizado(c.processo) = processo_normalizado(cm.processo)
                      AND c.fornecedor_id = cm.fornecedor_id
     WHERE cm.tipo = 'CONTRATO'
       AND NOT EXISTS (SELECT 1 FROM confirmados v WHERE v.fonte = cm.fonte AND v.id_fonte = cm.id_fonte)
     GROUP BY cm.fonte, cm.id_fonte
    HAVING count(DISTINCT c.id_pncp) = 1          -- ambíguo não vincula
)
SELECT * FROM confirmados
UNION ALL
SELECT * FROM por_processo;

-- Execução por empenho com o vínculo confirmado (mesmas colunas; contrato_id_pncp deixa de ser o candidato).
CREATE OR REPLACE VIEW vw_execucao_empenho AS
SELECT e.id, e.id_fonte, e.ano, e.data_empenho, e.unidade_id, e.fornecedor_id, e.credor_nome,
       e.contrato_id_fonte, v.id_pncp::varchar(60) AS contrato_id_pncp, e.licitacao_id_pncp,
       e.valor AS empenhado,
       coalesce(l.liquidado, 0) AS liquidado,
       coalesce(p.pago, 0)      AS pago
  FROM empenhos e
  LEFT JOIN vw_vinculo_contrato_pncp v ON v.fonte = e.fonte AND v.id_fonte = e.contrato_id_fonte
  LEFT JOIN (SELECT empenho_id_fonte, sum(valor_liquido(valor, anulacao)) AS liquidado
               FROM liquidacoes GROUP BY empenho_id_fonte) l ON l.empenho_id_fonte = e.id_fonte
  LEFT JOIN (SELECT empenho_id_fonte, sum(valor_liquido(valor, anulacao)) AS pago
               FROM pagamentos GROUP BY empenho_id_fonte) p ON p.empenho_id_fonte = e.id_fonte;

-- Contratado × pago com os aditivos do sistema municipal (prorrogações e acréscimos não estão no PNCP de Franca).
-- Agregados em subconsultas separadas para não multiplicar linhas entre empenhos e aditivos.
CREATE OR REPLACE VIEW vw_contratado_x_pago AS
SELECT c.id AS contrato_id, c.id_pncp, c.valor_total AS contratado,
       coalesce(x.empenhado, 0) AS empenhado,
       coalesce(x.liquidado, 0) AS liquidado,
       coalesce(x.pago, 0)      AS pago,
       coalesce(x.empenhos, 0)  AS empenhos,
       coalesce(a.aditivos, 0)  AS aditivos,
       c.valor_total + coalesce(a.aditivos, 0) AS contratado_com_aditivos
  FROM contratos c
  LEFT JOIN (SELECT contrato_id_pncp, sum(empenhado) AS empenhado, sum(liquidado) AS liquidado,
                    sum(pago) AS pago, count(*) AS empenhos
               FROM vw_execucao_empenho
              WHERE contrato_id_pncp IS NOT NULL
              GROUP BY contrato_id_pncp) x ON x.contrato_id_pncp = c.id_pncp
  LEFT JOIN (SELECT v.id_pncp, sum(ad.valor_total) AS aditivos
               FROM vw_vinculo_contrato_pncp v
               JOIN contrato_aditamentos ad ON ad.fonte = v.fonte AND ad.contrato_id_fonte = v.id_fonte
              GROUP BY v.id_pncp) a ON a.id_pncp = c.id_pncp;

-- Contratos (tipo CONTRATO) sem vínculo confirmado com o PNCP.
CREATE OR REPLACE VIEW vw_contratos_municipais_fora_do_pncp AS
SELECT cm.*
  FROM contratos_municipais cm
 WHERE NOT cm.excluido
   AND cm.tipo = 'CONTRATO'
   AND NOT EXISTS (SELECT 1 FROM vw_vinculo_contrato_pncp v WHERE v.fonte = cm.fonte AND v.id_fonte = cm.id_fonte);
