"""Gravação idempotente no PostgreSQL (schema em database/migrations).

* Upsert por id natural (id_pncp / cnpj); registros idênticos (mesmo payload_hash) não geram escrita.
* Cada registro é gravado na própria transação: uma linha ruim não derruba o lote.
* `resumo_ia` é invalidado quando o objeto muda, para a IA resumir de novo.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any

from franca_collectors.models import Contrato, Fornecedor, Licitacao, LicitacaoItem, Orgao, RegistroBruto
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


def _upsert_sql(tabela: str, colunas: tuple[str, ...], conflito: tuple[str, ...] = ("id_pncp",)) -> str:
    """INSERT ... ON CONFLICT DO UPDATE que só escreve quando o payload mudou."""
    sets = [f"{c} = EXCLUDED.{c}" for c in colunas if c not in conflito]
    if tabela in ("licitacoes", "contratos"):
        for col in ("resumo_ia", "resumo_ia_modelo", "resumo_ia_em"):
            sets.append(
                f"{col} = CASE WHEN {tabela}.objeto IS DISTINCT FROM EXCLUDED.objeto "
                f"THEN NULL ELSE {tabela}.{col} END"
            )
    return (
        f"INSERT INTO {tabela} ({', '.join(colunas)})\n"
        f"VALUES ({', '.join(f'%({c})s' for c in colunas)})\n"
        f"ON CONFLICT ({', '.join(conflito)}) DO UPDATE SET\n  " + ",\n  ".join(sets) + "\n"
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

# ------------------------------------------------------------------ sistema municipal (EddyData)
# Órgão e fornecedor vindos do EddyData só são criados se faltarem: o nome do PNCP/Receita prevalece.
GARANTIR_ORGAO = """
WITH ins AS (
    INSERT INTO orgaos (cnpj, razao_social) VALUES (%(cnpj)s, %(razao_social)s) ON CONFLICT (cnpj) DO NOTHING
    RETURNING id
)
SELECT id FROM ins UNION ALL SELECT id FROM orgaos WHERE cnpj = %(cnpj)s LIMIT 1
"""

GARANTIR_FORNECEDOR = """
WITH ins AS (
    INSERT INTO fornecedores (cnpj_cpf, tipo_pessoa, razao_social)
    VALUES (%(cnpj_cpf)s, %(tipo_pessoa)s, %(razao_social)s) ON CONFLICT (cnpj_cpf) DO NOTHING RETURNING id
)
SELECT id FROM ins UNION ALL SELECT id FROM fornecedores WHERE cnpj_cpf = %(cnpj_cpf)s LIMIT 1
"""

UPSERT_UNIDADE = """
WITH ins AS (
    INSERT INTO unidades_orcamentarias (orgao_id, codigo, nome) VALUES (%(orgao_id)s, %(codigo)s, %(nome)s)
    ON CONFLICT (orgao_id, codigo) DO UPDATE SET nome = EXCLUDED.nome
    WHERE unidades_orcamentarias.nome IS DISTINCT FROM EXCLUDED.nome
    RETURNING id
)
SELECT id FROM ins
UNION ALL
SELECT id FROM unidades_orcamentarias WHERE orgao_id = %(orgao_id)s AND codigo = %(codigo)s
LIMIT 1
"""

_CHAVE_FONTE = ("fonte", "id_fonte")
_MUNICIPAL: dict[str, tuple[str, tuple[str, ...]]] = {
    "empenho": ("empenhos", (
        "fonte", "id_fonte", "orgao_id", "unidade_id", "fornecedor_id", "credor_nome", "numero", "ano", "especie",
        "tipo_empenho", "data_empenho", "valor", "processo", "historico", "executora_codigo", "executora_nome",
        "despesa_codigo", "despesa_nome", "subelemento_codigo", "subelemento_nome", "funcao", "subfuncao",
        "programa", "acao", "fonte_recurso_codigo", "fonte_recurso_nome", "modalidade", "contrato_id_fonte",
        "contrato_id_pncp", "licitacao_id_pncp", "payload_hash")),
    "liquidacao": ("liquidacoes", (
        "fonte", "id_fonte", "empenho_id_fonte", "data_liquidacao", "valor", "anulacao", "anulado_total",
        "documento", "payload_hash")),
    "pagamento": ("pagamentos", (
        "fonte", "id_fonte", "liquidacao_id_fonte", "empenho_id_fonte", "data_pagamento", "valor", "valor_retido",
        "anulacao", "anulado_total", "documento", "payload_hash")),
    "contrato": ("contratos_municipais", (
        "fonte", "id_fonte", "orgao_id", "fornecedor_id", "credor_nome", "numero", "ano", "processo", "tipo",
        "tipo_contrato", "objeto", "valor", "data_assinatura", "data_inicio", "data_termino", "excluido", "inativo",
        "id_pncp", "licitacao_id_pncp", "payload_hash")),
    "aditamento": ("contrato_aditamentos", (
        "fonte", "id_fonte", "contrato_id_fonte", "numero", "finalidade", "data_aditamento", "data_inicio",
        "data_termino", "valor_total", "valor_aditado", "mudanca_vigencia", "mudanca_reajuste",
        "mudanca_favorecido", "payload_hash")),
}
UPSERT_MUNICIPAL = {tipo: _upsert_sql(tabela, cols, _CHAVE_FONTE) for tipo, (tabela, cols) in _MUNICIPAL.items()}

# Itens: fila por compra nunca coletada ou atualizada na fonte depois da última coleta de itens.
LICITACOES_SEM_ITENS = """
SELECT l.id_pncp, o.cnpj, l.ano, l.sequencial
  FROM licitacoes l
  JOIN orgaos o ON o.id = l.orgao_id
 WHERE l.sequencial IS NOT NULL
   AND (l.itens_coletados_em IS NULL OR l.data_atualizacao_fonte > l.itens_coletados_em)
 ORDER BY l.itens_coletados_em NULLS FIRST, l.data_publicacao DESC NULLS LAST
 LIMIT %(limite)s
