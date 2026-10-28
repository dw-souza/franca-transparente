"""Gravação idempotente no PostgreSQL (schema em database/migrations).

* Upsert por id natural (id_pncp / cnpj); registros idênticos (mesmo payload_hash) não geram escrita.
* Cada registro é gravado na própria transação: uma linha ruim não derruba o lote.
* `resumo_ia` é invalidado quando o objeto muda, para a IA resumir de novo.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from franca_collectors.models import Contrato, Fornecedor, Licitacao, Orgao, RegistroBruto
from franca_collectors.storage.base import Resultado, Sink

log = logging.getLogger(__name__)

_COLS_LICITACAO = (
    "id_pncp", "orgao_id", "unidade_codigo", "unidade_nome", "numero", "ano", "sequencial", "processo",
    "objeto", "informacao_complementar", "modalidade_id", "modo_disputa", "amparo_legal", "srp",
    "valor_estimado", "valor_homologado", "data_publicacao", "data_abertura", "data_encerramento",
    "status", "situacao_pncp_id", "link_sistema_origem", "fonte", "payload_hash", "payload_bruto",
    "data_atualizacao_fonte",
)

_COLS_CONTRATO = (
    "id_pncp", "id_pncp_compra", "orgao_id", "fornecedor_id", "unidade_codigo", "unidade_nome", "numero",
    "ano", "sequencial", "processo", "tipo_contrato", "categoria_processo", "objeto",
    "informacao_complementar", "valor_inicial", "valor_total", "valor_acumulado", "numero_parcelas",
    "valor_parcela", "data_assinatura", "vigencia_inicio", "vigencia_fim", "data_publicacao", "receita",
    "fonte", "payload_hash", "payload_bruto", "data_atualizacao_fonte",
)


def _upsert_sql(tabela: str, colunas: tuple[str, ...], conflito: str = "id_pncp") -> str:
    """INSERT ... ON CONFLICT DO UPDATE que só escreve quando o payload mudou."""
    sets = [f"{c} = EXCLUDED.{c}" for c in colunas if c != conflito]
    if tabela in ("licitacoes", "contratos"):
        for col in ("resumo_ia", "resumo_ia_modelo", "resumo_ia_em"):
            sets.append(
                f"{col} = CASE WHEN {tabela}.objeto IS DISTINCT FROM EXCLUDED.objeto "
                f"THEN NULL ELSE {tabela}.{col} END"
            )
    return (
        f"INSERT INTO {tabela} ({', '.join(colunas)})\n"
        f"VALUES ({', '.join(f'%({c})s' for c in colunas)})\n"
        f"ON CONFLICT ({conflito}) DO UPDATE SET\n  " + ",\n  ".join(sets) + "\n"
        f"WHERE {tabela}.payload_hash IS DISTINCT FROM EXCLUDED.payload_hash\n"
        "RETURNING (xmax = 0) AS inserido"
    )


UPSERT_LICITACAO = _upsert_sql("licitacoes", _COLS_LICITACAO)
UPSERT_CONTRATO = _upsert_sql("contratos", _COLS_CONTRATO)

# CTE: devolve o id tanto no insert quanto no conflito sem alteração.
UPSERT_ORGAO = """
WITH ins AS (
    INSERT INTO orgaos (cnpj, razao_social, poder, esfera, codigo_ibge, municipio, uf)
    VALUES (%(cnpj)s, %(razao_social)s, %(poder)s, %(esfera)s, %(codigo_ibge)s, %(municipio)s, %(uf)s)
    ON CONFLICT (cnpj) DO UPDATE SET
        razao_social = EXCLUDED.razao_social,
        poder        = COALESCE(EXCLUDED.poder, orgaos.poder),
        esfera       = COALESCE(EXCLUDED.esfera, orgaos.esfera),
        codigo_ibge  = COALESCE(EXCLUDED.codigo_ibge, orgaos.codigo_ibge),
        municipio    = COALESCE(EXCLUDED.municipio, orgaos.municipio),
        uf           = COALESCE(EXCLUDED.uf, orgaos.uf)
    WHERE (orgaos.razao_social, orgaos.poder, orgaos.esfera, orgaos.codigo_ibge, orgaos.municipio, orgaos.uf)
          IS DISTINCT FROM
          (EXCLUDED.razao_social, COALESCE(EXCLUDED.poder, orgaos.poder), COALESCE(EXCLUDED.esfera, orgaos.esfera),
           COALESCE(EXCLUDED.codigo_ibge, orgaos.codigo_ibge), COALESCE(EXCLUDED.municipio, orgaos.municipio),
           COALESCE(EXCLUDED.uf, orgaos.uf))
    RETURNING id
)
SELECT id FROM ins
UNION ALL
SELECT id FROM orgaos WHERE cnpj = %(cnpj)s
LIMIT 1
"""

UPSERT_FORNECEDOR = """
WITH ins AS (
    INSERT INTO fornecedores (cnpj_cpf, tipo_pessoa, razao_social)
    VALUES (%(cnpj_cpf)s, %(tipo_pessoa)s, %(razao_social)s)
    ON CONFLICT (cnpj_cpf) DO UPDATE SET razao_social = EXCLUDED.razao_social
    WHERE fornecedores.enriquecido_em IS NULL               -- dado da Receita prevalece
      AND fornecedores.razao_social IS DISTINCT FROM EXCLUDED.razao_social
    RETURNING id
)
SELECT id FROM ins
UNION ALL
SELECT id FROM fornecedores WHERE cnpj_cpf = %(cnpj_cpf)s
LIMIT 1
"""

GARANTIR_MODALIDADE = """
INSERT INTO modalidades_contratacao (id, nome) VALUES (%(id)s, %(nome)s) ON CONFLICT (id) DO NOTHING
"""

UPSERT_REGISTRO_BRUTO = """
INSERT INTO registros_brutos (endpoint_id, chave, payload, mapeado, payload_hash, execucao_id)
VALUES (%(endpoint_id)s, %(chave)s, %(payload)s, %(mapeado)s, %(payload_hash)s, %(execucao_id)s)
ON CONFLICT (endpoint_id, chave) DO UPDATE SET
    payload = EXCLUDED.payload, mapeado = EXCLUDED.mapeado, payload_hash = EXCLUDED.payload_hash,
    execucao_id = EXCLUDED.execucao_id, coletado_em = now()
