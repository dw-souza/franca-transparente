-- 000013 · Execução da despesa do Município (Portal da Transparência / EddyData)
-- Empenho → liquidação → pagamento, por secretaria (unidade orçamentária), mais os contratos e aditivos do
-- sistema municipal. Os vínculos entre esses registros usam o id do EddyData (id_fonte), sem FK: a ordem de
-- chegada não importa e as views fazem as junções. O vínculo com o PNCP é o id_pncp montado pelo coletor
-- (sequencial_pncp + ano), conferido contra o PNCP em 2026-10-29.
-- Lista branca de campos: nada de dados bancários/pessoais do credor; CPF em texto livre chega mascarado.

CREATE TABLE unidades_orcamentarias (          -- ≈ secretarias
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    orgao_id  bigint NOT NULL REFERENCES orgaos (id),
    codigo    text   NOT NULL,                 -- "020700"
    nome      text   NOT NULL,                 -- "SECRETARIA MUN. DE SAÚDE"
    UNIQUE (orgao_id, codigo)
);

CREATE TABLE contratos_municipais (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte              text        NOT NULL DEFAULT 'eddydata',
    id_fonte           bigint      NOT NULL,
    orgao_id           bigint      NOT NULL REFERENCES orgaos (id),
    fornecedor_id      bigint      REFERENCES fornecedores (id),
    credor_nome        text,
    numero             text,
    ano                smallint,
    processo           text,
    tipo               text,                    -- CONTRATO, REGISTRO_PRECO...
    tipo_contrato      text,
    objeto             text,
    valor              numeric(18, 2),
    data_assinatura    date,
    data_inicio        date,
    data_termino       date,
    excluido           boolean     NOT NULL DEFAULT false,
    inativo            boolean     NOT NULL DEFAULT false,
    id_pncp            varchar(60),             -- contrato no PNCP, quando a Prefeitura o publicou lá
    licitacao_id_pncp  varchar(60),
    payload_hash       char(64)    NOT NULL,
    criado_em          timestamptz NOT NULL DEFAULT now(),
    atualizado_em      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fonte, id_fonte)
);
CREATE INDEX contratos_municipais_id_pncp_idx ON contratos_municipais (id_pncp) WHERE id_pncp IS NOT NULL;
CREATE INDEX contratos_municipais_processo_idx ON contratos_municipais (processo);

CREATE TABLE contrato_aditamentos (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte              text        NOT NULL DEFAULT 'eddydata',
    id_fonte           bigint      NOT NULL,
    contrato_id_fonte  bigint      NOT NULL,     -- contratos_municipais.id_fonte
    numero             text,
    finalidade         text,
    data_aditamento    date,
    data_inicio        date,
    data_termino       date,
    valor_total        numeric(18, 2),
    valor_aditado      numeric(18, 2),
    mudanca_vigencia   boolean,
    mudanca_reajuste   boolean,
    mudanca_favorecido boolean,
    payload_hash       char(64)    NOT NULL,
    criado_em          timestamptz NOT NULL DEFAULT now(),
    atualizado_em      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fonte, id_fonte)
);
CREATE INDEX contrato_aditamentos_contrato_idx ON contrato_aditamentos (contrato_id_fonte);

CREATE TABLE empenhos (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte                 text        NOT NULL DEFAULT 'eddydata',
    id_fonte              bigint      NOT NULL,
    orgao_id              bigint      NOT NULL REFERENCES orgaos (id),
    unidade_id            bigint      REFERENCES unidades_orcamentarias (id),
    fornecedor_id         bigint      REFERENCES fornecedores (id),
    credor_nome           text,
    numero                integer,
    ano                   smallint    NOT NULL,
    especie               text,                 -- EMO (ordinário), EOA (anulação, valor negativo)...
    tipo_empenho          char(1),              -- O ordinário, G global, E estimativo
    data_empenho          date        NOT NULL,
    valor                 numeric(18, 2) NOT NULL,
    processo              text,
    historico             text,
    executora_codigo      text,
    executora_nome        text,
    despesa_codigo        text,                 -- natureza da despesa (33903000 Material de Consumo)
    despesa_nome          text,
    subelemento_codigo    text,
    subelemento_nome      text,
    funcao                text,
    subfuncao             text,
    programa              text,
    acao                  text,
    fonte_recurso_codigo  text,
    fonte_recurso_nome    text,
    modalidade            text,
    contrato_id_fonte     bigint,               -- contratos_municipais.id_fonte
    contrato_id_pncp      varchar(60),
    licitacao_id_pncp     varchar(60),
    payload_hash          char(64)    NOT NULL,
    criado_em             timestamptz NOT NULL DEFAULT now(),
    atualizado_em         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fonte, id_fonte)
);
CREATE INDEX empenhos_data_idx           ON empenhos (data_empenho);
CREATE INDEX empenhos_unidade_idx        ON empenhos (unidade_id, ano);
CREATE INDEX empenhos_fornecedor_idx     ON empenhos (fornecedor_id, ano);
CREATE INDEX empenhos_contrato_fonte_idx ON empenhos (contrato_id_fonte) WHERE contrato_id_fonte IS NOT NULL;
CREATE INDEX empenhos_contrato_pncp_idx  ON empenhos (contrato_id_pncp) WHERE contrato_id_pncp IS NOT NULL;

