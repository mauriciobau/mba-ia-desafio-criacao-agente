# Análise e plano técnico — Residencial Aurora

Registro para retomar o desenvolvimento; análise realizada em 2026-10-29. O pedido atual autoriza planejamento, não implementação nem publicação. O enunciado continua em `README.md`; antes de substituí-lo na entrega, preserve uma cópia versionada em local apropriado.

## Estado e fontes

- Fonte primária: `planejamento/ENUNCIADO.md` (originalmente `README.md`), especialmente linhas 33–100 (restrições e garantias), 102–169 (API), 171–181 (fora de escopo), 183–217 (avaliador), 219–284 (aceite, entrega e alertas).
- `dados/` contém somente os arquivos iniciais; não há aplicação, dependências ou testes versionados. Os cinco arquivos são imutáveis. Os dados incluem quadra gratuita, salão e churrasqueira pagos, três reservas e duas autorizações iniciais. A piscina fecha às 20h aos domingos (`dados/regulamento.md:149–157`).
- O Git já apresentava `.agents/.gitignore` não rastreado antes desta análise; preservá-lo. `.gitignore` já exclui `.env`, `.venv/` e `__pycache__/`.
- Nenhum requisito está implementado ou validado. A existência dos dados iniciais não comprova funcionamento da API. Não se verificou identidade dos dados com o remoto nem disponibilidade de chave Gemini/modelos na conta do avaliador.

## Requisitos e rastreabilidade

| ID | Obrigação | Desenho proposto | Verificação futura |
|---|---|---|---|
| R1 | Python >=3.12, uv e lock, ADK série 2 >=2.2.0 com versão exata; Gemini/AI Studio; sem segredo versionado | Projeto Python, `.env.example`, versão fixada, SQLite local | Clone limpo, `uv sync`, inspeção do lock e segredos; passos 1 e 15 |
| R2 | Principal e ao menos dois especialistas; tools leem/gravam reservas e visitantes | Especialistas de reservas e visitantes; consulta de regulamento isolada | Inspeção da topologia e eventos; passos 5–8, 11, 15 |
| R3 | Área paga e visitantes exigem confirmação fora da conversa; negativa não grava; reenvio e ID inválido retornam 409 | Confirmação ADK associada à sessão, validação no backend e guarda transacional do efeito | Passos 7–9 e 11; repetição após reinício e negativas |
| R4 | Apartamento imutável por sessão; nunca revelar/modificar dados de outro, inclusive nos eventos | Vinculação criada pelo backend; tools sem argumento de apartamento; consultas sempre filtradas e disponibilidade sem proprietário | Passos 3–5, 10 e 15; inspecionar eventos completos |
| R5 | Dados e histórico sobrevivem ao reinício; códigos nunca repetem inclusive cancelados | SQLite persistente; registro permanente de códigos e sessões ADK persistidas | Passo 13 e teste de cancelamento seguido de nova reserva |
| R6 | Consultar regulamento sem introduzir capítulos alheios nos eventos ou regulamento no prompt principal | Busca limitada a trechos relevantes, com tratamento isolado | Passo 12; examinar *todos* os eventos, inclusive argumentos e respostas das tools |
| R7 | Uma reserva ativa por área e data mesmo em concorrência | Restrição única no banco aplicada na gravação e conversão de conflito em resultado normal | Passo 14; duas aprovações concorrentes, duas respostas 200 e apenas uma reserva |
| R8 | Contrato exato das rotas; eventos completos e ordenados; 404 por sessão inexistente | Adaptador HTTP e serialização integral de eventos | Passos 1–14; comparação com contrato nas linhas 102–169 |
| R9 | Restauração de reservas/visitantes; documentação de arquitetura, garantias e execução; dados imutáveis | Comando explícito de restauração; README de entrega com referências reais | Clone limpo e comparação dos arquivos com base; passos 1 e 15 |

