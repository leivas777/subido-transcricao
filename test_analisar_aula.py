import copy
import unittest
from analisar_aula import validate, manual, reconcile


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.bundle = {'metadata': {'pdf': None}, 'fontes': {
            'video:0': {'text': 'Defina o objetivo antes de anunciar.', 'start': 10, 'end': 14}}}
        self.value = {'resumo': [{'texto': 'Escolher um objetivo antecede o anúncio.',
                      'evidencias': [{'fonte': 'video:0', 'trecho': 'Defina o objetivo'}]}],
                      'praticas': [], 'comparacao': [], 'lacunas': ['Imagens do vídeo não analisadas.']}

    def test_valid_reference_and_timestamps(self):
        validate(self.value, self.bundle)
        self.assertIn('00:00:10.000', manual(self.value, self.bundle))

    def test_invented_source_rejected(self):
        self.value['resumo'][0]['evidencias'][0]['fonte'] = 'video:999'
        with self.assertRaises(ValueError):
            validate(self.value, self.bundle)

    def test_pdf_layout_whitespace_accepted(self):
        self.bundle['fontes']['video:0']['text'] = 'Defina\n \no\nobjetivo antes de anunciar.'
        validate(self.value, self.bundle)

    def test_unique_literal_reference_corrected(self):
        self.value['resumo'][0]['evidencias'][0]['fonte'] = 'video:999'
        corrected, report = reconcile(self.value, self.bundle)
        self.assertEqual(corrected['resumo'][0]['evidencias'][0]['fonte'], 'video:0')
        self.assertEqual(len(report['correcoes_ids']), 1)
        self.assertEqual(report['pendencias'], [])
        self.assertEqual(self.value['resumo'][0]['evidencias'][0]['fonte'], 'video:999')

    def test_ambiguous_reference_requires_review(self):
        self.bundle['fontes']['video:1'] = copy.deepcopy(self.bundle['fontes']['video:0'])
        self.value['resumo'][0]['evidencias'][0]['fonte'] = 'video:999'
        _, report = reconcile(self.value, self.bundle)
        self.assertEqual(len(report['pendencias']), 1)

    def test_changed_words_not_repaired(self):
        self.value['resumo'][0]['evidencias'][0]['trecho'] = 'Defina seu objetivo'
        _, report = reconcile(self.value, self.bundle)
        self.assertEqual(len(report['pendencias']), 1)

    def test_consecutive_segments_expanded_with_exact_text(self):
        self.bundle['fontes'] = {'video:0': {'text': 'Escolha um objetivo', 'start': 0, 'end': 2},
                                  'video:1': {'text': 'antes de anunciar.', 'start': 2, 'end': 4}}
        self.value['resumo'][0]['evidencias'] = [{'fonte': 'video:0', 'trecho': 'um objetivo antes de anunciar.'}]
        corrected, report = reconcile(self.value, self.bundle)
        self.assertEqual(len(corrected['resumo'][0]['evidencias']), 2)
        self.assertEqual(len(report['citacoes_multissegmentos']), 1)
        self.assertFalse(report['pendencias'])
        validate(corrected, self.bundle)

    def test_invented_quote_rejected(self):
        self.value['resumo'][0]['evidencias'][0]['trecho'] = 'Invista R$ 100'
        with self.assertRaises(ValueError):
            validate(self.value, self.bundle)

    def test_pdf_comparison_without_pdf_rejected(self):
        self.value['comparacao'] = copy.deepcopy(self.value['resumo'])
        with self.assertRaises(ValueError):
            validate(self.value, self.bundle)

    def test_step_without_evidence_rejected(self):
        self.value['praticas'] = [{'titulo': 'Definir objetivo',
             'evidencias': self.value['resumo'][0]['evidencias'],
             'quando_usar': [], 'pre_requisitos': [], 'metricas': [], 'excecoes': [],
             'passos': [{'texto': 'Configure uma campanha', 'evidencias': []}]}]
        with self.assertRaises(ValueError):
            validate(self.value, self.bundle)


if __name__ == '__main__':
    unittest.main()
