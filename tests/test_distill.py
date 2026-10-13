import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from distill import adopt, build, collect, common, evaluate, export, sample, score, train, units
from workflow_v2 import model, model_policy


class CommonTests(unittest.TestCase):
    def test_task_of(self):
        self.assertEqual(common.task_of('page-03'), 'page')
        self.assertEqual(common.task_of('page-12-attempt-2'), 'page')
        self.assertEqual(common.task_of('plan-call'), 'plan')
        self.assertEqual(common.task_of('analysis-call'), 'analysis')
        self.assertEqual(common.task_of('review-1'), 'review')
        self.assertNotIn(common.task_of('final-optimize'), common.TRAINABLE)
        self.assertEqual(common.page_index('page-03'), 2)
        self.assertIsNone(common.page_index('plan-call'))

    def test_held_out_is_stable_and_about_one_in_ten(self):
        keys = [f'unit-{i}' for i in range(2000)]
        share = sum(common.held_out(k) for k in keys) / len(keys)
        self.assertTrue(0.06 < share < 0.14, share)
        self.assertEqual([common.held_out(k) for k in keys[:50]], [common.held_out(k) for k in keys[:50]])

    def test_prompt_key_ignores_key_order(self):
        a = [{'role': 'user', 'content': 'x'}]
        b = [{'content': 'x', 'role': 'user'}]
        self.assertEqual(common.prompt_key(a), common.prompt_key(b))
        self.assertNotEqual(common.prompt_key(a), common.prompt_key([{'role': 'user', 'content': 'y'}]))

    def test_json_helpers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a' / 'b.json'
            common.write_json(path, {'中': 1})
            self.assertEqual(common.read_json(path), {'中': 1})
            self.assertEqual(common.read_json(Path(folder) / 'none.json', 7), 7)
            rows = Path(folder) / 'r.jsonl'
            common.append_jsonl(rows, [{'a': 1}, {'a': 2}])
            with rows.open('a', encoding='utf-8') as handle:
                handle.write('broken\n')
            self.assertEqual(common.read_jsonl(rows), [{'a': 1}, {'a': 2}])


class JudgeTests(unittest.TestCase):
    def test_truncated_and_broken_json_fail(self):
        self.assertFalse(score.judge('page-01', '{"a":1}', {}, None, 'length')['passed'])
        bad = score.judge('analysis-call', 'not json', {}, None)
        self.assertFalse(bad['passed'])
        self.assertEqual(bad['hard'], 99)

    def test_unclosed_json_is_not_trainable(self):
        verdict = score.judge('analysis-call', '{"concepts": ["a"]', {}, None)
        self.assertFalse(verdict['passed'])

    def test_tasks_without_judge_fail(self):
        self.assertFalse(score.judge('review-1', '{}', {}, None)['passed'])

    def test_rank_prefers_passing_then_fewer_problems_then_shorter(self):
        ok_long = score._verdict(True, chars=900)
        ok_short = score._verdict(True, chars=300)
        ok_minor = score._verdict(True, minor=1, chars=100)
        bad = score._verdict(False, hard=0, major=1, chars=10)
        ordered = sorted([bad, ok_minor, ok_long, ok_short], key=score.rank)
        self.assertEqual(ordered, [ok_short, ok_long, ok_minor, bad])


class PickTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(sample, 'CANDIDATES', Path(self.folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.folder.cleanup)
        self.row = {'name': 'page-01', 'job_folder': '/x/job-1', 'messages': [{'role': 'user', 'content': 'p'}],
                    'schema': {}, 'content': 'ORIGINAL', 'done_reason': 'stop'}

    def fake_judge(self, name, content, schema, context, reason=''):
        return score._verdict(content.startswith('GOOD'), hard=0 if content.startswith('GOOD') else 1, chars=len(content))

    def test_original_kept_without_extra_calls(self):
        self.row['content'] = 'GOOD original'
        asker = mock.Mock()
        with mock.patch.object(sample, 'judge', self.fake_judge):
            record = sample.pick('k1', self.row, None, tries=3, asker=asker)
        asker.assert_not_called()
        self.assertEqual(record['best'], 0)

    def test_retries_until_pass(self):
        replies = iter([('bad', 'stop'), ('GOOD second', 'stop'), ('GOOD never', 'stop')])
        with mock.patch.object(sample, 'judge', self.fake_judge):
            record = sample.pick('k2', self.row, None, tries=4, asker=lambda row, t, s: next(replies))
        self.assertEqual(len(record['candidates']), 3)
        self.assertEqual(record['best'], 2)
        self.assertEqual(record['candidates'][2]['source'], 'sample-1002')

    def test_gives_up_after_tries_and_survives_errors(self):
        def asker(row, t, s):
            raise RuntimeError('timeout')
        with mock.patch.object(sample, 'judge', self.fake_judge):
            record = sample.pick('k3', self.row, None, tries=2, asker=asker)
        self.assertIsNone(record['best'])
        self.assertEqual(len(record['candidates']), 3)
        again = sample.pick('k3', self.row, None, tries=2, asker=mock.Mock(side_effect=AssertionError))
        self.assertEqual(len(again['candidates']), 3)

    def test_requests_to_judge_dedupes_and_prefers_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            base = {'name': 'page-01', 'messages': [{'role': 'user', 'content': 'same'}], 'schema': {}, 'job_folder': 'j'}
            common.write_json(Path(folder) / 'job' / 'a.json', dict(base, accepted=False, content='x'))
            common.write_json(Path(folder) / 'job' / 'b.json', dict(base, accepted=True, content='y'))
            common.write_json(Path(folder) / 'job' / 'c.json', dict(base, name='review-1', messages=[{'role': 'user', 'content': 'r'}]))
            found = sample.requests_to_judge(folder)
        self.assertEqual(len(found), 1)
        self.assertEqual(next(iter(found.values()))['content'], 'y')


class BuildTests(unittest.TestCase):
    def test_examples_use_best_passing_reply(self):
        with tempfile.TemporaryDirectory() as folder:
            messages = [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}]
            ok = score._verdict(True)
            common.write_json(Path(folder) / 'a.json', {'task': 'page', 'job_folder': '/d/job-a', 'messages': messages, 'best': 1,
                                                        'candidates': [{'source': 'original', 'content': 'bad', 'verdict': score._verdict(False)},
                                                                       {'source': 'sample-1001', 'content': '{"ok":1}', 'verdict': ok}]})
            common.write_json(Path(folder) / 'b.json', {'task': 'page', 'job_folder': '/d/job-b', 'messages': messages, 'best': None,
                                                        'candidates': [{'source': 'original', 'content': 'bad', 'verdict': score._verdict(False)}]})
            rows = list(build.examples(folder))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['messages'][-1], {'role': 'assistant', 'content': '{"ok":1}'})
        self.assertEqual(rows[0]['job'], 'job-a')
        self.assertEqual(build.summary(rows), {'page': {'examples': 1, 'from_retries': 1}})

    def test_validation_split_is_per_job(self):
        jobs = [f'job-{i}' for i in range(400)]
        share = sum(build.is_validation(j) for j in jobs) / len(jobs)
        self.assertTrue(0.01 < share < 0.12, share)


class FakeTokenizer:
    eos_token = '<E>'

    def apply_chat_template(self, messages, tokenize, add_generation_prompt, enable_thinking):
        assert not tokenize and add_generation_prompt and enable_thinking is False
        return ''.join(f'<{m["role"]}>{m["content"]}' for m in messages) + '<assistant>'

    def __call__(self, text, add_special_tokens=False):
        return {'input_ids': [ord(c) for c in text]}


class TrainTests(unittest.TestCase):
    def test_prompt_masked_and_reply_learned(self):
        row = {'messages': [{'role': 'system', 'content': 's'}, {'role': 'user', 'content': 'u'}, {'role': 'assistant', 'content': 'ab'}]}
        kept, dropped, lengths = train.tokenize(FakeTokenizer(), [row], 1000)
        self.assertEqual(dropped, 0)
        item = kept[0]
        reply = [ord(c) for c in 'ab<E>']
        self.assertEqual(item['input_ids'][-len(reply):], reply)
        self.assertEqual([x for x in item['labels'] if x != -100], reply)
        self.assertEqual(len(item['labels']), len(item['input_ids']))

    def test_long_rows_dropped(self):
        row = {'messages': [{'role': 'user', 'content': 'u' * 50}, {'role': 'assistant', 'content': 'a'}]}
        kept, dropped, _ = train.tokenize(FakeTokenizer(), [row], 20)
        self.assertEqual((len(kept), dropped), (0, 1))


class ExportTests(unittest.TestCase):
    def test_model_name_keeps_prefix(self):
        name = export.model_name('run-20261008-2200')
        self.assertTrue(name.startswith('qwen3.8:27b'))
        self.assertEqual(name, 'qwen3.8:27b-teach-run-20261008-2200')
        self.assertLessEqual(len(export.model_name('X' * 80).split('teach-')[1]), 24)

    def test_modelfile_replaces_from(self):
        base = '# Modelfile generated by "ollama show"\nFROM C:\\models\\blobs\\sha256-abc\nTEMPLATE """{{ .Prompt }}"""\nPARAMETER temperature 0.6\n'
        text = export.modelfile(base, 'F:\\run\\model.gguf')
        self.assertTrue(text.startswith('FROM F:\\run\\model.gguf\n'))
        self.assertEqual(text.count('FROM'), 1)
        self.assertIn('TEMPLATE', text)
        self.assertIn('PARAMETER temperature 0.6', text)
        self.assertNotIn('# Modelfile', text)


