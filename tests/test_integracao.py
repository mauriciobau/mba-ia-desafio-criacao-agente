"""Prova local do fluxo ADK; o modelo simulado não valida compreensão do Gemini."""
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

runtime = tempfile.TemporaryDirectory(prefix='aurora-tests-')
os.environ['AURORA_DB'] = runtime.name + '/condominio.sqlite3'
os.environ['AURORA_SESSION_DB'] = runtime.name + '/sessoes.sqlite3'

from fastapi.testclient import TestClient
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr

from aurora import api, storage
from aurora.agents import build_agent, consultar_regulamento, _area_id


class ModeloSimulado(BaseLlm):
    _etapa: int = PrivateAttr(default=0)
    _visitante: bool = PrivateAttr(default=False)

    async def generate_content_async(self, llm_request, stream=False):
        self._etapa += 1
        if self._etapa == 1:
            agent = 'especialista_visitantes' if self._visitante else 'especialista_reservas'
            part = types.Part(function_call=types.FunctionCall(name='transfer_to_agent', args={'agent_name': agent}))
        elif self._etapa == 2:
            name = 'autorizar_visitante' if self._visitante else 'reservar_area'
            args = {'nome': 'Joana Ribeiro', 'data': '2030-04-21'} if self._visitante else {'area': 'salao-de-festas', 'data': '2030-04-20'}
            part = types.Part(function_call=types.FunctionCall(name=name, args=args))
        else:
            part = types.Part(text='Concluído')
        yield LlmResponse(content=types.Content(role='model', parts=[part]))


class Integracao(unittest.TestCase):
    def setUp(self):
        storage.restore()
        self.model = ModeloSimulado(model='fake')
        api.build_agent = lambda: build_agent(self.model)

    def _pending(self, client):
        sid = client.post('/sessoes', json={'apartamento': '101'}).json()['session_id']
        response = client.post(f'/sessoes/{sid}/mensagens', json={'texto': 'solicitação'})
        self.assertEqual(response.status_code, 200)
        return sid, response.json()['confirmacoes_pendentes'][0]['id']

    def test_confirmacao_apos_reinicio_e_reenvio(self):
        with TestClient(api.app) as client:
            sid, confirmation = self._pending(client)
            self.assertFalse(any(r['data'] == '2030-04-20' for r in client.get('/apartamentos/101/reservas').json()))
        with TestClient(api.app) as client:
            response = client.post(f'/sessoes/{sid}/confirmacoes', json={'id': confirmation, 'confirmado': True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['confirmacoes_pendentes'], [])
            self.assertEqual(client.post(f'/sessoes/{sid}/confirmacoes', json={'id': confirmation, 'confirmado': True}).status_code, 409)
            self.assertEqual(sum(r['data'] == '2030-04-20' for r in client.get('/apartamentos/101/reservas').json()), 1)
            self.assertTrue(client.get(f'/sessoes/{sid}/eventos').json())

    def test_visitante_negado(self):
        self.model._visitante = True
        with TestClient(api.app) as client:
            sid, confirmation = self._pending(client)
            self.assertEqual(client.get('/apartamentos/101/visitantes').json(), [])
            response = client.post(f'/sessoes/{sid}/confirmacoes', json={'id': confirmation, 'confirmado': False})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get('/apartamentos/101/visitantes').json(), [])

    def test_visitante_aprovado_e_id_de_outra_sessao(self):
        self.model._visitante = True
        with TestClient(api.app) as client:
            sid, confirmation = self._pending(client)
            other = client.post('/sessoes', json={'apartamento': '201'}).json()['session_id']
            self.assertEqual(client.post(f'/sessoes/{other}/confirmacoes', json={'id': confirmation, 'confirmado': True}).status_code, 409)
            response = client.post(f'/sessoes/{sid}/confirmacoes', json={'id': confirmation, 'confirmado': True})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(client.get('/apartamentos/101/visitantes').json(), [{'nome': 'Joana Ribeiro', 'data': '2030-04-21'}])
            self.assertEqual(client.post(f'/sessoes/{sid}/confirmacoes', json={'id': confirmation, 'confirmado': True}).status_code, 409)

    def test_codigo_cancelado_nao_reaparece(self):
        self.assertEqual(storage.cancel('101', 'quadra', '2030-03-09')['status'], 'cancelada')
        result = storage.reserve('101', 'quadra', '2030-04-06')
        self.assertEqual(result['status'], 'reservada')
        self.assertNotIn(result['codigo'], {'RSV-1377', 'RSV-4821', 'RSV-2950'})

    def test_concorrencia_e_isolamento(self):
        self.assertEqual(storage.cancel('101', 'salao-de-festas', '2030-03-16')['status'], 'nao_encontrada')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda apartment: storage.reserve(apartment, 'salao-de-festas', '2030-05-11', apartment), ('101', '201')))
        self.assertEqual(sorted(r['status'] for r in results), ['ocupada', 'reservada'])
        self.assertEqual(storage.list_reservations('302')[0]['codigo'], 'RSV-4821')

    def test_nome_area_normalizado(self):
        self.assertEqual(_area_id('salao_festas'), 'salao-de-festas')
        self.assertEqual(_area_id('Salão de festas'), 'salao-de-festas')
        self.assertEqual(_area_id('churrasqueira'), 'churrasqueira')

    def test_artigos_iniciais_regulamento(self):
        self.assertIn('Art. 2º', str(consultar_regulamento('atividades religiosas político-partidárias')))

    def test_regulamento(self):
        result = consultar_regulamento('horário piscina domingos')
        self.assertIn('20h', str(result))
        self.assertNotIn('coleira refletiva', str(result))


if __name__ == '__main__':
    unittest.main()
