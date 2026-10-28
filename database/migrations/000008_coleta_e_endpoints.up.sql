-- 000008 · Operação da coleta: registro de endpoints mapeados (REA), execuções e camada bruta

-- Espelho dos arquivos services/collectors/endpoints/*.yaml (o YAML versionado no git é a fonte da verdade).
CREATE TABLE endpoints_mapeados (
    id               text PRIMARY KEY,                -- slug: "transparencia.despesas.empenhos"
    portal           text NOT NULL,                   -- "transparencia.franca.sp.gov.br"
    descricao        text,
    metodo           text NOT NULL DEFAULT 'GET' CHECK (metodo IN ('GET', 'POST')),
    url              text NOT NULL,
    status           text NOT NULL DEFAULT 'a_mapear'
                     CHECK (status IN ('a_mapear', 'mapeado', 'validado', 'quebrado', 'descontinuado')),
    ativo            boolean NOT NULL DEFAULT false,
    destino          text,                            -- entidade lógica alimentada (licitacoes, despesas...)
    spec             jsonb NOT NULL,
    spec_sha256      char(64) NOT NULL,
    descoberto_em    date,
    descoberto_por   text,
    ultimo_teste_em  timestamptz,
    ultimo_teste_ok  boolean,
    criado_em        timestamptz NOT NULL DEFAULT now(),
    atualizado_em    timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER endpoints_mapeados_atualizado_em BEFORE UPDATE ON endpoints_mapeados
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- Cada execução de coletor; a última janela com sucesso vira o cursor da coleta incremental.
CREATE TABLE execucoes_coleta (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    coletor            text NOT NULL,                 -- "pncp.contratacoes", "pncp.contratos", "rea:<id>"
    endpoint_id        text REFERENCES endpoints_mapeados (id) ON DELETE SET NULL,
    status             text NOT NULL DEFAULT 'executando'
                       CHECK (status IN ('executando', 'sucesso', 'parcial', 'erro')),
    parametros         jsonb NOT NULL DEFAULT '{}'::jsonb,
    janela_inicio      date,
    janela_fim         date,
    registros_lidos    integer NOT NULL DEFAULT 0,
    registros_gravados integer NOT NULL DEFAULT 0,
    registros_erro     integer NOT NULL DEFAULT 0,
    erro               text,
    iniciado_em        timestamptz NOT NULL DEFAULT now(),
    finalizado_em      timestamptz
);

CREATE INDEX execucoes_cursor_idx ON execucoes_coleta (coletor, janela_fim DESC) WHERE status = 'sucesso';

-- Camada bruta (bronze) para fontes ainda sem modelo próprio: o que o endpoint devolveu, intacto.
CREATE TABLE registros_brutos (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    endpoint_id  text   NOT NULL REFERENCES endpoints_mapeados (id) ON DELETE CASCADE,
    chave        text   NOT NULL,                     -- id natural do registro na fonte (ou hash)
    payload      jsonb  NOT NULL,
    mapeado      jsonb,                               -- campos normalizados segundo o "mapeamento" do YAML
    payload_hash char(64) NOT NULL,
    execucao_id  bigint REFERENCES execucoes_coleta (id) ON DELETE SET NULL,
    coletado_em  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (endpoint_id, chave)
);
