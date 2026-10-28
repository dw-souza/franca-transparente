"""Registro de endpoints mapeados por engenharia reversa (REA) dos portais municipais.

Fluxo: tráfego capturado (HAR) → `har.analisar` lista candidatos → YAML em endpoints/ →
`spec.carregar_specs` valida → `runner.coletar_endpoint` executa e grava na camada bruta.
"""
