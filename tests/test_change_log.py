import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from filelock import Timeout

from workflow_v2 import change_log, runlog
from workflow_v2.service import regenerate
from workflow_v2.store import Store, atomic
from tests.test_workflow_v2 import REQUEST, slide


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


class ChangeLogTest(unittest.TestCase):
    def test_real_slide_edits_record_before_after_and_ignore_unchanged_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            job = store.submit(REQUEST)
            out = store.folder(job)
            original = slide()
            atomic(out / 'slides/001.json', original)
            changed = dict(original, heading='新的標題')
            with change_log.change_context(stage='review', reason='修正標題與內容不一致'):
                atomic(out / 'slides/001.json', changed)
            atomic(out / 'slides/001.json', changed)
            records = rows(out / 'changes.jsonl')
            self.assertEqual(len(records), 2)
            edit = records[-1]
            self.assertEqual(edit['page'], 1)
            self.assertEqual(edit['before'], original)
            self.assertEqual(edit['after'], changed)
            self.assertEqual(edit['stage'], 'review')
            self.assertEqual(edit['changes'], [{'path': '/heading', 'operation': 'replace', 'before': original['heading'], 'after': '新的標題'}])
            self.assertNotEqual(edit['before_sha256'], edit['after_sha256'])
            self.assertEqual(rows(change_log.history_paths(store.root)[0]), records)
            atomic(out / 'review-progress.json', {'completed_pages': 1})
            self.assertEqual(len(rows(out / 'changes.jsonl')), 2)

    def test_user_revision_links_parent_request_and_actual_result(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            parent = store.submit(REQUEST)
            out = store.folder(parent)
            atomic(out / 'source.json', {'pages': []})
            atomic(out / 'plan.json', {'slides': [{}, {}]})
            original = slide()
            atomic(out / 'slides/001.json', original)
            atomic(out / 'slides/002.json', original)
            with store.db() as connection:
                connection.execute("UPDATE jobs SET status='done' WHERE id=?", (parent,))
            child = regenerate(parent, 0, '把標題寫得更清楚', store, field='heading')
            revised = dict(original, heading='修訂後標題')
            atomic(store.folder(child) / 'slides/001.json', revised)
            records = rows(store.folder(child) / 'changes.jsonl')
            request = next(r for r in records if r['action'] == 'page_revision_requested')
            result = next(r for r in records if r.get('artifact') == 'slides/001.json')
            self.assertEqual(request['actor'], 'user')
            self.assertEqual(result['before'], original)
            self.assertEqual(result['after'], revised)
            self.assertEqual(result['parent_job'], parent)
            self.assertEqual(result['instruction'], '把標題寫得更清楚')
            self.assertEqual(result['requested_field'], 'heading')

    def test_custom_prompt_and_history_survive_runtime_log_clear(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            job = store.submit(dict(REQUEST, teaching_prompt_override='用操作與口述理解概念。'))
            out = store.folder(job)
            records = rows(out / 'changes.jsonl')
            self.assertEqual(records[0]['action'], 'teaching_prompt_customized')
            self.assertEqual(records[0]['after'], '用操作與口述理解概念。')
            with patch.object(runlog, 'DATA', store.root):
                runlog.clear_log(job)
            self.assertEqual(rows(out / 'changes.jsonl'), records)
            self.assertEqual(rows(change_log.history_paths(store.root)[0]), records)

    def test_parallel_logging_is_complete_and_valid_jsonl(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            out = store.folder(store.submit(REQUEST))
            with ThreadPoolExecutor(max_workers=6) as executor:
                entries = list(executor.map(lambda index: change_log.record(out, 'test_edit', before=index, after=index + 1), range(20)))
            actual = rows(out / 'changes.jsonl')
            self.assertEqual(len(actual), 20)
            self.assertEqual({r['change_id'] for r in actual}, {r['change_id'] for r in entries})
            self.assertEqual(rows(change_log.history_paths(store.root)[0]), actual)

    def test_logging_failure_does_not_undo_saved_page(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            out = store.folder(store.submit(REQUEST))
            with patch.object(change_log, 'FileLock', side_effect=Timeout('locked')):
                atomic(out / 'slides/001.json', slide())
            self.assertEqual(json.loads((out / 'slides/001.json').read_text(encoding='utf-8')), slide())

    def test_missing_policy_metadata_does_not_block_history(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            out = store.folder(store.submit(REQUEST))
            with patch('workflow_v2.curriculum_prompts.policy_fingerprint', side_effect=OSError('metadata unavailable')):
                atomic(out / 'slides/001.json', slide())
            self.assertEqual(rows(out / 'changes.jsonl')[0]['teaching_policy_fingerprint'], '')

    def test_differences_preserve_added_removed_and_null_fields(self):
        actual = change_log.differences({'a/b': None, 'old': 'x'}, {'a/b': 3, 'new': None})
        self.assertIn({'path': '/a~1b', 'operation': 'replace', 'before': None, 'after': 3}, actual)
        self.assertIn({'path': '/old', 'operation': 'remove', 'before': 'x', 'after': None}, actual)
        self.assertIn({'path': '/new', 'operation': 'add', 'before': None, 'after': None}, actual)


if __name__ == '__main__':
    unittest.main()
