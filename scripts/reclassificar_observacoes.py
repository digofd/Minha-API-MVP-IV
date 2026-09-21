#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  

from app.core.observacoes import decidir_metar, decidir_taf  
from app.core.observacoes import ObservacaoDecidida  
from app.database import AsyncSessionLocal  
from app.models.observation import Observation  

from app.models.route import Route 


@dataclass(frozen=True)
class Mudanca:
    # O que mudaria numa linha, para poder mostrar antes de gravar.
    id: int
    icao: str
    tipo: str
    status_antes: str | None
    status_depois: str
    visibilidade_antes: int | None
    visibilidade_depois: int | None
    aviso_antes: str | None
    aviso_depois: str | None


def recalcular(observacao: Observation) -> ObservacaoDecidida | None:
    # "Refaz parsing e classificação a partir da mensagem bruta gravada.
    envelope = {"mens": observacao.mensagem_bruta,
                "recebimento": observacao.recebimento.isoformat()}
    argumentos = dict(icao=observacao.icao, route_id=observacao.route_id,
                      bruto=envelope, agora=observacao.recebimento)
    decisao = (decidir_metar(**argumentos) if observacao.tipo == "METAR"
               else decidir_taf(**argumentos))
    return decisao if isinstance(decisao, ObservacaoDecidida) else None


def diferenca(observacao: Observation, nova: ObservacaoDecidida) -> Mudanca | None:
    # Descreve a mudança, ou None se a linha já está correta.
    igual = (observacao.status_operacional == nova.status_operacional
             and observacao.visibilidade_m == nova.visibilidade_m
             and observacao.teto_ft == nova.teto_ft
             and observacao.aviso_temporario == nova.aviso_temporario)
    if igual:
        return None
    return Mudanca(observacao.id, observacao.icao, observacao.tipo,
                   observacao.status_operacional, nova.status_operacional,
                   observacao.visibilidade_m, nova.visibilidade_m,
                   observacao.aviso_temporario, nova.aviso_temporario)


def aplicar(observacao: Observation, nova: ObservacaoDecidida) -> None:
    # Copia os valores recalculados para a linha.
    observacao.status_operacional = nova.status_operacional
    observacao.base_legal = nova.base_legal
    observacao.teto_ft = nova.teto_ft
    observacao.visibilidade_m = nova.visibilidade_m
    observacao.aviso_temporario = nova.aviso_temporario


def resumir(mudancas: list[Mudanca]) -> str:
    # Relatório do que mudaria, agrupado por transição de status.
    if not mudancas:
        return "Nenhuma linha precisa de correção."
    transicoes: dict[str, int] = {}
    for m in mudancas:
        chave = f"{m.status_antes or 'nulo'} -> {m.status_depois}"
        transicoes[chave] = transicoes.get(chave, 0) + 1
    linhas = [f"{len(mudancas)} linha(s) a corrigir:", ""]
    linhas += [f"  {contagem:>4}x  {chave}" for chave, contagem in
               sorted(transicoes.items(), key=lambda par: -par[1])]
    linhas.append("")
    linhas.append("Exemplos:")
    for m in mudancas[:5]:
        linhas.append(f"  #{m.id} {m.icao} {m.tipo}: "
                      f"visibilidade {m.visibilidade_antes} -> {m.visibilidade_depois}, "
                      f"status {m.status_antes!r} -> {m.status_depois!r}")
    return "\n".join(linhas)


async def executar(gravar: bool) -> int:
    # Percorre todas as observações e recalcula cada uma.
    async with AsyncSessionLocal() as sessao:
        observacoes = list((await sessao.execute(select(Observation))).scalars().all())
        mudancas: list[Mudanca] = []
        for observacao in observacoes:
            nova = recalcular(observacao)
            if nova is None:
                continue
            mudanca = diferenca(observacao, nova)
            if mudanca is None:
                continue
            mudancas.append(mudanca)
            if gravar:
                aplicar(observacao, nova)
        if gravar:
            await sessao.commit()
        print(f"{len(observacoes)} observação(ões) analisadas.")
        print(resumir(mudancas))
        print("\nGRAVADO." if gravar else "\nSIMULAÇÃO — nada foi gravado. Use --aplicar.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aplicar", action="store_true",
                        help="grava as correções (sem esta opção, só simula)")
    return asyncio.run(executar(parser.parse_args().aplicar))


if __name__ == "__main__":
    sys.exit(main())
