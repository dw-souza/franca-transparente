-- 000010 · Valores negativos da fonte entram no banco
-- O PNCP publica erros de digitação (ex.: valorTotalEstimado = -36 em 47987136000109-1-000007/2024).
-- Rejeitar a linha esconderia o problema; como em contratos, a inconsistência vira sinal de qualidade de dado.

ALTER TABLE licitacoes DROP CONSTRAINT licitacoes_valor_estimado_check;
ALTER TABLE licitacoes DROP CONSTRAINT licitacoes_valor_homologado_check;