Fora de escopo: interface visual, autenticação real, pagamento/estorno, regras de horários e antecedência, testes automatizados obrigatórios e deploy. A restauração pode também apagar sessões, mas a escolha deve ser documentada. O comportamento de duas respostas simultâneas à mesma confirmação e de nova mensagem com confirmação pendente é livre dentro das garantias (`README.md:171`).

## Desenho proposto e limites

**Persistência.** SQLite em arquivos fora de `dados/`: um banco de negócio e, se necessário para evitar acoplamento/bloqueio, outro para o serviço de sessões ADK. Copiar os JSON iniciais para tabelas na inicialização controlada/restauração; nunca modificar os originais. Em reservas, manter linhas canceladas com estado ou um registro permanente de códigos, e criar índice único parcial para `(area, data)` apenas quando ativa. A inserção efetiva e a restrição são a autoridade, não a consulta prévia. Tratar conflito de unicidade como indisponibilidade, sem expor código ou apartamento do vencedor. Usar transações curtas, configuração e tratamento de contenção do SQLite; validar concorrência real com o serviço escolhido. Um identificador aleatório mais restrição única e retentativa evita repetição até após cancelamento.

**Identidade.** Na criação, backend associa identificador opaco de sessão a apartamento e persiste a associação. Tools obtêm a identidade de contexto confiável associado à sessão, sem parâmetro controlado pelo modelo; nenhuma tool altera a associação. Filtrar listagem e cancelamento na própria consulta por apartamento. Disponibilidade retorna apenas livre/ocupada, sem registros completos. Evitar também incluir dados de terceiros em exceções, mensagens internas e eventos. As rotas de verificação são administrativas por exigência do desafio e não são tools do agente.

**Confirmações.** Para áreas pagas e visitantes, a tool solicita confirmação ADK antes de qualquer efeito e o servidor expõe ID, ação e detalhes extraídos de evento confiável, vinculando-os à sessão. A rota rejeita IDs inexistentes, de outra sessão ou respondidos com 409. Ao aprovar/recusar, envia ao Runner a resposta estruturada ADK associada ao ID; nunca interpreta texto como confirmação. Persistir estado suficiente para retomar após reinício, e fazer o efeito aprovado ser idempotente por ID em transação com a gravação, protegendo reenvio e falhas entre efeito e resposta. Definir e provar tratamento de interrupção entre consumir confirmação e executar: não marcar concluída antes de um efeito recuperável; resultado e rejeição também precisam de registro coerente. Como o README alerta para combinações de topologia/Runner/sessão que falham silenciosamente, esta é hipótese técnica a demonstrar, não solução já comprovada. Mensagens enquanto pendente podem ser recusadas de forma explícita.

**Regulamento.** Proposta: indexar em memória artigos/parágrafos a partir de `dados/regulamento.md`, buscar trechos relevantes por termos e devolver somente evidência pertinente, com fallback explícito quando não houver confiança. A recuperação deve contemplar sinônimos, perguntas compostas e referências cruzadas; busca lexical simples pode falhar. Não retornar capítulo inteiro nem documento completo em tool response: eventos registram chamadas e resultados. Validar ausência de texto de assuntos alheios tanto na resposta como em cada evento; se a precisão da busca não for suficiente, rever desenho antes de avançar. O principal recebe apenas instruções de roteamento.

**API.** Rotas `POST /sessoes`, `POST /sessoes/{id}/mensagens`, `POST /sessoes/{id}/confirmacoes`, `GET /sessoes/{id}/eventos`, `GET /apartamentos/{numero}/reservas` e `GET /apartamentos/{numero}/visitantes`. Preservar nomes, listas, códigos e formatos do contrato. Eventos devem ser todos os eventos persistidos em ordem, serializados integralmente; não somente texto final. Cada resposta de conversa lista todas as confirmações ainda pendentes daquela sessão. Validar primeiro existência da sessão para garantir 404.

## Pesquisa e hipóteses a verificar

