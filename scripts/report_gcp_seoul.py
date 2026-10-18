"""Deterministic offline GCP price scenarios; no cloud SDK, credentials or network."""

import argparse
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "artifacts/gcp-seoul"


def calculate():
    rates = json.loads((ROOT / "rates.json").read_bytes())

    def rate(key):
        return Decimal(rates[key])

    scenarios = []
    for machine in ("e2-small", "e2-medium"):
        for label, hours in (("24x7", 730), ("22_sessions_x_8h", 176)):
            for gib in (20, 30):
                for network in ("ephemeral_ipv4", "private_vm_nat"):
                    vm = rate(machine.replace("-", "_") + "_hour") * hours
                    disk = rate("pd_balanced_gib_month") * gib
                    ip_hours = hours if network == "ephemeral_ipv4" else 730
                    ip = rate("external_ipv4_in_use_hour") * ip_hours
                    nat = Decimal(0)
                    if network == "private_vm_nat":
                        nat = rate("nat_vm_hour") * hours + rate("nat_gib_both_directions") * 11
                    snapshot = rate("snapshot_standard_gib_month") * 5
                    egress = rate("premium_egress_korea_gib")  # 1 GiB assumed outbound
                    # Two versions, one location; 1,000 accesses; 1 GiB logs; 10 MiB metrics.
                    shared_gross = (
                        rate("secret_version_location_month") * 2
                        + rate("secret_access_per_10000") / 10
                        + rate("logging_gib")
                        + rate("custom_monitoring_mib") * 10
                    )
                    subtotal = vm + disk + ip + nat + snapshot + egress
                    scenarios.append(
                        dict(
                            machine=machine,
                            schedule=label,
                            vm_hours=hours,
                            disk_gib=gib,
                            network=network,
                            components_usd={
                                k: str(v)
                                for k, v in dict(
                                    vm=vm,
                                    disk=disk,
                                    ip=ip,
                                    nat_gateway_processing=nat,
                                    snapshot=snapshot,
                                    internet_egress=egress,
                                    shared_services_without_free_allowance=shared_gross,
                                ).items()
                            },
                            monthly_if_shared_free_allowances_available_usd=str(subtotal),
                            monthly_if_shared_free_allowances_exhausted_usd=str(
                                subtotal + shared_gross
                            ),
                            trial_cash_if_eligible_credit_covers_entire_usage_usd="0",
                            actual_cash_usd=None,
                            total_cost_of_ownership_usd=None,
                        )
                    )
    return dict(
        region="asia-northeast3",
        currency="USD",
        pricing_date_kst="2026-10-18",
        basis="730h average month; 176h is a planning assumption, not collection approval",
        assumptions=dict(
            inbound_gib=10,
            outbound_to_korea_gib=1,
            retained_snapshot_gib_month=5,
            secret_versions_one_location=2,
            secret_accesses=1000,
            logs_gib=1,
            custom_metrics_mib=10,
            nat_ip_retained_hours=730,
            account_free_allowance_availability="UNKNOWN",
            actual_trial_eligibility_and_remaining_credit="UNKNOWN",
        ),
        unknown_costs=[
            "taxes_and_billing_currency_fx",
            "operator_patch_recovery_hours_and_wage",
            "actual_traffic_snapshot_growth_log_metric_volume",
            "optional_paid_support_and_external_notification_delivery",
            "account_discounts_and_other_workload_allowance_consumption",
            "unplanned_rebuild_or_incident_usage",
        ],
        scenarios=scenarios,
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    raw = (json.dumps(calculate(), indent=2) + "\n").encode()
    target = ROOT / "cost-scenarios.json"
    if args.check:
        assert target.read_bytes() == raw
        print("GCP Seoul offline cost arithmetic PASS (conditional estimates, not billing)")
    else:
        target.write_bytes(raw)


if __name__ == "__main__":
    main()
