"""
Prior-authorization triage pipeline powered by Jev (TypeSafe AI System-1 model).

For each synthetic PA request, we ask Jev exactly three typed questions in a
SINGLE call:
  1. Noul  -- does documentation satisfy medical-necessity criteria?
  2. Choice -- route to auto_approve / pend_clinical_review / peer_to_peer_required
  3. Score  -- how urgent is this, based on clinical content (not the
               submitter's self-reported urgency)?

Jev never sees our synthetic ground truth -- only `state` (the request +
clinical documentation + policy text), exactly like a real reviewer would
see it. Ground truth is attached to the audit record afterwards, purely for
our own evaluation in the analysis step.

IMPORTANT: This is a proof of concept over synthetic data. It is NOT
validated for, and must not be used for, real coverage or clinical
decisions. In a real deployment, `pend_clinical_review` and
`peer_to_peer_required` route to a human; `auto_approve` would still be
subject to normal audit sampling. Jev is never the final decision-maker on
a denial in this design.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

load_dotenv()

REQUESTS_PATH = Path(__file__).parent.parent / "data" / "pa_requests.jsonl"
AUDIT_LOG_PATH = Path(__file__).parent.parent / "data" / "audit_log.jsonl"

ROUTING_CRITERIA = {
    "auto_approve": (
        "Documentation clearly satisfies all elements of the applicable policy "
        "criteria with no meaningful ambiguity."
    ),
    "pend_clinical_review": (
        "Documentation is incomplete, ambiguous, or only partially satisfies "
        "criteria -- a clinical reviewer needs to request more information or "
        "make a judgment call."
    ),
    "peer_to_peer_required": (
        "Documentation clearly does not satisfy policy criteria as submitted, "
        "or this is a high-risk/high-cost procedure where a peer-to-peer "
        "discussion between the ordering provider and medical director is "
        "warranted before any denial determination."
    ),
}

URGENCY_CRITERIA = [
    "routine - standard review timeframe is clinically appropriate",
    "urgent - expedited review needed within days",
    "emergent - immediate/same-day review needed",
]


@dataclass
class TriageResult:
    request_id: str
    latency_ms: float
    model: str
    meets_medical_necessity: float
    routing_decision: str
    routing_probabilities: dict
    routing_confidence: float
    urgency_score: float
    urgency_label: str
    urgency_probabilities: dict
    urgency_confidence: float
    input_tokens: int
    output_tokens: int
    error: str | None = None


def build_state(req: dict) -> dict:
    """Everything Jev is allowed to see -- no ground truth fields included."""
    return {
        "member": {
            "age": req["member_age"],
            "plan_type": req["plan_type"],
        },
        "request": {
            "procedure_name": req["procedure_name"],
            "cpt_code": req["cpt_code"],
            "diagnosis_code": req["diagnosis_code"],
            "diagnosis_description": req["diagnosis_description"],
            "ordering_provider_specialty": req["ordering_provider_specialty"],
            "submitter_claimed_urgency": req["submitter_claimed_urgency"],
        },
        "clinical_documentation": req["clinical_documentation"],
        "applicable_policy_criteria": req["applicable_policy_criteria"],
    }


def triage_one(client: TypeSafeClient, req: dict) -> TriageResult:
    state = build_state(req)

    start = time.perf_counter()
    response = client.system_one(
        state=state,
        model="jev-latest",
        questions={
            "meets_medical_necessity": Noul(
                instructions=(
                    "Does the clinical documentation satisfy the applicable "
                    "policy criteria for medical necessity?"
                ),
            ),
            "routing_decision": Choice(
                instructions=(
                    "How should this prior-authorization request be routed "
                    "for handling?"
                ),
                criteria=ROUTING_CRITERIA,
            ),
            "urgency": Score(
                instructions=(
                    "Based only on the clinical documentation content -- not "
                    "the submitter's self-reported urgency label -- how "
                    "urgent is this request?"
                ),
                criteria=URGENCY_CRITERIA,
            ),
        },
    )
    latency_ms = (time.perf_counter() - start) * 1000

    routing = response.choices["routing_decision"]
    urgency = response.scores["urgency"]
    necessity = response.nouls["meets_medical_necessity"]

    # Use the model's own legend rather than re-deriving from our criteria
    # list, and clamp in case the raw score rounds outside the valid range.
    # Note: this SDK version keys ScoreAnswer.legend/.probabilities by int,
    # not str -- verified against the installed typesafe_sdk source.
    nearest_index = min(max(round(urgency.score), 0), len(URGENCY_CRITERIA) - 1)
    urgency_label = urgency.legend.get(nearest_index, URGENCY_CRITERIA[nearest_index]).split(" - ")[0]

    return TriageResult(
        request_id=req["request_id"],
        latency_ms=round(latency_ms, 1),
        model=response.model,
        meets_medical_necessity=necessity.noul,
        routing_decision=routing.choice,
        routing_probabilities=routing.probabilities,
        routing_confidence=routing.confidence,
        urgency_score=urgency.score,
        urgency_label=urgency_label,
        urgency_probabilities=urgency.probabilities,
        urgency_confidence=urgency.confidence,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


def main() -> None:
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit(
            "TYPESAFE_API_KEY not set. Copy .env.example to .env and add your key "
            "from https://console.typesafe.ai/"
        )

    requests = [json.loads(line) for line in REQUESTS_PATH.read_text().splitlines()]
    print(f"Loaded {len(requests)} synthetic PA requests")

    results = []
    errors = 0
    with TypeSafeClient() as client:
        for i, req in enumerate(requests, 1):
            try:
                result = triage_one(client, req)
            except Exception as e:  # noqa: BLE001 -- log and keep going on batch runs
                errors += 1
                result = TriageResult(
                    request_id=req["request_id"],
                    latency_ms=0.0,
                    model="",
                    meets_medical_necessity=0.0,
                    routing_decision="",
                    routing_probabilities={},
                    routing_confidence=0.0,
                    urgency_score=0.0,
                    urgency_label="",
                    urgency_probabilities={},
                    urgency_confidence=0.0,
                    input_tokens=0,
                    output_tokens=0,
                    error=str(e),
                )
            results.append((req, result))
            if i % 25 == 0 or i == len(requests):
                print(f"  {i}/{len(requests)} triaged ({errors} errors so far)")

    with AUDIT_LOG_PATH.open("w") as f:
        for req, result in results:
            record = {
                "request_id": req["request_id"],
                "category_id": req["category_id"],
                "cpt_code": req["cpt_code"],
                "submitter_claimed_urgency": req["submitter_claimed_urgency"],
                **result.__dict__,
                # synthetic ground truth, kept ONLY for our own evaluation
                "ground_truth_tier": req["_gt_tier"],
                "ground_truth_meets_criteria": req["_gt_meets_criteria"],
                "ground_truth_urgency": req["_gt_urgency"],
            }
            f.write(json.dumps(record) + "\n")

    print(f"\nWrote audit log with {len(results)} records to {AUDIT_LOG_PATH}")
    if errors:
        print(f"WARNING: {errors} requests failed -- see 'error' field in audit log")


if __name__ == "__main__":
    main()
