-- 000006 · Diário Oficial do Município de Franca (DOMF) e atos extraídos
-- Pipeline: pendente → baixado → texto_extraido → processado (IA) | erro

CREATE TABLE diarios_oficiais (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte                text     NOT NULL DEFAULT 'prefeitura'
                         CHECK (fonte IN ('prefeitura', 'camara')),
    data_publicacao      date     NOT NULL,
    numero_edicao        text,                         -- texto: há edições como "1234-A"
    edicao_extra         boolean  NOT NULL DEFAULT false,
    url_pdf              text     NOT NULL UNIQUE,
    pdf_sha256           char(64) UNIQUE,              -- detecta republicação do mesmo arquivo
    tamanho_bytes        bigint,
    paginas              integer,

    texto_bruto          text,
    metodo_extracao      text CHECK (metodo_extracao IN ('pdf_texto', 'ocr', 'misto')),
    status_processamento text     NOT NULL DEFAULT 'pendente'
                         CHECK (status_processamento IN ('pendente', 'baixado', 'texto_extraido', 'processado', 'erro')),

    processado_ia        boolean  NOT NULL DEFAULT false,
    processado_ia_em     timestamptz,
    modelo_ia            text,
    resumo_ia            text,
    extracao_ia          jsonb,                        -- saída estruturada (JSON Schema) da edição inteira

    tentativas           smallint NOT NULL DEFAULT 0,
    erro_ultimo          text,

    criado_em            timestamptz NOT NULL DEFAULT now(),
    atualizado_em        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT diarios_edicao_unica UNIQUE NULLS NOT DISTINCT (fonte, data_publicacao, numero_edicao, edicao_extra)
);

-- Sem tsvector da edição inteira: um diário grande estoura o limite de 1 MB do tsvector.
-- A busca textual é feita nos atos (abaixo).
CREATE INDEX diarios_data_idx       ON diarios_oficiais (data_publicacao DESC);
CREATE INDEX diarios_fila_status_idx ON diarios_oficiais (status_processamento) WHERE status_processamento <> 'processado';
CREATE INDEX diarios_fila_ia_idx    ON diarios_oficiais (data_publicacao) WHERE NOT processado_ia;

CREATE TRIGGER diarios_atualizado_em BEFORE UPDATE ON diarios_oficiais
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- Atos individuais segmentados de cada edição (decretos, extratos de contrato, avisos de licitação...)
CREATE TABLE diario_atos (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    diario_id      bigint  NOT NULL REFERENCES diarios_oficiais (id) ON DELETE CASCADE,
    ordem          integer NOT NULL,                  -- posição do ato na edição
    pagina_inicio  integer,
    pagina_fim     integer,

    tipo_ato       text,     -- decreto, portaria, lei, extrato_contrato, aviso_licitacao, homologacao, nomeacao...
    numero         text,
    orgao_emissor  text,
    titulo         text,
    ementa         text,
    texto          text     NOT NULL,

    valor          numeric(18, 2),
    cnpjs_citados  text[]   NOT NULL DEFAULT '{}',    -- normalizados; cruzamento com fornecedores
    licitacao_id   bigint   REFERENCES licitacoes (id) ON DELETE SET NULL,
    contrato_id    bigint   REFERENCES contratos (id)  ON DELETE SET NULL,

    resumo_ia      text,
    entidades_ia   jsonb,

    busca          tsvector GENERATED ALWAYS AS (
                       setweight(to_tsvector('pt_unaccent', coalesce(titulo, '')), 'A') ||
                       setweight(to_tsvector('pt_unaccent', coalesce(ementa, '')), 'B') ||
                       setweight(to_tsvector('pt_unaccent', left(texto, 200000)), 'C')
                   ) STORED,

    criado_em      timestamptz NOT NULL DEFAULT now(),
    atualizado_em  timestamptz NOT NULL DEFAULT now(),

    UNIQUE (diario_id, ordem)
);

CREATE INDEX diario_atos_tipo_idx      ON diario_atos (tipo_ato);
CREATE INDEX diario_atos_cnpjs_idx     ON diario_atos USING gin (cnpjs_citados);
CREATE INDEX diario_atos_busca_idx     ON diario_atos USING gin (busca);
CREATE INDEX diario_atos_licitacao_idx ON diario_atos (licitacao_id) WHERE licitacao_id IS NOT NULL;
CREATE INDEX diario_atos_contrato_idx  ON diario_atos (contrato_id)  WHERE contrato_id  IS NOT NULL;

CREATE TRIGGER diario_atos_atualizado_em BEFORE UPDATE ON diario_atos
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();
