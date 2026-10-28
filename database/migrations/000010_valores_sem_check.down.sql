-- NOT VALID: não falha se já houver linhas negativas; vale para gravações novas.
ALTER TABLE licitacoes ADD CONSTRAINT licitacoes_valor_estimado_check
    CHECK (valor_estimado IS NULL OR valor_estimado >= 0) NOT VALID;
ALTER TABLE licitacoes ADD CONSTRAINT licitacoes_valor_homologado_check
    CHECK (valor_homologado IS NULL OR valor_homologado >= 0) NOT VALID;