WHERE registros_brutos.payload_hash IS DISTINCT FROM EXCLUDED.payload_hash
RETURNING (xmax = 0) AS inserido
"""

UPSERT_ENDPOINT = """
INSERT INTO endpoints_mapeados (id, portal, descricao, metodo, url, status, ativo, destino, spec, spec_sha256,
                                descoberto_em, descoberto_por)
VALUES (%(id)s, %(portal)s, %(descricao)s, %(metodo)s, %(url)s, %(status)s, %(ativo)s, %(destino)s, %(spec)s,
        %(spec_sha256)s, %(descoberto_em)s, %(descoberto_por)s)
ON CONFLICT (id) DO UPDATE SET
    portal = EXCLUDED.portal, descricao = EXCLUDED.descricao, metodo = EXCLUDED.metodo, url = EXCLUDED.url,
    status = EXCLUDED.status, ativo = EXCLUDED.ativo, destino = EXCLUDED.destino, spec = EXCLUDED.spec,
    spec_sha256 = EXCLUDED.spec_sha256, descoberto_em = EXCLUDED.descoberto_em,
    descoberto_por = EXCLUDED.descoberto_por
WHERE endpoints_mapeados.spec_sha256 IS DISTINCT FROM EXCLUDED.spec_sha256
"""

INICIAR_EXECUCAO = """
INSERT INTO execucoes_coleta (coletor, endpoint_id, parametros, janela_inicio, janela_fim)
VALUES (%(coletor)s, %(endpoint_id)s, %(parametros)s, %(janela_inicio)s, %(janela_fim)s)
RETURNING id
"""

FINALIZAR_EXECUCAO = """
UPDATE execucoes_coleta
   SET status = %(status)s, registros_lidos = %(lidos)s, registros_gravados = %(gravados)s,
       registros_erro = %(erros)s, erro = %(erro)s, finalizado_em = now()
 WHERE id = %(id)s
