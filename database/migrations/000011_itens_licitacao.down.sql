DROP VIEW IF EXISTS vw_precos_itens;
DROP TABLE IF EXISTS licitacao_item_resultados;
DROP TABLE IF EXISTS licitacao_itens;
DROP INDEX IF EXISTS licitacoes_itens_pendentes_idx;
ALTER TABLE licitacoes DROP COLUMN IF EXISTS itens_coletados_em;