Consulta Context7 em 2026-10-29 à documentação oficial `/google/adk-docs`, sem garantia de correspondência exata com a versão a fixar:

- [Confirmação de tools](https://github.com/google/adk-docs/blob/main/docs/tools-custom/confirmation.md): documentação descreve `request_confirmation` e resposta `FunctionResponse` denominada `adk_request_confirmation` com o ID da chamada; ao usar Resume, a mesma invocação pode ser necessária. Verificar código da versão exata e resultado real, especialmente subagentes e reinício.
- [Sessões persistentes](https://github.com/google/adk-docs/blob/main/docs/sessions/session/index.md): descreve `DatabaseSessionService` e SQLite com driver assíncrono `sqlite+aiosqlite`; confirmar extras e compatibilidade na versão escolhida.
- [Contexto e estado](https://github.com/google/adk-docs/blob/main/docs/context/index.md): tools acessam estado via `ToolContext`; garantir por código que a vinculação não seja alterável pelo modelo, não presumir que state por si só é imutável.
- [Retomada](https://github.com/google/adk-docs/blob/main/docs/runtime/resume.md): documenta retomada de invocações com Runner. Decidir configuração somente após experimento com sessão persistente.

Versão exata ADK e modelo Gemini são decisões pendentes da implementação: consultar disponibilidade atual e compatibilidade, fixar uma versão >=2.2.0 e <3, registrar modelo configurável e limites efetivos da conta. Não presumir que os exemplos atuais da documentação correspondam à versão fixada. O README alerta que confirmação com persistência e subagentes pode falhar mesmo sem erro; provar cedo com aprovação antes/depois de reinício, recusa, replay e inspeção de eventos.

## Pacotes de trabalho sequenciais

Os caminhos abaixo são propostas, não arquivos existentes. Responsável pela integração deve ajustar a estrutura sem criar autores concorrentes para arquivos compartilhados.

1. **Fundação e prova ADK** — `pyproject.toml`, `uv.lock`, `.env.example`, protótipo isolado em diretório temporário. Escolher versões e modelo; demonstrar principal + especialistas, confirmação com Runner e sessão SQLite persistente, incluindo reinício antes da aprovação. Pré-requisito: ambiente e chave. Aceite: efeito ocorre uma vez, negativa não grava e eventos ficam acessíveis; registrar topologia que funciona. Não iniciar a integração definitiva com hipótese não comprovada.
2. **Armazenamento** — módulo próprio de banco, esquema e comando de restauração. Importar dados sem alterá-los; estado de reservas, códigos históricos, vínculo de sessão e identificadores de confirmação. Aceite: dados iniciais corretos, reinício preserva dados, cancelamento preserva código e concorrência garante exclusividade. Restaurar com API parada; documentar se também apaga sessões.
3. **Tools de negócio** — módulos exclusivos de reservas e visitantes sobre o armazenamento. Implementar escopo da sessão, leitura, cancelamento, reserva gratuita e reserva/visita condicionadas a confirmação. Aceite: nenhum argumento de apartamento controlado pelo modelo; indisponibilidade não revela dono; aprovação, recusa e replay verificados.
4. **Agentes e regulamento** — módulos de agentes e recuperação, após contrato das tools. Principal com dois especialistas, roteamento e busca pertinente. Aceite: resposta da piscina correta e eventos sem capítulos alheios; tools chamadas visíveis. Revisar vazamentos também nos argumentos e falhas.
5. **API e integração** — módulo web e adaptador do Runner, após definição dos contratos. Implementar seis rotas, serialização de eventos e estados 201/200/404/409; coletar pendências por sessão. Aceite: exemplos HTTP do enunciado, confirmação real com persistência e reinício; tratar conflito como 200 normal.
6. **Validação e entrega** — executar fluxo completo de 15 passos, inclusive paralelismo, reinício e inspeção de eventos; repetir teste de confirmação pendente após reinício. Verificar lock, segredos e identidade dos dados com base original. Substituir README pelo solicitado somente ao final, com seções Arquitetura, Garantias e Como rodar, caminhos reais e comandos executados. Registrar resultados e limitações reais. Fork público e envio para `main` são ações externas ainda não autorizadas nesta etapa.

## Retomada

Começar pelo pacote 1 e registrar o resultado da prova antes de estruturar a implementação. O ambiente de execução ainda não foi preparado, comandos de aplicação ainda não existem e nenhum teste de integração ou chamada a modelo foi executado. Este plano é uma proposta revisável; não representa aceite do desafio.


## Andamento de implementação (2026-10-29)

Implementados `aurora/storage.py`, `aurora/agents.py`, `aurora/api.py`, dependências e README de execução. ADK 2.9.1 e Python 3.12 foram instalados com uv; SQLite assíncrono exigiu o extra `sqlalchemy[asyncio]`. A prova com modelo simulado confirmou a retomada de uma reserva paga após reiniciar o serviço e o reenvio com 409; os testes também cobrem autorização e recusa de visitante, ID de outra sessão, código cancelado, concorrência no armazenamento e consulta da piscina. O servidor iniciou em localhost e retornou a reserva inicial do 101. `uv sync --locked` e seis testes locais passaram; `dados/` não foi alterado em relação ao HEAD local.

Ainda necessário: configurar chave e executar o fluxo completo do avaliador com Gemini real, incluindo concorrência nas rotas e checagem integral dos eventos; revisar a relevância da busca do regulamento e comportamento da retomada em erros. Não há comprovação de conformidade integral ou acesso ao modelo nesta conta. A documentação atual informa acesso restrito aos modelos 2.5 para projetos novos, de modo que o padrão configurável foi alterado para `gemini-3.5-flash-lite`; verificar compatibilidade e cota reais.


## Validação com Gemini real (2026-10-30)

Usado `gemini-3.5-flash-lite`, com bases temporárias isoladas. Uma primeira execução encontrou área `salao_festas` rejeitada; a normalização foi corrigida e o fluxo repetido. Foram observados sucesso em dados iniciais, isolamento em consulta e cancelamento, reserva gratuita, confirmação e recusa de reserva paga, aprovação e reenvio 409, disponibilidade sem revelar proprietário, autorização de visitante, resposta de piscina às 20h, checagem de trechos e dados sensíveis nos eventos, histórico e continuação após reinício, e duas aprovações concorrentes com apenas uma reserva. Em execução separada, aprovação após reinício da API gravou uma reserva e o reenvio retornou 409. Os eventos da primeira tentativa foram examinados para diagnosticar a normalização.

A identificação dos efeitos passou a combinar sessão, invocação e chamada para evitar colisões de IDs fornecidos pelo modelo entre sessões ou invocações. As verificações automatizadas locais continuam usando modelo simulado; as chamadas reais dependem de acesso e cotas do Google e não cobrem todas as formulações possíveis. A busca de regulamento continua lexical e limitada a um artigo; é um risco para perguntas com sinônimos ou que exijam múltiplos artigos. Os testes reais foram rodados com dados temporários, sem publicar ou criar fork.


## Revisão e clone limpo

A revisão independente detectou que a busca ignorava os artigos 1º a 9º; o padrão foi corrigido e o artigo 2º ganhou teste específico. Em clone local limpo do commit de entrega, com Python 3.12, `uv sync --locked`, os oito testes e o comando de restauração passaram. Em seguida, `uv run python scripts/validacao_real.py` completou os cenários registrados no roteiro com o Gemini real: isolamento, cancelamentos, confirmações, 404/409, consulta da piscina, eventos, reinício, persistência, códigos e aprovações simultâneas. Os bancos foram temporários. A confirmação aprovada após reinício foi verificada separadamente na execução anterior; o roteiro do clone cobre a retomada da conversa após reinício. O mecanismo de confirmação do ADK é experimental e respostas do modelo podem variar.
