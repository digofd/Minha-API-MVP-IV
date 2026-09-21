# Testes da casca de IO da AISWEB.

import httpx

from app.clients.aisweb_client import (
    AiswebClient, CartaResumo, DadosCartas, FalhaHttp, FalhaRede,
)

XML_CARTAS = """<?xml version="1.0" encoding="UTF-8"?>
<aisweb>
  <cartas total="2">
    <item id="a1">
      <tipo>VAC</tipo>
      <amdt>2604A1</amdt>
      <dtPublic>2026-04-16</dtPublic>
      <link><![CDATA[https://aisweb.decea.gov.br/download/?arquivo=a1&apikey=XYZ]]></link>
    </item>
    <item id="a2">
      <tipo>ADC</tipo>
      <amdt>2608A1</amdt>
      <dtPublic>2026-08-06</dtPublic>
    </item>
  </cartas>
</aisweb>"""


def _cliente_respondendo(resposta: httpx.Response) -> AiswebClient:
    cliente = AiswebClient("https://api.exemplo", "CHAVE", "SENHA")
    cliente.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: resposta))
    return cliente


class TestGetCartas:
    async def test_resposta_ok_vira_lista_de_cartas(self):
        cliente = _cliente_respondendo(httpx.Response(200, text=XML_CARTAS))
        resultado = await cliente.get_cartas("SBSP")
        assert resultado == DadosCartas((
            CartaResumo(tipo="VAC", amdt="2604A1", dt_public="2026-04-16",
                       link="https://aisweb.decea.gov.br/download/?arquivo=a1&apikey=XYZ"),
            CartaResumo(tipo="ADC", amdt="2608A1", dt_public="2026-08-06"),
        ))
        await cliente.close()

    async def test_item_sem_amdt_e_ignorado(self):
        xml = """<aisweb><cartas><item><tipo>SID</tipo></item></cartas></aisweb>"""
        cliente = _cliente_respondendo(httpx.Response(200, text=xml))
        resultado = await cliente.get_cartas("SBSP")
        assert resultado == DadosCartas(())
        await cliente.close()

    async def test_erro_de_status_vira_falha_http(self):
        cliente = _cliente_respondendo(httpx.Response(401, text="sem chave"))
        resultado = await cliente.get_cartas("SBSP")
        assert isinstance(resultado, FalhaHttp)
        await cliente.close()

    async def test_falha_de_rede_vira_falha_rede(self):
        cliente = AiswebClient("https://api.exemplo", "CHAVE", "SENHA")

        async def _handler(_request):
            raise httpx.ConnectError("recusado")

        cliente.client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        resultado = await cliente.get_cartas("SBSP")
        assert isinstance(resultado, FalhaRede)
        await cliente.close()


class TestGetCartaPdf:
    async def test_resposta_ok_devolve_os_bytes(self):
        cliente = _cliente_respondendo(httpx.Response(200, content=b"%PDF-1.4 conteudo"))
        resultado = await cliente.get_carta_pdf("https://aisweb.decea.gov.br/download/?a=1")
        assert resultado == b"%PDF-1.4 conteudo"
        await cliente.close()

    async def test_erro_de_status_vira_falha_http(self):
        cliente = _cliente_respondendo(httpx.Response(404, text="não encontrado"))
        resultado = await cliente.get_carta_pdf("https://aisweb.decea.gov.br/download/?a=1")
        assert isinstance(resultado, FalhaHttp)
        assert resultado.status == 404
        await cliente.close()
