-- 000001 · Extensões, funções utilitárias e configuração de busca textual
-- Formato: golang-migrate (NNNNNN_nome.up.sql / .down.sql)

CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- busca aproximada por nome (fornecedores, órgãos)
CREATE EXTENSION IF NOT EXISTS unaccent;  -- busca sem acento ("licitacao" encontra "licitação")

-- unaccent() é STABLE; índices e colunas geradas exigem IMMUTABLE.
-- Wrapper com dicionário explícito é a forma segura e usual de contornar isso.
CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

-- Configuração full-text: português + remoção de acentos
CREATE TEXT SEARCH CONFIGURATION pt_unaccent (COPY = portuguese);
ALTER TEXT SEARCH CONFIGURATION pt_unaccent
    ALTER MAPPING FOR hword, hword_part, word WITH unaccent, portuguese_stem;

-- Trigger genérico de atualizado_em
CREATE OR REPLACE FUNCTION set_atualizado_em() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.atualizado_em := now();
    RETURN NEW;
END
$$;

-- Documento (CNPJ/CPF) só com dígitos/letras, em maiúsculas.
-- Desde jul/2026 a Receita emite CNPJ alfanumérico (12 posições [0-9A-Z] + 2 DV numéricos).
CREATE OR REPLACE FUNCTION normalizar_documento(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT upper(regexp_replace($1, '[^0-9A-Za-z]', '', 'g')) $$;
