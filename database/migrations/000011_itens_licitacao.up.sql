-- 000011 · Itens das contratações e resultados por item (PNCP /orgaos/{cnpj}/compras/{ano}/{seq}/itens)
-- Base para preço unitário de referência e para saber quem venceu cada item.
-- Sem payload_bruto aqui: ~17 itens por licitação em média; o hash basta para detectar mudança e o
-- registro original pode ser recoletado.

ALTER TABLE licitacoes ADD COLUMN itens_coletados_em timestamptz;   -- cursor da coleta de itens
CREATE INDEX licitacoes_itens_pendentes_idx ON licitacoes (data_publicacao DESC) WHERE itens_coletados_em IS NULL;

CREATE TABLE licitacao_itens (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    licitacao_id             bigint      NOT NULL REFERENCES licitacoes (id) ON DELETE CASCADE,
    numero_item              integer     NOT NULL,
    descricao                text        NOT NULL,
    material_servico         char(1)     CHECK (material_servico IN ('M', 'S')),
    unidade_medida           text,
    quantidade               numeric(18, 4),
    valor_unitario_estimado  numeric(18, 4),
    valor_total_estimado     numeric(18, 2),
    orcamento_sigiloso       boolean     NOT NULL DEFAULT false,
    criterio_julgamento      text,
    situacao                 text,                    -- Em andamento, Homologado, Deserto, Fracassado...
    tem_resultado            boolean     NOT NULL DEFAULT false,
    ncm_nbs_codigo           text,
    catalogo_codigo          text,
    payload_hash             char(64)    NOT NULL,
    data_atualizacao_fonte   timestamptz,

    busca                    tsvector GENERATED ALWAYS AS (to_tsvector('pt_unaccent', descricao)) STORED,

    criado_em                timestamptz NOT NULL DEFAULT now(),
    atualizado_em            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (licitacao_id, numero_item)
);

CREATE INDEX licitacao_itens_busca_idx ON licitacao_itens USING gin (busca);
CREATE INDEX licitacao_itens_ncm_idx   ON licitacao_itens (ncm_nbs_codigo) WHERE ncm_nbs_codigo IS NOT NULL;

CREATE TRIGGER licitacao_itens_atualizado_em BEFORE UPDATE ON licitacao_itens
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

CREATE TABLE licitacao_item_resultados (
    id                         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_id                    bigint      NOT NULL REFERENCES licitacao_itens (id) ON DELETE CASCADE,
    sequencial                 integer     NOT NULL,             -- sequencialResultado
    fornecedor_id              bigint      REFERENCES fornecedores (id),
    quantidade_homologada      numeric(18, 4),
    valor_unitario_homologado  numeric(18, 4),
    valor_total_homologado     numeric(18, 2),
    percentual_desconto        numeric(9, 4),
    porte_fornecedor           text,                             -- ME, EPP, Demais
    situacao                   text,                             -- Informado, Cancelado
    data_resultado             date,
    payload_hash               char(64)    NOT NULL,
    data_atualizacao_fonte     timestamptz,
    criado_em                  timestamptz NOT NULL DEFAULT now(),
    atualizado_em              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (item_id, sequencial)
);

CREATE INDEX licitacao_item_resultados_fornecedor_idx ON licitacao_item_resultados (fornecedor_id);

CREATE TRIGGER licitacao_item_resultados_atualizado_em BEFORE UPDATE ON licitacao_item_resultados
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- Preço praticado por item: base de "quanto a cidade paga por X" e de comparação entre compras.
CREATE VIEW vw_precos_itens AS
SELECT i.id AS item_id, l.id AS licitacao_id, l.id_pncp, o.razao_social AS orgao, l.unidade_nome,
       l.ano, l.data_publicacao, m.nome AS modalidade,
       i.numero_item, i.descricao, i.material_servico, i.unidade_medida, i.quantidade,
       i.valor_unitario_estimado, r.valor_unitario_homologado, r.quantidade_homologada, r.valor_total_homologado,
       f.id AS fornecedor_id, f.razao_social AS fornecedor, f.tipo_pessoa, r.porte_fornecedor, r.data_resultado
  FROM licitacao_itens i
  JOIN licitacoes l ON l.id = i.licitacao_id
  JOIN orgaos o ON o.id = l.orgao_id
  LEFT JOIN modalidades_contratacao m ON m.id = l.modalidade_id
  LEFT JOIN licitacao_item_resultados r ON r.item_id = i.id AND r.situacao IS DISTINCT FROM 'Cancelado'
  LEFT JOIN fornecedores f ON f.id = r.fornecedor_id;
