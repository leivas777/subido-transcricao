import json
import tempfile
import unittest
import shutil
import subprocess
import importlib.util
from pathlib import Path
from unittest.mock import patch
import transcrever as t
from consumo import summarize
from comparar_custos import project


class Contracts(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ffmpeg') and importlib.util.find_spec('numpy'), 'Requer FFmpeg e numpy')
    def test_real_ffmpeg_decoding_returns_whisper_array(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / 'tone.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=1', '-ar', '44100', '-ac', '2', str(media)], check=True)
            audio = t.decode_for_whisper(media)
            self.assertEqual(audio.ndim, 1)
            self.assertEqual(str(audio.dtype), 'float32')
            self.assertAlmostEqual(len(audio)/16000, 1, places=2)

    def setUp(self):
        self.batch = [{'id': 0, 'text': 'o custo é 25 reais'}, {'id': 1, 'text': 'abra o Meta Ads'}]

    def test_rejects_changed_number_and_missing_segment(self):
        with self.assertRaises(ValueError):
            t.validate_revision(self.batch, {'segments': [{'id': 0, 'text': 'O custo é 50 reais.'}, self.batch[1]]})
        with self.assertRaises(ValueError):
            t.validate_revision(self.batch, {'segments': self.batch[:1]})

    def test_export_keeps_original_times(self):
        segments = [{'id': 0, 'start': 3599.999, 'end': 3602.5, 'text': 'Teste.'}]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            t.export(folder, segments, 'original')
            self.assertIn('00:59:59,999 --> 01:00:02,500', (folder / 'original.srt').read_text())

    def test_openrouter_uses_exact_model_and_rejects_truncation(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({'segments': [{'id': 0, 'text': 'O custo é 25 reais.'}, {'id': 1, 'text': 'Abra o Meta Ads.'}]})}}], 'usage': {'total_tokens': 10}}).encode()
        def mocked(request, timeout):
            payload = json.loads(request.data)
            self.assertEqual(payload['model'], t.MODEL)
            self.assertNotIn('models', payload)
            self.assertFalse(payload['provider']['allow_fallbacks'])
            self.assertEqual(request.full_url, 'https://openrouter.ai/api/v1/chat/completions')
            return Response()
        with patch('urllib.request.urlopen', mocked):
            revised, usage = t.review('fake-test-key', self.batch)
            self.assertEqual(len(revised), 2)
            self.assertEqual(usage['total_tokens'], 10)
        with patch.object(Response, 'read', lambda self: json.dumps({'choices': [{'finish_reason': 'length'}]}).encode()):
            with patch('urllib.request.urlopen', mocked), self.assertRaises(ValueError):
                t.review('fake-test-key', self.batch)

    def test_atomic_cache_and_changed_prompt_key(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'cache.json'
            t.write_json(dest, {'segments': self.batch})
            self.assertEqual(json.loads(dest.read_text())['segments'], self.batch)
            self.assertFalse(Path(str(dest) + '.tmp').exists())
        self.assertNotEqual(t.digest((t.PROMPT + 'v1').encode()), t.digest((t.PROMPT + 'v2').encode()))

    def test_rejected_response_retains_usage_on_disk_and_cache_has_no_new_cost(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self):
                return json.dumps({'id': 'gen-test', 'model': t.MODEL, 'usage': {
                    'prompt_tokens': 30, 'completion_tokens': 20, 'total_tokens': 50, 'cost': .001},
                    'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                        'segments': [{'id': 0, 'text': 'O custo é 50 reais.'}, {'id': 1, 'text': 'Abra o Meta Ads.'}]})}}]}).encode()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / 'aula.m4a'
            media.write_bytes(b'test audio: cache prevents decoding')
            cache_id = t.digest(f'{t.file_hash(media)}|small|pt|vad|v1'.encode())
            folder = root / f'aula-{cache_id[:12]}'
            folder.mkdir()
            segments = [{**s, 'start': i*30, 'end': (i+1)*30} for i, s in enumerate(self.batch)]
            t.write_json(folder / 'original.json', {'cache_id': cache_id, 'duration': 60, 'segments': segments})
            argv = ['transcrever.py', '--entrada', str(media), '--destino', str(root), '--openrouter']
            with patch('sys.argv', argv), patch.dict('os.environ', {'OPENROUTER_API_KEY': 'fake-test-key'}), patch('urllib.request.urlopen', return_value=Response()):
                self.assertEqual(t.main(), 2)
            report = json.loads((folder / 'consumo.json').read_text())
            self.assertEqual(report['rejected'], 1)
            self.assertEqual(report['tokens']['total_tokens'], 50)
            self.assertEqual(report['cost_per_processed_minute_usd'], .001)
            ledger = next((folder / 'chamadas').glob('*.json')).read_text()
            self.assertIn('gen-test', ledger)
            self.assertNotIn('fake-test-key', ledger)
            # A validated cached batch must not call the API or charge again.
            batch_id = t.digest(json.dumps([t.MODEL, t.PROMPT, self.batch], ensure_ascii=False, sort_keys=True).encode())
            t.write_json(folder / f'revisao-{batch_id}.json', {'segments': self.batch})
            with patch('sys.argv', argv), patch.dict('os.environ', {'OPENROUTER_API_KEY': 'fake-test-key'}), patch('urllib.request.urlopen') as request:
                self.assertEqual(t.main(), 0)
                request.assert_not_called()
            current = json.loads((folder / 'consumo-execucao.json').read_text())
            self.assertEqual(current['cost_usd'], 0)
            self.assertEqual(current['attempts'], 0)
            self.assertEqual(json.loads((folder / 'consumo.json').read_text())['cost_usd'], .001)

    def test_cost_unknown_and_retry_does_not_duplicate_duration(self):
        records = [{'status': 'rejeitada', 'audio_interval': [0, 60], 'usage': {'cost': .002}},
                   {'status': 'aceita', 'audio_interval': [0, 60], 'usage': {'cost': .003}}]
        report = summarize(records, 120)
        self.assertAlmostEqual(report['cost_per_processed_minute_usd'], .005)
        self.assertEqual(report['audio_minutes_represented'], 1)
        self.assertEqual(report['attempts_missing_token_fields']['prompt_tokens'], 2)
        records.append({'status': 'envio_sem_resultado_confirmado', 'audio_interval': [60, 120], 'usage': {}})
        report = summarize(records, 120)
        self.assertIsNone(report['cost_usd'])
        self.assertIsNone(report['cost_per_processed_minute_usd'])
        self.assertEqual(report['known_cost_usd'], .005)
        self.assertEqual(report['unconfirmed_responses'], 1)

    def test_truncation_callback_precedes_validation(self):
        from io import BytesIO
        data = {'id': 'gen-length', 'usage': {'total_tokens': 100, 'cost': 0}, 'choices': [{'finish_reason': 'length'}]}
        seen = []
        with patch('urllib.request.urlopen', return_value=BytesIO(json.dumps(data).encode())):
            with self.assertRaises(ValueError):
                t.review('fake', self.batch, on_response=seen.append)
        self.assertEqual(seen[0]['usage']['total_tokens'], 100)

    def test_projection_math_and_zero_duration(self):
        catalog = {'models': [{'input': .1, 'output': .4}]}
        self.assertAlmostEqual(project(catalog, 300, 300, 1)[0]['estimated_usd_per_minute'], .00015)
        with self.assertRaises(ValueError):
            project(catalog, 300, 300, 0)

    def test_gemini_is_explicit_and_cache_key_separates_models(self):
        from io import BytesIO
        gemini = 'google/gemini-2.5-flash-lite'
        def mocked(request, timeout):
            payload = json.loads(request.data)
            self.assertEqual(payload['model'], gemini)
            self.assertFalse(payload['provider']['allow_fallbacks'])
            self.assertNotIn('models', payload)
            return BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
                'message': {'content': json.dumps({'segments': self.batch})}}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30, 'cost': .000009}}).encode())
        with patch('urllib.request.urlopen', mocked):
            revised, usage = t.review('fake', self.batch, model=gemini)
        self.assertEqual(revised, self.batch)
        self.assertEqual(usage['cost'], .000009)
        keys = [t.digest(json.dumps([m, t.PROMPT, self.batch], ensure_ascii=False, sort_keys=True).encode())
                for m in (t.MODEL, gemini)]
        self.assertNotEqual(keys[0], keys[1])
        with patch('urllib.request.urlopen') as request, self.assertRaises(ValueError):
            t.review('fake', self.batch, model='unapproved/model')
        request.assert_not_called()

    def test_key_input_trims_outer_whitespace_and_rejects_bad_paste(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(t, 'read_env_key', return_value=''), patch('getpass.getpass', return_value='\u00a0fake-key\n'):
            self.assertEqual(t.read_key(), 'fake-key')
        for value in ['Bearer fake', '"fake"', 'fake key', '']:
            with patch.dict('os.environ', {}, clear=True), patch.object(t, 'read_env_key', return_value=''), patch('getpass.getpass', return_value=value):
                with self.assertRaises(ValueError):
                    t.read_key()

    def test_key_check_only_queries_metadata(self):
        from io import BytesIO, StringIO
        def mocked(request, timeout):
            self.assertEqual(request.full_url, 'https://openrouter.ai/api/v1/key')
            self.assertEqual(request.get_method(), 'GET')
            self.assertIsNone(request.data)
            return BytesIO(json.dumps({'data': {'label': 'private-label'}}).encode())
        output = StringIO()
        with patch('sys.argv', ['transcrever.py', '--testar-chave']), patch.object(t, 'read_key', return_value='fake'), patch('urllib.request.urlopen', mocked), patch('sys.stdout', output):
            self.assertEqual(t.main(), 0)
        self.assertIn('Autenticação OpenRouter confirmada', output.getvalue())
        self.assertNotIn('private-label', output.getvalue())

    def test_401_message_never_exposes_response_body(self):
        from io import BytesIO
        from urllib.error import HTTPError
        error = HTTPError('https://openrouter.ai/api/v1/key', 401, 'Unauthorized', {}, BytesIO(b'private-key-data'))
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                t.check_key('fake')
        self.assertIn('HTTP 401', str(caught.exception))
        self.assertNotIn('private-key-data', str(caught.exception))

    def test_env_key_is_resolved_beside_script_without_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            env = Path(directory) / '.env'
            env.write_text('# exemplo\nOPENROUTER_API_KEY="fake-local-key"\nOTHER=value\n')
            with patch.object(t, 'ENV_PATH', env), patch.dict('os.environ', {}, clear=True), patch('getpass.getpass') as prompt:
                self.assertEqual(t.read_key(), 'fake-local-key')
                prompt.assert_not_called()
            with patch.object(t, 'ENV_PATH', env), patch.dict('os.environ', {'OPENROUTER_API_KEY': 'fake-environment-key'}):
                self.assertEqual(t.read_key(), 'fake-environment-key')
            self.assertEqual(t.read_env_key(Path(directory) / 'missing.env'), '')
            env.write_text('OPENROUTER_API_KEY=fake\nOPENROUTER_API_KEY=other\n')
            with self.assertRaises(ValueError):
                t.read_env_key(env)
            env.write_text('OPENROUTER_API_KEY="fake\n')
            with self.assertRaises(ValueError):
                t.read_env_key(env)


if __name__ == '__main__':
    unittest.main()
