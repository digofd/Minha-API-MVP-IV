# Testes da casca de IO da REDEMET.

import httpx

from app.clients.redemet_client import (
    Dados, FalhaHttp, FalhaRede, RedemetClient, descrever, mensagens_de, redigir,
)

URL_COM_CHAVE = "https://api.exemplo/mensagens/metar/SBSP?api_key=SEGREDO123&x=1"


class TestRedacaoDaChave:

    def test_chave_em_url_e_substituida(self):
        assert "SEGREDO123" not in redigir(URL_COM_CHAVE)
        assert "api_key=***" in redigir(URL_COM_CHAVE)

    def test_preserva_o_resto_da_mensagem(self):
        assert "metar/SBSP" in redigir(URL_COM_CHAVE)

    def test_texto_sem_chave_fica_intacto(self):
        assert redigir("timeout ao conectar") == "timeout ao conectar"


class TestDescrever:
    def test_dados_informam_a_quantidade(self):
        assert descrever(Dados([{"mens": "x"}])) == "1 mensagem(ns)"

    def test_lista_vazia_nao_e_falha(self):
        assert descrever(Dados([])) == "0 mensagem(ns)"

    def test_falha_http_informa_o_status(self):
        assert "HTTP 401" in descrever(FalhaHttp(401, "chave inválida"))

    def test_falha_de_rede_informa_o_motivo(self):
        assert "falha de rede" in descrever(FalhaRede("timeout"))


class TestMensagensDe:
    def test_extrai_de_dados(self):
        assert mensagens_de(Dados([{"mens": "a"}])) == [{"mens": "a"}]

    def test_falha_nao_produz_mensagens(self):
        assert mensagens_de(FalhaHttp(500, "boom")) == []
        assert mensagens_de(FalhaRede("dns")) == []


class TestTraducaoDaResposta:

    def _cliente_respondendo(self, resposta: httpx.Response) -> RedemetClient:
        cliente = RedemetClient("https://api.exemplo", "CHAVE")
        cliente.client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: resposta))
        return cliente

    async def test_resposta_ok_vira_dados(self):
        corpo = {"data": {"data": [{"mens": "METAR SBSP"}]}}
        cliente = self._cliente_respondendo(httpx.Response(200, json=corpo))
        resultado = await cliente.get_taf("SBSP")
        assert resultado == Dados([{"mens": "METAR SBSP"}])
        await cliente.close()

    async def test_erro_de_status_vira_falha_http(self):
        cliente = self._cliente_respondendo(httpx.Response(401, text="sem chave"))
        resultado = await cliente.get_taf("SBSP")
        assert isinstance(resultado, FalhaHttp)
        assert resultado.status == 401
        await cliente.close()

    async def test_corpo_que_nao_e_json_vira_falha(self):
        cliente = self._cliente_respondendo(httpx.Response(200, text="<html>"))
        resultado = await cliente.get_taf("SBSP")
        assert isinstance(resultado, FalhaHttp)
        await cliente.close()

    async def test_sem_mensagens_e_sucesso_com_lista_vazia(self):
         #Aeródromo sem METAR não é falha 
        cliente = self._cliente_respondendo(
            httpx.Response(200, json={"data": {"data": []}}))
        assert await cliente.get_taf("SBSP") == Dados([])
        await cliente.close()
