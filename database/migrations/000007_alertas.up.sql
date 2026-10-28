-- 000007 · Alertas cívicos (assinaturas de cidadãos) e registro de disparos

CREATE TABLE alertas (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nome               text NOT NULL,                     -- "Licitações de asfalto acima de R$ 100 mil"
    tipo_evento        text NOT NULL
                       CHECK (tipo_evento IN ('nova_licitacao', 'novo_contrato', 'novo_ato_diario', 'sinal_risco')),
    -- Ex.: {"palavras": ["asfalto"], "modalidades": [6, 8], "valor_min": 100000,
    --       "cnpj_fornecedor": "...", "unidade": "Secretaria de Saúde"}
    criterios          jsonb NOT NULL DEFAULT '{}'::jsonb,

    canal              text NOT NULL DEFAULT 'email'
                       CHECK (canal IN ('email', 'webhook', 'telegram')),
    destino            text NOT NULL,                     -- e-mail/URL: dado pessoal (LGPD), nunca exposto na API pública
    confirmado_em      timestamptz,                       -- double opt-in; só alertas confirmados disparam
    token_cancelamento uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    ativo              boolean NOT NULL DEFAULT true,
    ultimo_disparo_em  timestamptz,

    criado_em          timestamptz NOT NULL DEFAULT now(),
    atualizado_em      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX alertas_ativos_idx ON alertas (tipo_evento) WHERE ativo AND confirmado_em IS NOT NULL;

CREATE TRIGGER alertas_atualizado_em BEFORE UPDATE ON alertas
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- Garante no máximo um aviso por (alerta, registro): reprocessar a coleta não reenvia.
CREATE TABLE alertas_disparos (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alerta_id   bigint NOT NULL REFERENCES alertas (id) ON DELETE CASCADE,
    entidade    text   NOT NULL CHECK (entidade IN ('licitacao', 'contrato', 'diario_ato', 'sinal_risco')),
    entidade_id bigint NOT NULL,
    status      text   NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'enviado', 'falhou')),
    enviado_em  timestamptz,
    erro        text,
    criado_em   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (alerta_id, entidade, entidade_id)
);

CREATE INDEX alertas_disparos_pendentes_idx ON alertas_disparos (criado_em) WHERE status = 'pendente';
