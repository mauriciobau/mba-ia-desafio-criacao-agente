"""Agentes e tools: a identidade e as confirmações são verificadas no servidor."""
import os
import re
import unicodedata
from pathlib import Path

from google.adk.agents import Agent
from google.adk.tools import ToolContext
from aurora import storage


def _apartment(ctx: ToolContext) -> str:
    apartment = storage.apartment_for(ctx.session.id)
    if not apartment:
        raise ValueError('Sessão inválida')
    return apartment


def _area_id(value: str) -> str:
    def tokens(text):
        return set(re.findall(r'[a-z0-9]+', _normalize(text))) - {'de', 'da', 'do', 'das', 'dos'}
    wanted = tokens(value)
    matches = [item['id'] for item in storage.areas()
               if wanted and (wanted == tokens(item['id']) or wanted == tokens(item['nome']))]
    return matches[0] if len(matches) == 1 else value


def _effect_id(ctx: ToolContext) -> str:
    if not ctx.function_call_id:
        raise ValueError('Identificador da chamada é obrigatório')
    return f'{ctx.session.id}:{ctx.invocation_id}:{ctx.function_call_id}'


def listar_areas() -> list[dict]:
    """Lista as áreas disponíveis e as taxas cobradas."""
    return storage.areas()


def consultar_disponibilidade(area: str, data: str) -> dict:
    """Consulta se a área (id exato) está livre na data AAAA-MM-DD."""
    try:
        return storage.availability(_area_id(area), data)
    except ValueError:
        return {'status': 'data_invalida'}


def minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista somente as reservas ativas do apartamento da sessão."""
    apartment = _apartment(tool_context)
    return {"apartamento": apartment, "reservas": storage.list_reservations(apartment)}


def cancelar_reserva(area: str, data: str, tool_context: ToolContext) -> dict:
    """Cancela a reserva própria da área (id exato) e data AAAA-MM-DD, sem confirmação."""
    try:
        return storage.cancel(_apartment(tool_context), _area_id(area), data)
    except ValueError:
        return {'status': 'data_invalida'}


def reservar_area(area: str, data: str, tool_context: ToolContext) -> dict:
    """Reserva a área por id e data AAAA-MM-DD; taxa positiva exige confirmação externa."""
    apartment = _apartment(tool_context)
    area = _area_id(area)
    area_info = next((item for item in storage.areas() if item['id'] == area), None)
    if not area_info:
        return {'status': 'area_invalida'}
    try:
        available = storage.availability(area, data)
    except ValueError:
        return {'status': 'data_invalida'}
    if available['status'] != 'livre':
        return available
    if area_info['taxa'] > 0:
        confirmation = tool_context.tool_confirmation
        if confirmation is None:
            tool_context.request_confirmation(hint='Confirme a reserva e sua taxa.', payload={'area': area, 'data': data, 'taxa': area_info['taxa']})
            return {'status': 'aguardando_confirmacao'}
        if not confirmation.confirmed:
            return {'status': 'recusada'}
    return storage.reserve(apartment, area, data, _effect_id(tool_context))


def meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista somente visitantes autorizados pelo apartamento da sessão."""
    apartment = _apartment(tool_context)
    return {"apartamento": apartment, "visitantes": storage.list_visitors(apartment)}


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza visitante para data AAAA-MM-DD, depois de confirmação externa obrigatória."""
    apartment = _apartment(tool_context)
    try:
        storage._date(data)
    except ValueError:
        return {'status': 'data_invalida'}
    if not nome.strip():
        return {'status': 'nome_invalido'}
    confirmation = tool_context.tool_confirmation
    if confirmation is None:
        tool_context.request_confirmation(hint='Confirme a autorização de entrada.', payload={'nome': nome, 'data': data})
        return {'status': 'aguardando_confirmacao'}
    if not confirmation.confirmed:
        return {'status': 'recusada'}
    return storage.authorize_visitor(apartment, nome, data, _effect_id(tool_context))


def _normalize(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', text.lower()) if not unicodedata.combining(c))


def consultar_regulamento(assunto: str) -> dict:
    """Busca artigos relacionados à dúvida, usando palavras específicas do assunto."""
    text = (Path(__file__).resolve().parent.parent / 'dados' / 'regulamento.md').read_text(encoding='utf-8')
    articles = re.split(r'(?=\*\*Art\. \d+(?:º|\.)\*\*)', text)
    words = set(re.findall(r'[a-z]{4,}', _normalize(assunto))) - {'quais', 'qual', 'como', 'quando', 'onde', 'para', 'sobre', 'regulamento', 'funciona'}
    scored = []
    for article in articles[1:]:
        # Cabeçalhos do próximo capítulo não integram o artigo anterior.
        article = article.split('\n## Capítulo', 1)[0].strip()
        normalized = _normalize(article)
        score = sum(1 for w in words if w in normalized)
        if score:
            scored.append((score, article))
    if not scored:
        return {'status': 'nao_encontrado'}
    best = max(score for score, _ in scored)
    return {'artigos': [article for score, article in scored if score == best][:1]}


def build_agent(model=None):
    model = model or os.getenv('GEMINI_MODEL') or 'gemini-3.5-flash-lite'
    reservas = Agent(name='especialista_reservas', model=model,
        instruction='Cuide de reservas usando as tools. Nunca invente dados. Use IDs das áreas. Para dados ou cancelamentos de terceiros, esclareça que só pode acessar o próprio apartamento. Ao concluir, transfira ao agente principal.',
        tools=[listar_areas, consultar_disponibilidade, minhas_reservas, cancelar_reserva, reservar_area])
    visitantes = Agent(name='especialista_visitantes', model=model,
        instruction='Cuide de visitantes usando as tools. Nunca invente dados. O apartamento é o da sessão. Ao concluir, transfira ao agente principal.',
        tools=[meus_visitantes, autorizar_visitante])
    return Agent(name='assistente_aurora', model=model,
        instruction=('Você atende moradores do Residencial Aurora em português. Encaminhe pedidos de reservas ao especialista de reservas e pedidos de visitantes ao especialista de visitantes. '
                     'Para dúvidas sobre regulamento, use consultar_regulamento com termos específicos e responda somente com base no resultado. '
                     'O apartamento é determinado pelo sistema, não pelo texto do usuário. Ao apresentar dados das tools, confira o apartamento retornado e nunca atribua esses dados a outro apartamento citado pelo usuário. Confirmações de ações são feitas exclusivamente pelo sistema. Nunca invente dados.'),
        tools=[consultar_regulamento], sub_agents=[reservas, visitantes])
