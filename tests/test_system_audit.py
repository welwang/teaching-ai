"""Regression coverage for queue failures, image caches and controller lifecycle."""
import io,json,subprocess,tempfile,unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock,patch

from workflow_v2.store import Store,atomic
from workflow_v2 import worker,images,monitoring,runlog,model,health,office
from tests.test_design_system import sample_deck

REQUEST=dict(schema_version=1,grade=4,semester='上學期',subject='數學',unit='角',
             publisher='測試',difficulty='低難度',slide_count=8,source_path='test.md',
             model='qwen3.8:27b-q4_K_M',locale='zh-TW')


class SystemAuditTest(unittest.TestCase):
    def test_stage_launch_failure_releases_job_and_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);first=store.submit(REQUEST);second=store.submit(REQUEST)
            with patch.object(worker.subprocess,'Popen',side_effect=OSError('launch failed')):
                for _ in range(3):self.assertTrue(worker.step(store))
            self.assertEqual(store.get(first)['status'],'failed')
            self.assertEqual(store.claim()['id'],second)

    def test_broken_source_checkpoint_does_not_leave_running_job(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);source=Path(folder)/'source.md';source.write_text('教材',encoding='utf-8')
            jid=store.submit(dict(REQUEST,source_path=str(source)))
            with store.db() as c:c.execute('UPDATE jobs SET stage=1 WHERE id=?',(jid,))
            (store.folder(jid)/'source.json').write_text('{broken',encoding='utf-8')
            with patch.object(worker.subprocess,'Popen') as start:
                worker.step(store)
            start.assert_not_called();self.assertEqual(store.get(jid)['status'],'repairing')

    def test_stage_status_matches_actual_stage(self):
        for stage,state in ((3,'reviewing'),(4,'rendering'),(5,'running')):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as folder:
                store=Store(folder);jid=store.submit(REQUEST)
                with store.db() as c:c.execute('UPDATE jobs SET stage=? WHERE id=?',(stage,jid))
                store.claim();self.assertEqual(store.get(jid)['status'],state)
                store.pause_job(jid);store.resume_job(jid)
                self.assertEqual(store.get(jid)['status'],state)

    def test_existing_ui_launch_preserves_token_session(self):
        import launch_v2
        with tempfile.TemporaryDirectory() as folder,patch.object(launch_v2,'ROOT',Path(folder)):
            marker=Path(folder)/'data/workflow-v2/session-start.json';atomic(marker,{'started':123})
            with patch.object(launch_v2,'healthy',return_value=True),patch.object(launch_v2,'start_image_service'), \
                 patch.object(launch_v2.subprocess,'Popen') as start,redirect_stdout(io.StringIO()):
                launch_v2.main(no_browser=True)
            start.assert_not_called()
            self.assertEqual(json.loads(marker.read_text(encoding='utf-8'))['started'],123)

    def test_new_ui_launch_resets_session_after_success(self):
        import launch_v2
        proc=Mock();proc.pid=123;proc.poll.return_value=None
        with tempfile.TemporaryDirectory() as folder,patch.object(launch_v2,'ROOT',Path(folder)), \
             patch.object(launch_v2,'healthy',side_effect=[False,True,True]), \
             patch.object(launch_v2,'ensure_server'),patch.object(launch_v2,'start_image_service'), \
             patch.object(launch_v2.subprocess,'Popen',return_value=proc),redirect_stdout(io.StringIO()):
            launch_v2.main(no_browser=True)
            self.assertGreater(json.loads((Path(folder)/'data/workflow-v2/session-start.json').read_text(encoding='utf-8'))['started'],0)

    def test_removing_job_keeps_session_token_total(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);jid=store.submit(REQUEST)
            atomic(store.folder(jid)/'calls/page-1-attempt-0.json',{'prompt_eval_count':10,'eval_count':5})
            self.assertEqual(monitoring.session_usage(store,since=0)['total_tokens'],15)
            store.remove_job(jid)
            self.assertEqual(monitoring.session_usage(store,since=0)['total_tokens'],15)

    def test_partial_jsonl_does_not_break_control_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'run.jsonl';path.write_text('{"event":"ok"}\n{broken\n[]\n',encoding='utf-8')
            with patch.object(runlog,'SYSTEM_LOG',path):
                self.assertEqual(runlog.tail_events(),[{'event':'ok'}])

    def test_service_ready_requires_installed_fixed_model(self):
        response=Mock();response.json.return_value={'models':[]}
        with patch.object(health.requests,'get',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'尚未安裝'):health.models_probe()

    def test_local_endpoint_rejects_credentials_and_url_suffixes(self):
        for url in ('http://user:pass@localhost:11435','http://localhost:11435/api',
                    'http://localhost:11435?secret=value','https://localhost:11435'):
            with self.subTest(url=url),patch.object(model.yaml,'safe_load',return_value={'ollama_url':url}):
                with self.assertRaises(ValueError):model.endpoint()

    def test_cached_images_are_embedded_even_at_download_limit(self):
        page=sample_deck()['slides'][2];page['media_hint']['search_keyword']='open door'
        page['visual_asset'].update(is_required=True,asset_type='illustration',image_prompt='An open door')
        with tempfile.TemporaryDirectory() as folder:
            from PIL import Image
            out=Path(folder);picture=out/'cached.png';Image.new('RGB',(400,400),'teal').save(picture)
            atomic(out/'image-sources.json',{'1':{'local_path':str(picture),'search_keyword':'open door'}})
            with patch.object(images,'find_image') as search:
                media=images.online_images({'slides':[page]},out,max_images=0)
            search.assert_not_called();self.assertEqual(media[1],str(picture))
            self.assertEqual(json.loads((out/'visual-assets.json').read_text(encoding='utf-8'))['1']['status'],'cached')

    def test_changed_page_keyword_does_not_reuse_previous_picture(self):
        page=sample_deck()['slides'][2];page['media_hint']['search_keyword']='open door'
        page['visual_asset'].update(is_required=True,asset_type='illustration',image_prompt='An open door')
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);picture=out/'cached.png';picture.write_bytes(b'cached')
            atomic(out/'image-sources.json',{'1':{'local_path':str(picture),'search_keyword':'apple fruit'}})
            with patch.object(images,'find_image',return_value=None):
                self.assertEqual(images.online_images({'slides':[page]},out),{})
            self.assertEqual(json.loads((out/'image-sources.json').read_text(encoding='utf-8')),{})

    def test_office_timeout_stops_children_and_cleans_profile(self):
        proc=Mock();proc.communicate.side_effect=subprocess.TimeoutExpired('office',1)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);exe=root/'runtime/libreoffice/program/soffice.com'
            exe.parent.mkdir(parents=True);exe.touch()
            with patch.object(office,'ROOT',root),patch.object(office,'DATA',root/'data'), \
                 patch.object(office.subprocess,'Popen',return_value=proc), \
                 patch.object(worker,'stop_tree') as stop:
                (root/'test.pptx').write_bytes(b'mocked source')
                with self.assertRaises(subprocess.TimeoutExpired):office.convert_pdf(root/'test.pptx',root,timeout=1)
            stop.assert_called_once_with(proc);self.assertEqual(list(root.glob('office-*')),[])

    def test_failed_image_query_is_not_repeated_during_pagination(self):
        page=sample_deck()['slides'][2];page['media_hint']['search_keyword']='open door'
        page['visual_asset'].update(is_required=True,asset_type='illustration',image_prompt='An open door')
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder);failed=set()
            with patch.object(images,'find_image',return_value=None) as search:
                images.online_images({'slides':[page]},out,failed_keywords=failed)
                images.online_images({'slides':[page]},out,failed_keywords=failed)
            search.assert_called_once()
            self.assertEqual(json.loads((out/'visual-assets.json').read_text(encoding='utf-8'))['1']['status'],'unavailable')

    def test_system_office_installation_is_available_without_bundled_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);exe=root/'programs/LibreOffice/program/soffice.com'
            exe.parent.mkdir(parents=True);exe.touch()
            with patch.object(office,'ROOT',root),patch.object(office.shutil,'which',return_value=None), \
                 patch.dict('os.environ',{'ProgramFiles':str(root/'programs'),'ProgramFiles(x86)':''}):
                self.assertEqual(office.executable(),exe)


if __name__=='__main__':unittest.main()
