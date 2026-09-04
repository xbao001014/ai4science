"""Additional quality-related pytest modules in the existing temporary DB harness."""
import run_regression

run_regression.TESTS=['test_quality_v2','test_p0_quality','test_triple_models','test_triple_method_role_hint',
    'test_entity_normalize','test_dataset_access','test_study_prompts','test_study_policy','test_fulltext_reconcile']

if __name__=='__main__':run_regression.main()
