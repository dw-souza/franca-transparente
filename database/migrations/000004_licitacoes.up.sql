-- 000004 · Licitações / contratações (editais, dispensas, inexigibilidades)
-- Fonte primária: PNCP /v1/contratacoes. id_pncp = numeroControlePNCP
-- (ex.: 47970769000104-1-000123/2026).

CREATE TABLE licitacoes (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_pncp                 varchar(60) NOT NULL UNIQUE,
    orgao_id                bigint      NOT NULL REFERENCES orgaos (id),

    -- Unidade compradora: no PNCP costuma ser a secretaria/departamento.
    unidade_codigo          text,
    unidade_nome            text,

    numero                  text,                    -- numeroCompra ("90012/2026")
    ano                     smallint    NOT NULL,
    sequencial              integer,
    processo                text,

    objeto                  text        NOT NULL,
    informacao_complementar text,

    modalidade_id           smallint    REFERENCES modalidades_contratacao (id),
    modo_disputa            text,                    -- Aberto, Fechado, Não se aplica...
    amparo_legal            text,
    srp                     boolean     NOT NULL DEFAULT false,   -- Sistema de Registro de Preços

    valor_estimado          numeric(18, 2) CHECK (valor_estimado  IS NULL OR valor_estimado  >= 0),
    valor_homologado        numeric(18, 2) CHECK (valor_homologado IS NULL OR valor_homologado >= 0),

    data_publicacao         timestamptz,
    data_abertura           timestamptz,             -- dataAberturaProposta
    data_encerramento       timestamptz,             -- dataEncerramentoProposta

    status                  text        NOT NULL,    -- situacaoCompraNome ("Divulgada no PNCP", "Revogada"...)
    situacao_pncp_id        smallint,
    link_sistema_origem     text,

    -- Enriquecimento por IA
    resumo_ia               text,
    resumo_ia_modelo        text,
    resumo_ia_em            timestamptz,

    -- Rastreabilidade: o registro bruto fica guardado para reprocessamento e auditoria.
    fonte                   text        NOT NULL DEFAULT 'pncp',
    payload_hash            char(64),
    payload_bruto           jsonb,
    data_atualizacao_fonte  timestamptz,             -- dataAtualizacaoGlobal

    busca                   tsvector GENERATED ALWAYS AS (
                                setweight(to_tsvector('pt_unaccent', coalesce(objeto, '')), 'A') ||
                                setweight(to_tsvector('pt_unaccent', coalesce(unidade_nome, '')), 'B') ||
                                setweight(to_tsvector('pt_unaccent', coalesce(informacao_complementar, '')), 'C')
                            ) STORED,

    criado_em               timestamptz NOT NULL DEFAULT now(),
    atualizado_em           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX licitacoes_orgao_idx         ON licitacoes (orgao_id);
CREATE INDEX licitacoes_ano_modalidade_idx ON licitacoes (ano, modalidade_id);
CREATE INDEX licitacoes_status_idx        ON licitacoes (status);
CREATE INDEX licitacoes_publicacao_idx    ON licitacoes (data_publicacao DESC);
CREATE INDEX licitacoes_encerramento_idx  ON licitacoes (data_encerramento);   -- "licitações abertas"
CREATE INDEX licitacoes_valor_idx         ON licitacoes (valor_estimado);
CREATE INDEX licitacoes_unidade_idx       ON licitacoes (unidade_nome);
CREATE INDEX licitacoes_busca_idx         ON licitacoes USING gin (busca);
CREATE INDEX licitacoes_sem_resumo_idx    ON licitacoes (id) WHERE resumo_ia IS NULL;  -- fila da IA

CREATE TRIGGER licitacoes_atualizado_em BEFORE UPDATE ON licitacoes
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();
