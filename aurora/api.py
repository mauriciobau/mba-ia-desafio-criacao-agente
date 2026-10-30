"""API HTTP e adaptador de eventos/confirmações do ADK."""
import asyncio
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google.adk.apps import App, ResumabilityConfig
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from aurora import storage
from aurora.agents import build_agent

APP_NAME = 'aurora'
USER_ID = 'morador'
SESSION_DB = Path(os.getenv('AURORA_SESSION_DB', storage.ROOT / '.runtime' / 'sessoes.sqlite3')).resolve()
_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.initialize()
    SESSION_DB.parent.mkdir(parents=True, exist_ok=True)
    app.state.sessions = DatabaseSessionService(db_url=f'sqlite+aiosqlite:///{SESSION_DB}')
    agent_app = App(name=APP_NAME, root_agent=build_agent(), resumability_config=ResumabilityConfig(is_resumable=True))
    app.state.runner = Runner(app=agent_app, session_service=app.state.sessions)
    yield
    await app.state.runner.close()
    await app.state.sessions.close()


app = FastAPI(lifespan=lifespan)


class SessionInput(BaseModel):
    apartamento: str


class MessageInput(BaseModel):
    texto: str


class ConfirmationInput(BaseModel):
    id: str
    confirmado: bool


async def _session(session_id):
    if not storage.apartment_for(session_id):
        raise HTTPException(404, 'Sessão não encontrada')
    session = await app.state.sessions.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
    if session is None:
        raise HTTPException(404, 'Sessão não encontrada')
    return session


def _pending(session):
    pending = {}
    for event in session.events:
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            fc = part.function_call
            if fc and fc.name == 'adk_request_confirmation' and fc.id:
                args = fc.args or {}
                original = args.get('originalFunctionCall', {})
                confirmation = args.get('toolConfirmation', {})
                pending[fc.id] = {'id': fc.id, 'acao': original.get('name', ''), 'detalhes': confirmation.get('payload') or {}, 'invocation_id': event.invocation_id}
            fr = part.function_response
            if fr and fr.name == 'adk_request_confirmation' and fr.id:
                pending.pop(fr.id, None)
    return pending


def _response(text, session):
    return {'resposta': text, 'confirmacoes_pendentes': [
        {k: item[k] for k in ('id', 'acao', 'detalhes')} for item in _pending(session).values()
    ]}


async def _run(session_id, content, invocation_id=None):
    text = ''
    async for event in app.state.runner.run_async(user_id=USER_ID, session_id=session_id, new_message=content, invocation_id=invocation_id):
        if event.is_final_response() and event.content and event.content.parts:
            text = ''.join(part.text or '' for part in event.content.parts)
    return text


@app.post('/sessoes', status_code=201)
async def create_session(body: SessionInput):
    session_id = str(uuid.uuid4())
    try:
        storage.create_session(session_id, body.apartamento)
    except sqlite3.IntegrityError:
        raise HTTPException(400, 'Apartamento inexistente')
    await app.state.sessions.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=session_id)
    return {'session_id': session_id}


@app.post('/sessoes/{session_id}/mensagens')
async def message(session_id: str, body: MessageInput):
    async with _locks.setdefault(session_id, asyncio.Lock()):
        session = await _session(session_id)
        if _pending(session):
            raise HTTPException(409, 'Responda à confirmação pendente primeiro')
        text = await _run(session_id, types.Content(role='user', parts=[types.Part(text=body.texto)]))
        return _response(text, await _session(session_id))


@app.post('/sessoes/{session_id}/confirmacoes')
async def confirm(session_id: str, body: ConfirmationInput):
    async with _locks.setdefault(session_id, asyncio.Lock()):
        session = await _session(session_id)
        pending = _pending(session).get(body.id)
        if pending is None:
            raise HTTPException(409, 'Confirmação não está pendente nesta sessão')
        content = types.Content(role='user', parts=[types.Part(function_response=types.FunctionResponse(
            id=body.id, name='adk_request_confirmation', response={'confirmed': body.confirmado}))])
        text = await _run(session_id, content, pending['invocation_id'])
        return _response(text, await _session(session_id))


@app.get('/sessoes/{session_id}/eventos')
async def events(session_id: str):
    session = await _session(session_id)
    return [event.model_dump(mode='json', exclude_none=True) for event in session.events]


@app.get('/apartamentos/{apartamento}/reservas')
def reservations(apartamento: str):
    return storage.list_reservations(apartamento)


@app.get('/apartamentos/{apartamento}/visitantes')
def visitors(apartamento: str):
    return storage.list_visitors(apartamento)