"""

_COLS_ITEM = (
    "licitacao_id", "numero_item", "descricao", "material_servico", "unidade_medida", "quantidade",
    "valor_unitario_estimado", "valor_total_estimado", "orcamento_sigiloso", "criterio_julgamento", "situacao",
    "tem_resultado", "ncm_nbs_codigo", "catalogo_codigo", "payload_hash", "data_atualizacao_fonte",
)
_COLS_RESULTADO = (
    "item_id", "sequencial", "fornecedor_id", "quantidade_homologada", "valor_unitario_homologado",
    "valor_total_homologado", "percentual_desconto", "porte_fornecedor", "situacao", "data_resultado",
    "payload_hash", "data_atualizacao_fonte",
)


def _upsert_filho_sql(tabela: str, colunas: tuple[str, ...], chave: tuple[str, str]) -> str:
    """Upsert por chave composta que devolve (id, inserido); inserido é NULL quando nada mudou."""
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in colunas if c not in chave)
    return (
        f"WITH ins AS (\n"
        f"    INSERT INTO {tabela} ({', '.join(colunas)})\n"
        f"    VALUES ({', '.join(f'%({c})s' for c in colunas)})\n"
        f"    ON CONFLICT ({', '.join(chave)}) DO UPDATE SET {sets}\n"
        f"    WHERE {tabela}.payload_hash IS DISTINCT FROM EXCLUDED.payload_hash\n"
        f"    RETURNING id, (xmax = 0) AS inserido\n"
        f")\n"
        f"SELECT id, inserido FROM ins\n"
        f"UNION ALL\n"
        f"SELECT id, NULL FROM {tabela} WHERE {chave[0]} = %({chave[0]})s AND {chave[1]} = %({chave[1]})s\n"
        f"LIMIT 1"
    )


UPSERT_ITEM = _upsert_filho_sql("licitacao_itens", _COLS_ITEM, ("licitacao_id", "numero_item"))
UPSERT_RESULTADO = _upsert_filho_sql("licitacao_item_resultados", _COLS_RESULTADO, ("item_id", "sequencial"))

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
        self._unidades: dict[tuple[int, str], int] = {}

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
            self._unidades.clear()
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

    def _orgao_id_por_cnpj(self, cnpj: str) -> int:
        if cnpj not in self._orgaos:
            # razão social provisória: o PNCP preenche a real quando o órgão aparecer lá
            self._orgaos[cnpj] = self._um(GARANTIR_ORGAO, {"cnpj": cnpj, "razao_social": cnpj})[0]
        return self._orgaos[cnpj]

    def _garantir_fornecedor(self, f: Fornecedor) -> int:
        if f.cnpj_cpf not in self._fornecedores:
            self._fornecedores[f.cnpj_cpf] = self._um(GARANTIR_FORNECEDOR, f.model_dump())[0]
        return self._fornecedores[f.cnpj_cpf]

    def salvar_municipal(self, tipo: str, registro: Any) -> Resultado:
        params = registro.model_dump(exclude={"orgao_cnpj", "fornecedor", "unidade"})
        with self._transacao():
            if hasattr(registro, "orgao_cnpj"):
                params["orgao_id"] = self._orgao_id_por_cnpj(registro.orgao_cnpj)
            if hasattr(registro, "fornecedor"):
                params["fornecedor_id"] = self._garantir_fornecedor(registro.fornecedor) if registro.fornecedor \
                    else None
            if hasattr(registro, "unidade"):
                params["unidade_id"] = None
                if registro.unidade:
                    chave = (params["orgao_id"], registro.unidade.codigo)
                    if chave not in self._unidades:
                        self._unidades[chave] = self._um(UPSERT_UNIDADE, {"orgao_id": chave[0],
                                                         **registro.unidade.model_dump()})[0]
                    params["unidade_id"] = self._unidades[chave]
            return self._resultado(self._um(UPSERT_MUNICIPAL[tipo], params))

    def licitacoes_sem_itens(self, limite: int) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(LICITACOES_SEM_ITENS, {"limite": limite})
            return [{"id_pncp": r[0], "cnpj": r[1], "ano": r[2], "sequencial": r[3]} for r in cur.fetchall()]

    def salvar_itens(self, id_pncp: str, itens: list[LicitacaoItem]) -> dict[str, int]:
        contagem: Counter = Counter()
        with self._transacao():
            linha = self._um("SELECT id FROM licitacoes WHERE id_pncp = %(id)s", {"id": id_pncp})
            if linha is None:
                raise ValueError(f"licitação {id_pncp} não está no banco")
            licitacao_id = linha[0]
            for item in itens:
                params = item.model_dump(exclude={"resultados"})
                params["licitacao_id"] = licitacao_id
                item_id, inserido = self._um(UPSERT_ITEM, params)
                contagem[self._resultado(None if inserido is None else (inserido,))] += 1
                for res in item.resultados:
                    rp = res.model_dump(exclude={"fornecedor"})
                    rp["item_id"] = item_id
                    rp["fornecedor_id"] = self._fornecedor_id(res.fornecedor) if res.fornecedor else None
                    self._um(UPSERT_RESULTADO, rp)
            self._um("UPDATE licitacoes SET itens_coletados_em = now() WHERE id = %(id)s", {"id": licitacao_id})
        return dict(contagem)

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
