import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, Mock

from workflow_v2 import strata


class StrataTest(unittest.TestCase):
    def reply(self, content='{"answer":42}', finish='stop'):
        return {'model':'qwen3.8-flash-next-iq3_s', 'choices':[
            {'message':{'content':content},'finish_reason':finish}],
            'usage':{'prompt_tokens':120,'completion_tokens':15,
                'prompt_tokens_details':{'cached_tokens':100}},
            'timings':{'prompt_ms':12,'predicted_ms':30}}

    def test_monitoring_preserves_usage_timings_and_truncation(self):
        result = strata.normalize_reply(self.reply(finish='length'), .5)
        self.assertEqual(result['prompt_eval_count'], 120)
        self.assertEqual(result['eval_count'], 15)
        self.assertEqual(result['cached_tokens'], 100)
        self.assertEqual(result['prompt_eval_duration'], 12000000)
        self.assertEqual(result['eval_duration'], 30000000)
        self.assertEqual(result['done_reason'], 'length')

    def test_only_complete_fences_are_unwrapped(self):
        self.assertEqual(strata.normalize_reply(self.reply('```json\n{"answer":42}\n```'), 1)['message']['content'], '{"answer":42}')
        self.assertEqual(strata.normalize_reply(self.reply('```json\n{"answer":'), 1)['message']['content'], '```json\n{"answer":')

    def test_endpoint_rejects_external_and_invalid_urls(self):
        for url in ('https://example.com', 'http://example.com', 'ftp://localhost:8088',
                    'http://user:pass@localhost:8088', 'http://localhost:8088/v1'):
            with self.subTest(url=url), patch.object(strata, 'settings', return_value={'strata_url':url}):
                with self.assertRaises(ValueError): strata.endpoint()

    def test_context_uses_actual_engine_allocation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'strata.json'
            path.write_text(json.dumps({'args':['--max-context','131072']}))
            with patch.object(strata, 'config_path', return_value=path):
                self.assertEqual(strata.context_limit(), 131072)

    def test_one_million_context_is_refused_before_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'strata.json'
            path.write_text(json.dumps({'args':['--max-context','1048576']}))
            with patch.object(strata, 'config_path', return_value=path), \
                 patch.object(strata, 'installed', return_value=True), \
                 patch.object(strata.subprocess, 'Popen') as popen:
                with self.assertRaisesRegex(ValueError,'不啟用 1M'):
                    strata._start_server()
            popen.assert_not_called()

    def test_stream_collects_usage_and_always_closes_socket(self):
        final={'choices':[{'delta':{},'finish_reason':'stop'}],
               'usage':{'prompt_tokens':20,'completion_tokens':5}}
        response=Mock(ok=True)
        response.iter_lines.return_value=[b': heartbeat',
            b'data: '+json.dumps({'choices':[{'delta':{'content':'{"ok":true}'},'finish_reason':None}]}).encode(),
            b'data: '+json.dumps(final).encode(), b'data: [DONE]']
        messages=[{'role':'system','content':'JSON only'},{'role':'user','content':'test'}]
        with patch.object(strata,'endpoint',return_value='http://127.0.0.1:8088'), \
             patch.object(strata.requests,'post',return_value=response) as post:
            _, result=strata.request(strata.MODEL,messages,{'type':'object'},300)
        self.assertEqual(result['message']['content'],'{"ok":true}')
        self.assertEqual(result['prompt_eval_count'],20)
        response.close.assert_called_once()
        payload=post.call_args.kwargs['json']
        self.assertFalse(payload['chat_template_kwargs']['enable_thinking'])
        self.assertEqual(payload['max_tokens'],300)
        self.assertNotIn('response_format',payload)
        self.assertEqual(messages[0]['content'],'JSON only')

    def test_stream_without_finish_is_rejected(self):
        response=Mock(ok=True)
        response.iter_lines.return_value=[b'data: {"choices":[{"delta":{"content":"{\""},"finish_reason":null}]}']
        with patch.object(strata,'endpoint',return_value='http://127.0.0.1:8088'), \
             patch.object(strata.requests,'post',return_value=response):
            with self.assertRaises((ValueError,json.JSONDecodeError)):
                strata.request(strata.MODEL,[{'role':'system','content':'test'}],{},100)
        response.close.assert_called_once()

    def test_strata_call_uses_existing_validation_and_exclusive_gpu(self):
        from workflow_v2.model import call
        response=Mock(ok=True)
        with patch.object(strata,'ensure_ready'), patch.object(strata,'context_limit',return_value=131072), \
             patch.object(strata,'request',return_value=(response,strata.normalize_reply(self.reply(),1))), \
             patch('workflow_v2.model.gpu_slot') as slot, patch('workflow_v2.model.log_event'):
            value=call(strata.MODEL,'test',{'type':'object','required':['answer'],
                'properties':{'answer':{'type':'integer'}}},parallel=True)
        self.assertEqual(value,{'answer':42})
        slot.assert_called_once_with(False)

    def test_strata_truncation_never_becomes_a_success(self):
        from workflow_v2.model import call
        with patch.object(strata,'ensure_ready'), patch.object(strata,'context_limit',return_value=131072), \
             patch.object(strata,'request',return_value=(Mock(ok=True),strata.normalize_reply(self.reply(finish='length'),1))), \
             patch('workflow_v2.model.gpu_slot'), patch('workflow_v2.model.log_event'):
            with self.assertRaisesRegex(ValueError,'仍無完整有效 JSON'):
                call(strata.MODEL,'test',{'type':'object'},attempts=1)

    def test_unload_does_not_evict_resident_strata_between_stages(self):
        from workflow_v2.model import unload_model
        with patch('workflow_v2.model.requests.post') as post:
            unload_model(strata.MODEL)
        post.assert_not_called()

    def test_reused_pid_is_not_our_service(self):
        with tempfile.TemporaryDirectory() as folder:
            pid=Path(folder)/'pid';pid.write_text('123')
            process=Mock();process.cwd.return_value=str(strata.ROOT/'runtime/strata')
            process.cmdline.return_value=['python.exe','unrelated.py']
            with patch.object(strata,'PID_FILE',pid),patch.object(strata.psutil,'Process',return_value=process):
                self.assertIsNone(strata.owned_process())

    def test_mixed_providers_are_rejected_before_queue_mutation(self):
        from workflow_v2.store import Store
        with tempfile.TemporaryDirectory() as folder, \
             patch('workflow_v2.model_policy.settings',return_value={}):
            store=Store(folder)
            with self.assertRaisesRegex(ValueError,'不可混用'):
                store.submit({'model':strata.MODEL,'page_model':'qwen3.8:27b-q4_K_M'})
            self.assertEqual(store.list(),[])

    def test_installer_resumes_from_verified_range(self):
        import install_strata
        response=Mock(status_code=206,headers={'Content-Range':'bytes 3-5/6'})
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        response.iter_content.return_value=[b'xyz']
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'model.gguf';path.with_name(path.name+'.part').write_bytes(b'abc')
            with patch('requests.get',return_value=response) as get:
                install_strata.download('https://example.com/model',path)
            self.assertEqual(path.read_bytes(),b'abcxyz')
            self.assertEqual(get.call_args.kwargs['headers'],{'Range':'bytes=3-'})
            self.assertTrue(path.with_name(path.name+'.done').exists())

    def test_installer_rejects_wrong_range_without_corrupting_partial_file(self):
        import install_strata
        response=Mock(status_code=206,headers={'Content-Range':'bytes 0-2/6'})
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'model.gguf';part=path.with_name(path.name+'.part');part.write_bytes(b'abc')
            with patch('requests.get',return_value=response),patch('install_strata.time.sleep'):
                with self.assertRaisesRegex(ValueError,'incorrect download range'):
                    install_strata.download('https://example.com/model',path)
            self.assertEqual(part.read_bytes(),b'abc')
            self.assertFalse(path.exists())


if __name__=='__main__':unittest.main()
