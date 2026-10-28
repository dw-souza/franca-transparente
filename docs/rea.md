# Mapeando APIs internas dos portais (REA)

Os portais de transparência municipais quase sempre carregam as tabelas via chamadas AJAX que devolvem
JSON. Consumir essas chamadas é mais estável e barato que raspar HTML. Este é o fluxo do projeto.

## Regras

- Só dados públicos, acessíveis sem login. Nada de contornar autenticação, CAPTCHA ou WAF:
  se aparecer desafio, o coletor para (falha fechada) e a gente pede os dados pela LAI.
- Ritmo educado: `intervalo_segundos` ≥ 1 em portais municipais, coleta fora do horário comercial,
  User-Agent identificando o projeto com contato.
- Toda descoberta fica documentada no YAML (`descoberta:`), com evidência reproduzível.

## Passo a passo

1. Abra o portal com DevTools › Network (filtro Fetch/XHR), marque *Preserve log*.
2. Use a tela de interesse como um cidadão: filtre por período, troque de página, mude o tamanho da página,
   clique em "exportar". Cada ação revela um parâmetro.
3. *Save all as HAR* e rode a triagem:

   ```bash
   python -m franca_collectors rea har captura.har --host transparencia.franca.sp.gov.br --yaml rascunho.yaml
   ```

   A saída lista, por ordem de relevância, as chamadas que devolvem listas de objetos JSON, com
   parâmetros, caminho da lista (`registros_em`) e campos. O `--yaml` gera rascunhos de spec.
4. Copie o rascunho para `services/collectors/endpoints/franca.yaml`, ajuste:
   - `params`/`corpo` com templates de data (`"{data_inicio:%d/%m/%Y}"`), `janela_dias`;
   - `paginacao` (o rascunho adivinha `pagina`/`start`+`length`);
   - `chave` (campos que identificam o registro) e `mapeamento`.
   Antes de salvar o HAR no repositório de evidências, remova cookies e headers de sessão.
5. Teste sem gravar no banco e compare com o que o portal mostra:

   ```bash
   python -m franca_collectors rea executar transparencia.despesas.empenhos --desde 2026-10-01 --ate 2026-10-07 --forcar
   ```

6. Mude `status: mapeado`, abra PR. Depois de uma semana rodando e números conferidos por amostragem,
   `status: validado` e `ativo: true`.

Os registros desses endpoints caem em `registros_brutos` (camada bruta, com `payload` e `mapeado`).
Quando um destino estabiliza, escreve-se o normalizador para a tabela definitiva (como já existe para o PNCP).

## Formato

Veja `services/collectors/endpoints/_modelo.yaml` (todos os campos comentados). `rea validar` e os testes
validam os YAML; campos desconhecidos são erro, para pegar typo cedo.
