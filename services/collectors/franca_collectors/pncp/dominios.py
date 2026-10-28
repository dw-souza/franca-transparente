"""Tabelas de domínio do PNCP (https://pncp.gov.br/app/entidades-dominio)."""

MODALIDADES: dict[int, str] = {
    1: "Leilão - Eletrônico",
    2: "Diálogo Competitivo",
    3: "Concurso",
    4: "Concorrência - Eletrônica",
    5: "Concorrência - Presencial",
    6: "Pregão - Eletrônico",
    7: "Pregão - Presencial",
    8: "Dispensa de Licitação",
    9: "Inexigibilidade",
    10: "Manifestação de Interesse",
    11: "Pré-qualificação",
    12: "Credenciamento",
    13: "Leilão - Presencial",
}

# Limites de tamanhoPagina na API de consulta (mínimo 10; abaixo disso a API devolve 400).
PAGINA_MIN = 10
PAGINA_MAX_CONTRATACOES = 50
PAGINA_MAX_CONTRATOS = 500