class EvaluateTests(unittest.TestCase):
    def metrics(self, first, fallbacks=0, seconds=600, json_errors=0):
        return {'pages': 10, 'first_try': first, 'rewrites': 10 - first, 'qa_rejections': 0, 'fallbacks': fallbacks,
                'kept_for_teacher': 0, 'json_rejections': json_errors, 'seconds': seconds}

    def test_total(self):
        value = evaluate.total([self.metrics(6), self.metrics(8)])
        self.assertEqual(value['pages'], 20)
        self.assertEqual(value['first_try_rate'], 0.7)
        self.assertEqual(value['seconds_per_page'], 60.0)
        self.assertEqual(value['jobs'], 2)

    def test_verdict(self):
        old = evaluate.total([self.metrics(6)])
        self.assertEqual(evaluate.verdict(old, evaluate.total([self.metrics(8)]))[0], 'adopt')
        self.assertEqual(evaluate.verdict(old, evaluate.total([self.metrics(6)]))[0], 'keep')
        self.assertEqual(evaluate.verdict(old, evaluate.total([self.metrics(9, fallbacks=1)]))[0], 'keep')
        self.assertEqual(evaluate.verdict(old, evaluate.total([self.metrics(9, seconds=800)]))[0], 'keep')

    def test_job_metrics(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            common.write_json(out / 'plan.json', {'slides': [{}, {}, {}]})
            common.write_json(out / 'qa-report.json', {'pages': {'1': {'final': 'passed'}, '2': {'final': 'passed'}, '3': {'final': 'fallback'}}})
            common.append_jsonl(out / 'run.jsonl', [{'event': 'page_retry'}, {'event': 'fallback_page_created'}, {'event': 'model_response_rejected'}])
            value = evaluate.job_metrics(out, 90)
        self.assertEqual((value['pages'], value['first_try'], value['rewrites'], value['fallbacks'], value['json_rejections']), (3, 2, 1, 1, 1))

    def test_report_mentions_switch(self):
        old = evaluate.total([self.metrics(6)])
        text = evaluate.report_markdown('a', old, 'qwen3.8:27b-teach-x', old, '先不要換。')
        self.assertIn('distilled_model: qwen3.8:27b-teach-x', text)


class UnitTests(unittest.TestCase):
    UNIT = {'document_id': 7, 'unit_code': 'M5-3', 'path': 'F:/x.pdf', 'grade': 5, 'semester': '上學期', 'subject': '數學',
            'title': '分數的加減', 'publisher': '南一'}

    def test_request_matches_contract(self):
        from workflow_v2.contracts import REQUEST, validate
        request = units.build_request(self.UNIT, '中難度', 12, 'qwen3.8:27b-q4_K_M')
        validate(REQUEST, request)
        self.assertFalse(request['online_cc0_images'] or request['include_worksheet'] or request['review_outline'])
        self.assertEqual(request['audience'], '國小學童')
        with self.assertRaises(ValueError):
            units.build_request(self.UNIT, '超難', 12, 'm')
        with self.assertRaises(ValueError):
            units.build_request(self.UNIT, '全部', 5, 'm')

    def test_unit_id_stable(self):
        self.assertEqual(units.unit_id(self.UNIT), units.unit_id(dict(self.UNIT)))
        self.assertNotEqual(units.unit_id(self.UNIT), units.unit_id(dict(self.UNIT, path='F:/y.pdf')))

    def test_plan_units_skips_held_out_finished_and_filters(self):
        pool = [dict(self.UNIT, path=f'F:/{i}.pdf', grade=4 + i % 3, subject=('數學', '國語')[i % 2]) for i in range(60)]
        done = {units.unit_id(pool[0]): {'finished': True}}
        chosen = collect.plan_units(pool, 100, done)
        keys = {units.unit_id(u) for u in chosen}
        self.assertNotIn(units.unit_id(pool[0]), keys)
        self.assertFalse(any(common.held_out(k) for k in keys))
        self.assertEqual(len(collect.plan_units(pool, 5, {})), 5)
        only = collect.plan_units(pool, 100, {}, grades={5}, subjects={'數學'})
        self.assertTrue(only and all(u['grade'] == 5 and u['subject'] == '數學' for u in only))
        held = evaluate.held_out_units(pool, 100)
        self.assertTrue(all(common.held_out(units.unit_id(u)) for u in held))
        self.assertFalse(keys & {units.unit_id(u) for u in held})

    def test_variant_spreads_choices(self):
        seen = {collect.variant(f'k{i}') for i in range(200)}
        self.assertEqual({d for d, _ in seen}, set(units.DIFFICULTIES))
        self.assertEqual({n for _, n in seen}, set(collect.SLIDE_COUNTS))


class AdoptTests(unittest.TestCase):
    def test_switch_on_and_off_keeps_other_lines(self):
        text = 'preferred_model: a\n# 說明\n# distilled_model: qwen3.8:27b-teach-run-YYYYMMDD-HHMM\nmodel_selection: fixed\n'
        on = adopt.switch(text, 'qwen3.8:27b-teach-x')
        self.assertIn('\ndistilled_model: qwen3.8:27b-teach-x\n', on)
        self.assertIn('# 說明', on)
        self.assertEqual(on.count('distilled_model'), 1)
        import yaml
        self.assertEqual(yaml.safe_load(on)['distilled_model'], 'qwen3.8:27b-teach-x')
        off = adopt.switch(on, '')
        self.assertIsNone(yaml.safe_load(off).get('distilled_model'))
        self.assertEqual(adopt.switch('a: 1\n', 'qwen3.8:27b-teach-y'), 'a: 1\ndistilled_model: qwen3.8:27b-teach-y\n')


class ModelPolicyTests(unittest.TestCase):
    def test_without_distilled_model_nothing_changes(self):
        config = {'preferred_model': 'qwen3.8:27b-q4_K_M'}
        self.assertEqual(model_policy.configured_model(config), 'qwen3.8:27b-q4_K_M')
        self.assertEqual(model_policy.model_for_images('qwen3.8:27b-q4_K_M', config), 'qwen3.8:27b-q4_K_M')
        self.assertEqual(model_policy.configured_model({'distilled_model': '  '}), model_policy.DEFAULT_MODEL)

    def test_distilled_model_for_text_base_for_images(self):
        config = {'preferred_model': 'qwen3.8:27b-q4_K_M', 'distilled_model': 'qwen3.8:27b-teach-r1'}
        self.assertEqual(model_policy.configured_model(config), 'qwen3.8:27b-teach-r1')
        self.assertEqual(model_policy.base_model(config), 'qwen3.8:27b-q4_K_M')
        self.assertEqual(model_policy.model_for_images('qwen3.8:27b-teach-r1', config), 'qwen3.8:27b-q4_K_M')
        self.assertEqual(model_policy.model_for_images('qwen3.8:27b-teach-r2', {'preferred_model': 'qwen3.8:27b-q4_K_M'}), 'qwen3.8:27b-q4_K_M')

    def test_bind_fixed_mode(self):
        config = {'model_selection': 'fixed', 'preferred_model': 'qwen3.8:27b-q4_K_M', 'distilled_model': 'qwen3.8:27b-teach-r1'}
        with mock.patch.object(model_policy, 'settings', return_value=config):
            value = model_policy.bind({'model': 'other'})
        self.assertEqual((value['model'], value['page_model']), ('qwen3.8:27b-teach-r1',) * 2)


class CaptureTests(unittest.TestCase):
    def call_capture(self, folder, record, images=None):
        data = {'message': {'content': '{"a":1}'}, 'done_reason': 'stop', 'prompt_eval_count': 5, 'eval_count': 3, 'model': 'm'}
        with mock.patch.dict(os.environ, {model.CAPTURE_ENV: folder}):
            model.capture(record, [{'role': 'user', 'content': 'x'}], {'type': 'object'}, data, True, 1, '', {'temperature': .18}, images)

    def test_off_by_default(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(model.CAPTURE_ENV, None)
            model.capture(Path(folder) / 'job' / 'calls' / 'page-01.json', [], {}, {}, True, 1, '', {})
            self.assertEqual(list(Path(folder).rglob('*.json')), [])

    def test_records_under_job_name(self):
        with tempfile.TemporaryDirectory() as folder:
            self.call_capture(folder, Path(folder) / 'jobs' / 'job-7' / 'calls' / 'page-01.json')
            files = list((Path(folder) / 'job-7').glob('page-01-1-*.json'))
            self.assertEqual(len(files), 1)
            row = json.loads(files[0].read_text(encoding='utf-8'))
            self.assertEqual((row['name'], row['content'], row['accepted']), ('page-01', '{"a":1}', True))
            self.assertTrue(row['job_folder'].endswith('job-7'))

    def test_image_calls_not_recorded(self):
        with tempfile.TemporaryDirectory() as folder:
            self.call_capture(folder, Path(folder) / 'jobs' / 'job-7' / 'calls' / 'page-01.json', images=['abc'])
            self.assertEqual(list((Path(folder)).rglob('page-01-*.json')), [])


if __name__ == '__main__':
    unittest.main()
