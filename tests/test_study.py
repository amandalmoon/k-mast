from datetime import timedelta

from kmast.core.contracts import Forecast, validate_optimizer_inputs
from kmast.core.study import StudyContract

from .test_contracts import units


def test_complete_settings_still_cannot_pass_economics():
    study = StudyContract(
        baseline_policy_id="PBASE_FIXED",
        capital_scenarios=(1000,),
        valuation_calendar="SYNTHETIC",
        common_horizon=timedelta(days=1),
        fixed_cost_schedule_id="SYNTHETIC",
        fold_manifest_id="SYNTHETIC",
        label_maturity_policy_id="SYNTHETIC",
        trial_registry_id="SYNTHETIC",
        dependence_test_method="SYNTHETIC",
        confidence_level="0.95",
        minimum_economic_improvement=1,
        stress_loss_limit=1,
        expected_shortfall_limit=1,
        capacity_acceptance_policy="SYNTHETIC",
        freeze_approved_by="SYNTHETIC_TEST_ONLY",
    )
    assert study.missing_economic_fields() == ()
    assert study.g3_status() == "NOT_IMPLEMENTED"
    assert study.live_approved is False and study.optimizer_approved is False


def test_matching_optimizer_input_contract_is_accepted():
    common = units()
    validate_optimizer_inputs(
        (Forecast(units=common, expected_return="0.01", uncertainty="0.02"),), common
    )
