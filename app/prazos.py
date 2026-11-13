"""Cálculo de prazos processuais.

Esta parte é código determinístico e testável: o Gemini NUNCA calcula prazo.
Ele só extrai da intimação o número de dias e o tipo de contagem; a data final
sai daqui.

Regras implementadas (CPC/2015 e Lei 11.419/2006):
- Disponibilização no DJe/DJEN -> publicação no 1º dia útil seguinte
  (Lei 11.419, art. 4º, §3º).
- A contagem começa no 1º dia útil seguinte à publicação (CPC, art. 224, §3º);
  exclui-se o dia do começo (art. 224, caput).
- Dias úteis (CPC, art. 219), ou corridos quando informado (ex.: processo penal).
- Recesso forense de 20/12 a 20/01: prazos suspensos (CPC, art. 220).
- Se o prazo vencer em dia não útil, prorroga para o próximo dia útil
  (CPC, art. 224, §1º) — vale também para contagem em dias corridos.
- Prazo em dobro (Fazenda, MP, Defensoria, litisconsortes com procuradores
  diferentes em autos físicos) NÃO é presumido: o advogado marca.

ATENÇÃO: o calendário de feriados é uma base inicial. Feriados locais,
pontos facultativos e suspensões por portaria (ex.: indisponibilidade do
sistema) precisam ser cadastrados em dados/feriados_tribunais.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

ARQUIVO_FERIADOS = Path(__file__).resolve().parent.parent / "dados" / "feriados_tribunais.json"


def pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


def feriados_nacionais(ano: int) -> dict[date, str]:
    p = pascoa(ano)
    return {
        date(ano, 1, 1): "Confraternização Universal",
        p - timedelta(days=48): "Carnaval (segunda)",
        p - timedelta(days=47): "Carnaval (terça)",
        p - timedelta(days=2): "Sexta-feira Santa",
        date(ano, 4, 21): "Tiradentes",
        date(ano, 5, 1): "Dia do Trabalho",
        p + timedelta(days=60): "Corpus Christi",
        date(ano, 9, 7): "Independência",
        date(ano, 10, 12): "Nossa Senhora Aparecida",
        date(ano, 11, 2): "Finados",
        date(ano, 11, 15): "Proclamação da República",
        date(ano, 11, 20): "Dia da Consciência Negra (Lei 14.759/2023)",
        date(ano, 12, 8): "Dia da Justiça",
        date(ano, 12, 25): "Natal",
    }


@lru_cache(maxsize=1)
def _config_tribunais() -> dict:
    if ARQUIVO_FERIADOS.exists():
        return json.loads(ARQUIVO_FERIADOS.read_text(encoding="utf-8"))
    return {}


def feriados_tribunal(tribunal: str | None, ano: int) -> dict[date, str]:
    """Feriados nacionais + regras do tribunal (prefixo, ex.: 'TRF' vale p/ TRF1..TRF6)."""
    feriados = feriados_nacionais(ano)
    if not tribunal:
        return feriados
    cfg = _config_tribunais()
    p = pascoa(ano)
    for chave, regras in cfg.items():
        if chave.startswith("_") or not tribunal.upper().startswith(chave.upper()):
            continue
        for item in regras.get("fixos", []):
            dia, mes = (int(x) for x in item["data"].split("/"))
            feriados[date(ano, mes, dia)] = item["nome"]
        for item in regras.get("relativos_pascoa", []):
            feriados[p + timedelta(days=item["dias"])] = item["nome"]
        for item in regras.get("datas", []):
            d = date.fromisoformat(item["data"])
            if d.year == ano:
                feriados[d] = item["nome"]
    return feriados


def em_recesso(d: date) -> bool:
    """CPC, art. 220: suspensão de prazos de 20/12 a 20/01, inclusive."""
    return (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 20)


def motivo_nao_util(d: date, tribunal: str | None) -> str | None:
    if d.weekday() == 5:
        return "sábado"
    if d.weekday() == 6:
        return "domingo"
    nome = feriados_tribunal(tribunal, d.year).get(d)
    if nome:
        return f"feriado: {nome}"
    return None


def eh_dia_util(d: date, tribunal: str | None) -> bool:
    return motivo_nao_util(d, tribunal) is None


def proximo_dia_util(d: date, tribunal: str | None) -> date:
    d += timedelta(days=1)
    while not eh_dia_util(d, tribunal):
        d += timedelta(days=1)
    return d


@dataclass
class ResultadoPrazo:
    disponibilizacao: date
    publicacao: date
    inicio: date
    vencimento: date
    dias: int
    contagem: str
    em_dobro: bool
    memoria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "disponibilizacao": self.disponibilizacao.isoformat(),
            "publicacao": self.publicacao.isoformat(),
            "inicio": self.inicio.isoformat(),
            "vencimento": self.vencimento.isoformat(),
            "dias": self.dias,
            "contagem": self.contagem,
            "em_dobro": self.em_dobro,
            "memoria": self.memoria,
        }


def calcular_prazo(
    disponibilizacao: date,
    dias: int,
    tribunal: str | None = None,
    contagem: str = "uteis",
    em_dobro: bool = False,
) -> ResultadoPrazo:
    """Calcula o vencimento a partir da data de disponibilização no diário."""
    if dias <= 0:
        raise ValueError("O prazo precisa ter pelo menos 1 dia.")
    if contagem not in ("uteis", "corridos"):
        raise ValueError("contagem deve ser 'uteis' ou 'corridos'")

    memoria: list[str] = []
    total = dias * 2 if em_dobro else dias
    if em_dobro:
        memoria.append(f"Prazo em dobro marcado pelo advogado: {dias} x 2 = {total} dias.")

    publicacao = proximo_dia_util(disponibilizacao, tribunal)
    memoria.append(
        f"Disponibilizado em {disponibilizacao:%d/%m/%Y}; considera-se publicado em "
        f"{publicacao:%d/%m/%Y} (Lei 11.419/2006, art. 4º, §3º)."
    )

    # 1º dia da contagem: dia útil seguinte à publicação, fora do recesso.
    inicio = proximo_dia_util(publicacao, tribunal)
    while em_recesso(inicio) or not eh_dia_util(inicio, tribunal):
        inicio += timedelta(days=1)
    memoria.append(f"Início da contagem: {inicio:%d/%m/%Y} (CPC, art. 224, §3º).")

    d = inicio
    contados = 1
    pulados: list[str] = []
    while contados < total:
        d += timedelta(days=1)
        if em_recesso(d):
            continue
        if contagem == "uteis":
            motivo = motivo_nao_util(d, tribunal)
            if motivo:
                if motivo.startswith("feriado"):
                    pulados.append(f"{d:%d/%m/%Y} ({motivo})")
                continue
        contados += 1

    if contagem == "uteis":
        memoria.append(f"Contados {total} dias úteis (CPC, art. 219).")
    else:
        memoria.append(f"Contados {total} dias corridos.")
    if pulados:
        memoria.append("Feriados pulados: " + "; ".join(pulados) + ".")
    if any(em_recesso(inicio + timedelta(days=i)) for i in range((d - inicio).days + 1)):
        memoria.append("Prazo suspenso no recesso forense de 20/12 a 20/01 (CPC, art. 220).")

    vencimento = d
    while not eh_dia_util(vencimento, tribunal) or em_recesso(vencimento):
        vencimento += timedelta(days=1)
    if vencimento != d:
        memoria.append(
            f"Vencimento em dia não útil ({d:%d/%m/%Y}); prorrogado para "
            f"{vencimento:%d/%m/%Y} (CPC, art. 224, §1º)."
        )
    memoria.append(f"Vencimento: {vencimento:%d/%m/%Y}.")

    return ResultadoPrazo(
        disponibilizacao=disponibilizacao,
        publicacao=publicacao,
        inicio=inicio,
        vencimento=vencimento,
        dias=total,
        contagem=contagem,
        em_dobro=em_dobro,
        memoria=memoria,
    )


def dias_uteis_restantes(hoje: date, vencimento: date, tribunal: str | None) -> int:
    """Quantos dias úteis faltam até o vencimento (0 = vence hoje, negativo = vencido)."""
    if vencimento < hoje:
        return -1
    n = 0
    d = hoje
    while d < vencimento:
        d += timedelta(days=1)
        if eh_dia_util(d, tribunal) and not em_recesso(d):
            n += 1
    return n