"""

ULTIMA_JANELA = """
SELECT max(janela_fim) FROM execucoes_coleta WHERE coletor = %(coletor)s AND status = 'sucesso'
"""


class PostgresSink(Sink):
    nome = "postgres"

    def __init__(self, database_url: str, conexao: Any | None = None):
        if conexao is None:
            try:
                import psycopg
            except ImportError as exc:  # pragma: no cover - depende do ambiente
                raise RuntimeError("Instale o extra: pip install 'franca-collectors[postgres]'") from exc
            conexao = psycopg.connect(database_url, autocommit=True)
        self.conn = conexao
        self._orgaos: dict[str, int] = {}
        self._fornecedores: dict[str, int] = {}
        self._modalidades: set[int] = set()

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _json(valor: Any) -> Any:
        try:
            from psycopg.types.json import Jsonb
        except ImportError:  # permite testar o SQL com uma conexão falsa
            return json.dumps(valor, ensure_ascii=False, default=str) if valor is not None else None
        return Jsonb(valor) if valor is not None else None

    def _um(self, sql: str, params: dict[str, Any]):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone() if cur.description else None

    def _orgao_id(self, orgao: Orgao) -> int:
        if orgao.cnpj not in self._orgaos:
            self._orgaos[orgao.cnpj] = self._um(UPSERT_ORGAO, orgao.model_dump())[0]
        return self._orgaos[orgao.cnpj]

    def _fornecedor_id(self, f: Fornecedor) -> int:
        if f.cnpj_cpf not in self._fornecedores:
            self._fornecedores[f.cnpj_cpf] = self._um(UPSERT_FORNECEDOR, f.model_dump())[0]
        return self._fornecedores[f.cnpj_cpf]

    @contextmanager
    def _transacao(self) -> Iterator[None]:
        """Transação por registro; se falhar, os ids criados nela somem do banco e também do cache."""
        try:
            with self.conn.transaction():
                yield
        except Exception:
            self._orgaos.clear()
            self._fornecedores.clear()
            self._modalidades.clear()
            raise

    @staticmethod
    def _resultado(linha) -> Resultado:
        if linha is None:
            return "inalterado"
        return "inserido" if linha[0] else "atualizado"

    # --------------------------------------------------------------- gravação
    def salvar_licitacao(self, l: Licitacao) -> Resultado:
        with self._transacao():
            if l.modalidade_id is not None and l.modalidade_id not in self._modalidades:
                self._um(GARANTIR_MODALIDADE, {"id": l.modalidade_id,
                                               "nome": l.modalidade_nome or f"Modalidade {l.modalidade_id}"})
                self._modalidades.add(l.modalidade_id)
            params = l.model_dump(exclude={"orgao", "modalidade_nome"})
            params["orgao_id"] = self._orgao_id(l.orgao)
            params["payload_bruto"] = self._json(l.payload_bruto)
            return self._resultado(self._um(UPSERT_LICITACAO, params))

    def salvar_contrato(self, c: Contrato) -> Resultado:
        with self._transacao():
            params = c.model_dump(exclude={"orgao", "fornecedor"})
            params["orgao_id"] = self._orgao_id(c.orgao)
            params["fornecedor_id"] = self._fornecedor_id(c.fornecedor)
            params["payload_bruto"] = self._json(c.payload_bruto)
            return self._resultado(self._um(UPSERT_CONTRATO, params))

    def salvar_registro_bruto(self, r: RegistroBruto, execucao_id: int | None = None) -> Resultado:
        with self.conn.transaction():
            params = r.model_dump()
            params.update(payload=self._json(r.payload), mapeado=self._json(r.mapeado), execucao_id=execucao_id)
            return self._resultado(self._um(UPSERT_REGISTRO_BRUTO, params))

    def sincronizar_endpoint(self, spec: dict[str, Any], spec_sha256: str) -> None:
        descoberta = spec.get("descoberta") or {}
        self._um(UPSERT_ENDPOINT, {
            "id": spec["id"], "portal": spec["portal"], "descricao": spec.get("descricao"),
            "metodo": spec.get("metodo", "GET"), "url": spec["url"], "status": spec.get("status", "a_mapear"),
            "ativo": bool(spec.get("ativo")), "destino": spec.get("destino"), "spec": self._json(spec),
            "spec_sha256": spec_sha256, "descoberto_em": descoberta.get("em"),
            "descoberto_por": descoberta.get("por"),
        })

    # --------------------------------------------------------------- execuções
    def iniciar_execucao(self, coletor, parametros, janela_inicio=None, janela_fim=None, endpoint_id=None):
        return self._um(INICIAR_EXECUCAO, {
            "coletor": coletor, "endpoint_id": endpoint_id, "parametros": self._json(parametros),
            "janela_inicio": janela_inicio, "janela_fim": janela_fim,
        })[0]

    def finalizar_execucao(self, execucao_id, status, lidos, gravados, erros, erro=None):
        if execucao_id is not None:
            self._um(FINALIZAR_EXECUCAO, {"id": execucao_id, "status": status, "lidos": lidos,
                                          "gravados": gravados, "erros": erros, "erro": erro})

    def ultima_janela(self, coletor: str) -> date | None:
        linha = self._um(ULTIMA_JANELA, {"coletor": coletor})
        valor = linha[0] if linha else None
        return date.fromisoformat(valor) if isinstance(valor, str) else valor

    def close(self) -> None:
        self.conn.close()
