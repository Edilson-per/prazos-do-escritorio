"""Testes do cálculo de prazo. Rodar com: python -m unittest discover -s tests

Cada caso foi conferido à mão no calendário. Ao achar um erro real em uso,
acrescente aqui o caso que falhou antes de corrigir o código.
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.prazos import calcular_prazo, eh_dia_util, pascoa  # noqa: E402


class TestPascoa(unittest.TestCase):
    def test_datas_conhecidas(self):
        self.assertEqual(pascoa(2025), date(2025, 4, 20))
        self.assertEqual(pascoa(2026), date(2026, 4, 5))
        self.assertEqual(pascoa(2027), date(2027, 3, 28))


class TestCalendario(unittest.TestCase):
    def test_consciencia_negra_nao_e_util(self):
        self.assertFalse(eh_dia_util(date(2026, 11, 20), None))

    def test_quarta_santa_so_na_justica_federal(self):
        self.assertFalse(eh_dia_util(date(2026, 4, 1), "TRF3"))
        self.assertTrue(eh_dia_util(date(2026, 4, 1), "TJSP"))


class TestPrazo(unittest.TestCase):
    def test_15_dias_uteis_com_feriado_no_meio(self):
        # Disponibilizado ter 10/11/2026 -> publicado qua 11/11 -> início qui 12/11.
        # Pula 20/11 (Consciência Negra). 15º dia útil = qui 03/12/2026.
        r = calcular_prazo(date(2026, 11, 10), 15, "TJSP")
        self.assertEqual(r.publicacao, date(2026, 11, 11))
        self.assertEqual(r.inicio, date(2026, 11, 12))
        self.assertEqual(r.vencimento, date(2026, 12, 3))

    def test_recesso_suspende(self):
        # Início qua 16/12; conta 16,17,18; suspende 20/12-20/01; volta qui 21/01/2027.
        # Sem feriado local: 15º dia útil = sex 05/02/2027.
        r = calcular_prazo(date(2026, 12, 14), 15, None)
        self.assertEqual(r.vencimento, date(2027, 2, 5))

    def test_recesso_mais_feriados_locais_e_carnaval(self):
        # TJSP: pula 25/01 (aniversário de SP) e o Carnaval (08 e 09/02/2027).
        r = calcular_prazo(date(2026, 12, 14), 15, "TJSP")
        self.assertEqual(r.vencimento, date(2027, 2, 10))

    def test_disponibilizacao_antes_de_feriado(self):
        # Disponibilizado qui 19/11; 20/11 feriado -> publicado seg 23/11 -> início ter 24/11.
        r = calcular_prazo(date(2026, 11, 19), 5, None)
        self.assertEqual(r.publicacao, date(2026, 11, 23))
        self.assertEqual(r.vencimento, date(2026, 11, 30))

    def test_corridos_prorroga_vencimento_em_fim_de_semana(self):
        # Início seg 09/11; 6 dias corridos terminam sáb 14/11 -> prorroga para seg 16/11.
        r = calcular_prazo(date(2026, 11, 5), 6, None, contagem="corridos")
        self.assertEqual(r.inicio, date(2026, 11, 9))
        self.assertEqual(r.vencimento, date(2026, 11, 16))

    def test_em_dobro(self):
        r = calcular_prazo(date(2026, 11, 10), 15, "TJSP", em_dobro=True)
        self.assertEqual(r.dias, 30)
        self.assertGreater(r.vencimento, date(2026, 12, 3))

    def test_prazo_invalido(self):
        with self.assertRaises(ValueError):
            calcular_prazo(date(2026, 11, 10), 0)

    def test_memoria_de_calculo_explica(self):
        r = calcular_prazo(date(2026, 11, 10), 15, "TJSP")
        texto = " ".join(r.memoria)
        self.assertIn("Consciência Negra", texto)
        self.assertIn("art. 219", texto)


if __name__ == "__main__":
    unittest.main()
