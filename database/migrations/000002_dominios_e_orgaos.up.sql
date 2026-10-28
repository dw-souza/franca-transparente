-- 000002 · Tabelas de domínio e órgãos públicos

-- Modalidades de contratação (tabela de domínio do PNCP, Lei 14.133/21).
-- O collector insere automaticamente códigos novos que a API passar a devolver.
CREATE TABLE modalidades_contratacao (
    id   smallint PRIMARY KEY,
    nome text     NOT NULL
);

INSERT INTO modalidades_contratacao (id, nome) VALUES
    (1,  'Leilão - Eletrônico'),
    (2,  'Diálogo Competitivo'),
    (3,  'Concurso'),
    (4,  'Concorrência - Eletrônica'),
    (5,  'Concorrência - Presencial'),
    (6,  'Pregão - Eletrônico'),
    (7,  'Pregão - Presencial'),
    (8,  'Dispensa de Licitação'),
    (9,  'Inexigibilidade'),
    (10, 'Manifestação de Interesse'),
    (11, 'Pré-qualificação'),
    (12, 'Credenciamento'),
    (13, 'Leilão - Presencial');

-- Órgãos compradores (Prefeitura, Câmara, autarquias, fundos com CNPJ próprio...).
-- Franca tem vários CNPJs compradores; o collector descobre os que aparecem no PNCP.
CREATE TABLE orgaos (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cnpj          varchar(14) NOT NULL UNIQUE
                  CHECK (cnpj ~ '^[0-9A-Z]{12}[0-9]{2}$'),
    razao_social  text        NOT NULL,
    nome_curto    text,                       -- "Prefeitura", "Câmara", "Unifacef"... (curadoria)
    poder         varchar(2),                 -- PNCP poderId (E, L, J, N)
    esfera        varchar(2),                 -- PNCP esferaId (F, E, M, D, N)
    codigo_ibge   char(7),
    municipio     text,
    uf            char(2),
    criado_em     timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX orgaos_codigo_ibge_idx ON orgaos (codigo_ibge);
CREATE INDEX orgaos_razao_trgm_idx  ON orgaos USING gin (f_unaccent(razao_social) gin_trgm_ops);

CREATE TRIGGER orgaos_atualizado_em BEFORE UPDATE ON orgaos
    FOR EACH ROW EXECUTE FUNCTION set_atualizado_em();

-- Semente: Prefeitura Municipal de Franca (CNPJ 47.970.769/0001-04).
INSERT INTO orgaos (cnpj, razao_social, nome_curto, poder, esfera, codigo_ibge, municipio, uf)
VALUES ('47970769000104', 'MUNICIPIO DE FRANCA', 'Prefeitura', 'E', 'M', '3516200', 'Franca', 'SP');