CREATE TABLE liquidacoes (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte             text        NOT NULL DEFAULT 'eddydata',
    id_fonte          bigint      NOT NULL,
    empenho_id_fonte  bigint      NOT NULL,
    data_liquidacao   date        NOT NULL,
    valor             numeric(18, 2) NOT NULL,
    anulacao          boolean     NOT NULL DEFAULT false,   -- registro de anulação
    anulado_total     boolean     NOT NULL DEFAULT false,   -- liquidação original anulada por inteiro
    documento         text,
    payload_hash      char(64)    NOT NULL,
    criado_em         timestamptz NOT NULL DEFAULT now(),
    atualizado_em     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fonte, id_fonte)
);
CREATE INDEX liquidacoes_empenho_idx ON liquidacoes (empenho_id_fonte);
CREATE INDEX liquidacoes_data_idx    ON liquidacoes (data_liquidacao);

CREATE TABLE pagamentos (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte                text        NOT NULL DEFAULT 'eddydata',
    id_fonte             bigint      NOT NULL,
    liquidacao_id_fonte  bigint      NOT NULL,
    empenho_id_fonte     bigint,
    data_pagamento       date        NOT NULL,
    valor                numeric(18, 2) NOT NULL,
    valor_retido         numeric(18, 2),
    anulacao             boolean     NOT NULL DEFAULT false,
    anulado_total        boolean     NOT NULL DEFAULT false,
    documento            text,                  -- "OP 6034" (ordem de pagamento)
    payload_hash         char(64)    NOT NULL,
    criado_em            timestamptz NOT NULL DEFAULT now(),
    atualizado_em        timestamptz NOT NULL DEFAULT now(),
    UNIQUE (fonte, id_fonte)
);
CREATE INDEX pagamentos_empenho_idx ON pagamentos (empenho_id_fonte);
CREATE INDEX pagamentos_data_idx    ON pagamentos (data_pagamento);

CREATE TRIGGER contratos_municipais_atualizado_em BEFORE UPDATE ON contratos_municipais
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();
CREATE TRIGGER contrato_aditamentos_atualizado_em BEFORE UPDATE ON contrato_aditamentos
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();
CREATE TRIGGER empenhos_atualizado_em BEFORE UPDATE ON empenhos
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();
CREATE TRIGGER liquidacoes_atualizado_em BEFORE UPDATE ON liquidacoes
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();
CREATE TRIGGER pagamentos_atualizado_em BEFORE UPDATE ON pagamentos
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- Valor líquido: registro de anulação conta negativo, venha com o sinal que vier.
CREATE OR REPLACE FUNCTION valor_liquido(valor numeric, anulacao boolean) RETURNS numeric
LANGUAGE sql IMMUTABLE PARALLEL SAFE
AS $$ SELECT CASE WHEN anulacao THEN -abs(valor) ELSE valor END $$;

-- Empenhado, liquidado e pago por empenho (base das demais views).
CREATE VIEW vw_execucao_empenho AS
SELECT e.id, e.id_fonte, e.ano, e.data_empenho, e.unidade_id, e.fornecedor_id, e.credor_nome,
       e.contrato_id_fonte, e.contrato_id_pncp, e.licitacao_id_pncp,
       e.valor AS empenhado,
       coalesce(l.liquidado, 0) AS liquidado,
       coalesce(p.pago, 0)      AS pago
  FROM empenhos e
  LEFT JOIN (SELECT empenho_id_fonte, sum(valor_liquido(valor, anulacao)) AS liquidado
               FROM liquidacoes GROUP BY empenho_id_fonte) l ON l.empenho_id_fonte = e.id_fonte
  LEFT JOIN (SELECT empenho_id_fonte, sum(valor_liquido(valor, anulacao)) AS pago
               FROM pagamentos GROUP BY empenho_id_fonte) p ON p.empenho_id_fonte = e.id_fonte;

-- Gasto por secretaria e ano (card "onde o dinheiro vai").
CREATE VIEW vw_despesa_por_secretaria AS
SELECT x.ano, u.id AS unidade_id, u.codigo, u.nome AS secretaria,
       sum(x.empenhado) AS empenhado, sum(x.liquidado) AS liquidado, sum(x.pago) AS pago
  FROM vw_execucao_empenho x
  JOIN unidades_orcamentarias u ON u.id = x.unidade_id
 GROUP BY x.ano, u.id, u.codigo, u.nome;

-- Contratado × executado: contrato do PNCP com o que foi empenhado e pago contra ele no sistema municipal.
CREATE VIEW vw_contratado_x_pago AS
SELECT c.id AS contrato_id, c.id_pncp, c.valor_total AS contratado,
       coalesce(sum(x.empenhado), 0) AS empenhado,
       coalesce(sum(x.liquidado), 0) AS liquidado,
       coalesce(sum(x.pago), 0)      AS pago,
       count(x.id)                   AS empenhos
  FROM contratos c
  LEFT JOIN vw_execucao_empenho x ON x.contrato_id_pncp = c.id_pncp
 GROUP BY c.id, c.id_pncp, c.valor_total;

-- Contratos do sistema municipal sem correspondente no PNCP (lacuna de publicação a investigar).
CREATE VIEW vw_contratos_municipais_fora_do_pncp AS
SELECT cm.*
  FROM contratos_municipais cm
 WHERE NOT cm.excluido
   AND (cm.id_pncp IS NULL OR NOT EXISTS (SELECT 1 FROM contratos c WHERE c.id_pncp = cm.id_pncp));
