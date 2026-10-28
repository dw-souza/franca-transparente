-- 000003 · Fornecedores (pessoas jurídicas, físicas e estrangeiras contratadas)

CREATE TABLE fornecedores (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cnpj_cpf           varchar(30) NOT NULL UNIQUE,   -- normalizado (só [0-9A-Z]); estrangeiro pode ser maior
    tipo_pessoa        varchar(2)  NOT NULL DEFAULT 'PJ'
                       CHECK (tipo_pessoa IN ('PJ', 'PF', 'PE')),   -- PE = estrangeiro (domínio PNCP)
    razao_social       text        NOT NULL,
    nome_fantasia      text,

    -- Raiz do CNPJ (8 primeiras posições): agrupa matriz e filiais na análise de concentração.
    cnpj_raiz          varchar(8) GENERATED ALWAYS AS (
                           CASE WHEN tipo_pessoa = 'PJ' THEN left(cnpj_cpf, 8) END
                       ) STORED,

    -- Enriquecimento via dados abertos da Receita Federal (fase 2)
    natureza_juridica  text,
    cnae_principal     varchar(7),
    cnae_descricao     text,
    porte              text,
    situacao_cadastral text,
    data_abertura      date,
    capital_social     numeric(18, 2),
    municipio          text,
    uf                 char(2),
    enriquecido_em     timestamptz,     -- quando preenchido, o collector não sobrescreve razao_social

    criado_em          timestamptz NOT NULL DEFAULT now(),
    atualizado_em      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fornecedores_documento_valido CHECK (
        (tipo_pessoa = 'PJ' AND cnpj_cpf ~ '^[0-9A-Z]{12}[0-9]{2}$') OR
        (tipo_pessoa = 'PF' AND cnpj_cpf ~ '^[0-9]{11}$') OR
        (tipo_pessoa = 'PE' AND cnpj_cpf ~ '^[0-9A-Z]{1,30}$')
    )
);

COMMENT ON COLUMN fornecedores.cnpj_cpf IS
    'CPF de pessoa física é dado pessoal (LGPD): a API pública deve expô-lo mascarado.';

CREATE INDEX fornecedores_cnpj_raiz_idx  ON fornecedores (cnpj_raiz);
CREATE INDEX fornecedores_razao_trgm_idx ON fornecedores USING gin (f_unaccent(razao_social) gin_trgm_ops);
CREATE INDEX fornecedores_fantasia_trgm_idx ON fornecedores USING gin (f_unaccent(nome_fantasia) gin_trgm_ops)
    WHERE nome_fantasia IS NOT NULL;

CREATE TRIGGER fornecedores_atualizado_em BEFORE UPDATE ON fornecedores
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();
