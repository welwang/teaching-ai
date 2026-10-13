import json
import tempfile
import unittest
from unittest.mock import patch

from workflow_v2 import model_policy
from workflow_v2.model import context_size
from workflow_v2.store import Store


class ModelPolicyTest(unittest.TestCase):
    def test_fixed_model_overrides_both_caller_models_without_mutation(self):
        original={'model':'strata:old','page_model':'gemma4:12b','unit':'測試'}
        with patch.object(model_policy,'settings',return_value={
                'model_selection':'fixed','preferred_model':model_policy.DEFAULT_MODEL}):
            bound=model_policy.bind(original)
        self.assertEqual(bound['model'],model_policy.DEFAULT_MODEL)
        self.assertEqual(bound['page_model'],model_policy.DEFAULT_MODEL)
        self.assertEqual(original['model'],'strata:old')
        self.assertEqual(bound['unit'],original['unit'])

    def test_job_submission_needs_no_user_model_choice(self):
        request=dict(schema_version=1,grade=6,semester='上學期',subject='數學',
            unit='比與比值',publisher='測試',difficulty='低難度',slide_count=8,
            source_path='test.md',locale='zh-TW')
        with tempfile.TemporaryDirectory() as folder, patch.object(model_policy,'settings',
                return_value={'model_selection':'fixed','preferred_model':model_policy.DEFAULT_MODEL}):
            store=Store(folder)
            row=store.get(store.submit(request))
            saved=json.loads(row['request'])
        self.assertEqual(saved['model'],model_policy.DEFAULT_MODEL)
        self.assertEqual(saved['page_model'],model_policy.DEFAULT_MODEL)
        self.assertNotIn('model',request)

    def test_dense_context_stays_fixed_across_prompt_sizes(self):
        with patch.object(model_policy,'settings',return_value={'generation_context':32768}):
            self.assertEqual(context_size(model_policy.DEFAULT_MODEL,'短文'),32768)
            self.assertEqual(context_size(model_policy.DEFAULT_MODEL,'長文'*9000),32768)

    def test_unconfigured_context_keeps_conservative_default(self):
        with patch.object(model_policy,'settings',return_value={}):
            self.assertEqual(model_policy.configured_context(),8192)

    def test_context_rejects_oversize_or_untyped_settings(self):
        for value in (1000000,65536,'32768',True):
            with self.subTest(value=value), patch.object(model_policy,'settings',
                    return_value={'generation_context':value}):
                with self.assertRaises(ValueError):model_policy.configured_context()

    def test_unfixed_adapter_preserves_explicit_requests(self):
        with patch.object(model_policy,'settings',return_value={}):
            original={'model':'example:local','page_model':'example:local'}
            self.assertEqual(model_policy.bind(original),original)

    def test_text_only_cover_stays_valid_after_normalization(self):
        from test_design_system import sample_deck
        from workflow_v2.contracts import slide_schema,validate
        from workflow_v2.pipeline import normalize_slide
        page=sample_deck()['slides'][0]
        page.update(student_task='說出生活中的角',visual_model={'type':'none'})
        page=normalize_slide(page,{'student_task':'說出生活中的角'})
        self.assertNotIn('visual_model',page)
        validate(slide_schema({1},'Cover',strict=True),page)


if __name__=='__main__':unittest.main()
