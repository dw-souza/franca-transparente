-- 000005 · Contratos (e empenhos com força de contrato) publicados no PNCP
-- id_pncp = numeroControlePNCP do contrato; id_pncp_compra = numeroControlePncpCompra.

CREATE TABLE contratos (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id_pncp                 varchar(60) NOT NULL UNIQUE,
    id_pncp_compra          varchar(60),
    licitacao_id            bigint      REFERENCES licitacoes (id) ON DELETE SET NULL,
    orgao_id                bigint      NOT NULL REFERENCES orgaos (id),
    fornecedor_id           bigint      NOT NULL REFERENCES fornecedores (id),

    unidade_codigo          text,
    unidade_nome            text,

    numero                  text,                    -- numeroContratoEmpenho
    ano                     smallint,
    sequencial              integer,
    processo                text,
    tipo_contrato           text,                    -- Contrato, Empenho, Carta-contrato...
    categoria_processo      text,                    -- Compras, Obras, Serviços...

    objeto                  text        NOT NULL,
    informacao_complementar text,

    valor_inicial           numeric(18, 2),
    valor_total             numeric(18, 2) NOT NULL,  -- valorGlobal
    valor_acumulado         numeric(18, 2),
    numero_parcelas         integer,
    valor_parcela           numeric(18, 2),

    data_assinatura         date,
    vigencia_inicio         date,
    vigencia_fim            date,
    -- Sem CHECK de coerência de vigência de propósito: dado público vem com erros
    -- e rejeitar a linha esconderia o problema. Inconsistências viram sinais de risco.

    data_publicacao         timestamptz,
    receita                 boolean     NOT NULL DEFAULT false,  -- contrato que gera receita ao órgão

    resumo_ia               text,
    resumo_ia_modelo        text,
    resumo_ia_em            timestamptz,

    fonte                   text        NOT NULL DEFAULT 'pncp',
    payload_hash            char(64),
    payload_bruto           jsonb,
    data_atualizacao_fonte  timestamptz,

    busca                   tsvector GENERATED ALWAYS AS (
                                setweight(to_tsvector('pt_unaccent', coalesce(objeto, '')), 'A') ||
                                setweight(to_tsvector('pt_unaccent', coalesce(informacao_complementar, '')), 'C')
                            ) STORED,

    criado_em               timestamptz NOT NULL DEFAULT now(),
    atualizado_em           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX contratos_licitacao_idx     ON contratos (licitacao_id);
CREATE INDEX contratos_compra_idx        ON contratos (id_pncp_compra) WHERE licitacao_id IS NULL;
CREATE INDEX contratos_orgao_idx         ON contratos (orgao_id);
CREATE INDEX contratos_fornecedor_idx    ON contratos (fornecedor_id, data_assinatura DESC);
CREATE INDEX contratos_assinatura_idx    ON contratos (data_assinatura DESC);
CREATE INDEX contratos_vigencia_fim_idx  ON contratos (vigencia_fim);
CREATE INDEX contratos_valor_idx         ON contratos (valor_total);
CREATE INDEX contratos_busca_idx         ON contratos USING gin (busca);

CREATE TRIGGER contratos_atualizado_em BEFORE UPDATE ON contratos
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- Vínculo contrato ↔ licitação nas duas ordens de chegada.
-- Contratos costumam ser coletados antes/depois da compra; o banco resolve sozinho.
CREATE OR REPLACE FUNCTION contratos_resolver_licitacao() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.licitacao_id IS NULL AND NEW.id_pncp_compra IS NOT NULL THEN
        SELECT l.id INTO NEW.licitacao_id FROM licitacoes l WHERE l.id_pncp = NEW.id_pncp_compra;
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER contratos_vincular_licitacao
    BEFORE INSERT OR UPDATE OF id_pncp_compra ON contratos
    FOR EACH ROW EXECUTE FUNCTION contratos_resolver_licitacao();

CREATE OR REPLACE FUNCTION licitacoes_vincular_contratos() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE contratos SET licitacao_id = NEW.id
     WHERE id_pncp_compra = NEW.id_pncp AND licitacao_id IS NULL;
    RETURN NEW;
END
$$;

CREATE TRIGGER licitacoes_vincular_contratos
    AFTER INSERT ON licitacoes
    FOR EACH ROW EXECUTE FUNCTION licitacoes_vincular_contratos();
