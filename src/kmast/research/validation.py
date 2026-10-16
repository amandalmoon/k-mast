from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from kmast.core.base import Contract, Identifier
from kmast.core.study import StudyContract
from kmast.data.normalization import content_hash


class CandidateFreeze(Contract):
    candidate: Literal["AlphaA-candidate-v1"] = "AlphaA-candidate-v1"
    config_hash: Identifier
    source_hash: Identifier
    data_manifest_hash: Identifier
    frozen_at: AwareDatetime
    study: StudyContract
    candidate_search_count: int = Field(ge=1)
    lineage: tuple[Identifier, ...] = Field(min_length=1)
    risk_policy_ref: Identifier | None = None
    execution_scenarios_ref: Identifier | None = None
    uncertainty_method_ref: Identifier | None = None

    @property
    def identity(self) -> str:
        return content_hash(self.model_dump(mode="json"))

    def require_oos(
        self, expected_identity: str, opened_at: AwareDatetime, data_ready: bool
    ) -> None:
        if (
            self.identity != expected_identity
            or self.frozen_at >= opened_at
            or self.study.missing_economic_fields()
            or not data_ready
            or not self.risk_policy_ref
            or not self.execution_scenarios_ref
            or not self.uncertainty_method_ref
        ):
            raise PermissionError("G0/G1 freeze incomplete or changed; OOS access blocked")


class MatureLabel(Contract):
    feature_at: AwareDatetime
    label_known_at: AwareDatetime
    training_cutoff: AwareDatetime

    @model_validator(mode="after")
    def causal(self) -> "MatureLabel":
        if not self.feature_at < self.label_known_at <= self.training_cutoff:
            raise ValueError("future or immature label forbidden")
        return self


def sample_gate(independent_clusters: int, frozen_minimum: int | None) -> str:
    if frozen_minimum is None or frozen_minimum < 1 or independent_clusters < frozen_minimum:
        return "HOLD_INSUFFICIENT_EVIDENCE"
    return "HOLD_CONFIRMATORY_ECONOMICS_REQUIRED"
