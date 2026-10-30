# Assistente do Residencial Aurora

API de atendimento condominial em Python e Google ADK. O [enunciado original](planejamento/ENUNCIADO.md) e o [plano técnico](planejamento/ANALISE-TECNICA.md) estão preservados no repositório.

## Arquitetura

O agente principal encaminha pedidos a dois subagentes, especialistas em reservas e visitantes, por transferência do ADK. O principal consulta o regulamento por uma tool de busca de artigos. As tools em `aurora/agents.py` acessam `aurora/storage.py`; o modelo não recebe uma tool administrativa para escolher um apartamento. O serviço de sessões do ADK e os dados do condomínio usam bancos SQLite locais separados. A API em `aurora/api.py` expõe o contrato HTTP do enunciado.

A busca textual do regulamento é simples e retorna no máximo um artigo. Ela pode falhar em perguntas formuladas com sinônimos ou que exigem mais de um artigo; a cobertura precisa ser avaliada com o modelo real.

## Garantias

1. **Confirmação:** `reservar_area` e `autorizar_visitante`, em `aurora/agents.py`, solicitam confirmação ADK para áreas pagas e visitantes antes de gravar; a rota de confirmação em `aurora/api.py` verifica o ID pendente na sessão e envia uma resposta estruturada ao Runner. `efeitos` em `aurora/storage.py` registra o efeito da chamada de forma transacional. Áreas gratuitas e cancelamentos não pedem confirmação.
2. **Isolamento:** `_apartment` em `aurora/agents.py` obtém o apartamento pelo ID da sessão armazenado pelo servidor. As consultas e cancelamentos em `aurora/storage.py` filtram pelo apartamento; disponibilidade retorna apenas livre ou ocupada.
3. **Persistência:** `DatabaseSessionService` em `aurora/api.py` guarda os eventos, enquanto `aurora/storage.py` guarda reservas e visitantes. Reservas canceladas permanecem no banco para impedir reutilização de códigos.
4. **Regulamento:** `consultar_regulamento` em `aurora/agents.py` lê o arquivo sob demanda e devolve no máximo um artigo selecionado; o regulamento não está nas instruções do principal. A relevância da busca é uma limitação a validar.
5. **Concorrência:** o índice SQLite `reserva_ativa_unica` em `aurora/storage.py` impede duas reservas ativas de uma mesma área e data; a transação de gravação retorna ocupada quando a vaga já foi tomada.

## Como rodar

Pré-requisitos: Python 3.12 ou superior, `uv`, chave Google AI Studio e acesso a um modelo Gemini que aceite chamadas de função. A versão `google-adk` está fixada em 2.9.1. A disponibilidade e os limites dependem da conta; configure `GEMINI_MODEL` se necessário. A documentação do Google recomenda [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) para novos projetos e registra restrição de acesso à [família 2.5](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash).

```sh
cp .env.example .env
# Preencha GOOGLE_API_KEY e, se necessário, GEMINI_MODEL no .env.
uv sync
uv run python -m aurora.storage
uv run uvicorn aurora.api:app --host 0.0.0.0 --port 8000
```

A restauração deve ser executada com a API parada: ela restaura reservas e visitantes dos arquivos originais e **apaga todas as sessões e seu histórico**. A API inicializa os dados na primeira execução caso ainda não existam. Os arquivos de estado ficam em `.runtime/`; `AURORA_DB` e `AURORA_SESSION_DB` podem apontar para arquivos distintos em outros locais.

Para executar as verificações locais com modelo simulado:

```sh
uv run python -m unittest discover -s tests -v
```

Para repetir os principais cenários com o Gemini real, com a porta 8000 livre e uma chave configurada, execute `uv run python scripts/validacao_real.py`. O roteiro cria bancos temporários e faz várias chamadas ao modelo, sujeitas aos limites e custos da conta.

Os testes locais cobrem concorrência no armazenamento, isolamento básico, recusa, confirmação após reinício e reenvio, mas não substituem o fluxo completo do avaliador. Os principais cenários do avaliador foram executados com Gemini real em clone limpo, incluindo disputa simultânea; a aprovação após reinício foi verificada em uma execução separada. Como as respostas dependem do modelo e a busca do regulamento é lexical, isso não garante sucesso para todas as formulações.
