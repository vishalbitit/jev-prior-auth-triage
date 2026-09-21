"""
Generate synthetic, PHI-free prior-authorization requests.

No real patient data is used anywhere. Member IDs, ages, and clinical notes
are synthetically generated. Clinical note templates are written by hand to
plausibly reflect how documentation would (or would not) satisfy the
simplified policies in policy/policies.py -- they are illustrative, not
drawn from or intended to resemble any real patient record.

Each request is labeled with synthetic ground truth (difficulty tier,
whether it meets criteria, and a "true" urgency) that is used ONLY for our
own evaluation afterwards -- it is never sent to Jev. Jev only ever sees
`state` (the clinical documentation + policy) and has to reason it out,
exactly like a real reviewer would.

A `submitter_claimed_urgency` field is included separately, and is
deliberately allowed to disagree with the ground-truth urgency sometimes --
providers routinely mark requests "urgent" to jump the queue, and part of
what we want to see is whether Jev's independent urgency score tracks the
clinical content rather than just parroting the submitter's own label.
"""

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from policy.policies import POLICIES, Policy

random.seed(42)  # reproducible synthetic dataset

N_REQUESTS = 150
OUTPUT_PATH = Path(__file__).parent / "pa_requests.jsonl"

SPECIALTIES = {
    "lumbar_mri": ["Family Medicine", "Orthopedic Surgery", "Physical Medicine & Rehab"],
    "tka": ["Orthopedic Surgery"],
    "biologic_ra": ["Rheumatology"],
    "dme_wheelchair": ["Physical Medicine & Rehab", "Neurology"],
    "bariatric_surgery": ["Bariatric Surgery", "General Surgery"],
    "genetic_brca": ["Medical Genetics", "Oncology", "OB/GYN"],
    "screening_colonoscopy": ["Gastroenterology", "Family Medicine"],
}

AGE_RANGES = {
    "lumbar_mri": (24, 80),
    "tka": (50, 85),
    "biologic_ra": (22, 75),
    "dme_wheelchair": (18, 85),
    "bariatric_surgery": (22, 65),
    "genetic_brca": (25, 65),
    "screening_colonoscopy": (45, 75),
}

PLAN_TYPES = ["HMO", "PPO", "EPO"]

TIERS = ["meets_criteria", "borderline", "does_not_meet_criteria"]


@dataclass
class PARequest:
    request_id: str
    member_id: str
    member_age: int
    plan_type: str
    ordering_provider_specialty: str
    category_id: str
    procedure_name: str
    cpt_code: str
    diagnosis_code: str
    diagnosis_description: str
    clinical_documentation: str
    submitter_claimed_urgency: str
    applicable_policy_criteria: str
    # synthetic ground truth -- used only for OUR evaluation, never sent to Jev
    _gt_tier: str
    _gt_meets_criteria: bool
    _gt_urgency: str


def _clinical_note(policy: Policy, tier: str) -> tuple[str, str]:
    """Return (clinical_documentation, ground_truth_urgency) for a given tier."""
    cid = policy.category_id

    if cid == "lumbar_mri":
        if tier == "meets_criteria":
            variants = [
                (
                    "Member reports 8 weeks of low back pain, completed structured physical "
                    "therapy (12 sessions) and NSAID trial with minimal improvement. No red "
                    "flag symptoms.",
                    "routine",
                ),
                (
                    "New progressive right lower extremity weakness (4/5 dorsiflexion), "
                    "saddle numbness reported, concern for cauda equina syndrome. Urgent "
                    "evaluation requested.",
                    "emergent",
                ),
            ]
        elif tier == "borderline":
            variants = [
                (
                    "Member reports 4 weeks of low back pain, self-directed home exercises, "
                    "no formal PT referral yet. Pain described as 'not improving much.'",
                    "urgent",
                ),
                (
                    "6 weeks of intermittent PT attendance (5 of 12 scheduled sessions "
                    "completed), inconsistent NSAID use documented. Some improvement noted "
                    "but pain persists.",
                    "routine",
                ),
            ]
        else:
            variants = [
                (
                    "Member reports 10 days of low back pain, no conservative therapy "
                    "attempted yet, no neurological symptoms, no red flags.",
                    "routine",
                ),
                (
                    "Chronic low back pain, no documented trial of PT or NSAIDs in the "
                    "chart, requesting imaging for 'peace of mind.'",
                    "routine",
                ),
            ]
        note, urgency = random.choice(variants)
        return note, urgency

    if cid == "tka":
        if tier == "meets_criteria":
            note = (
                "5 months of NSAIDs, PT (16 sessions), and two intra-articular corticosteroid "
                "injections with inadequate relief. Radiographs confirm Kellgren-Lawrence "
                "grade 4 changes. Member unable to climb stairs or walk more than one block."
            )
        elif tier == "borderline":
            note = (
                "2 months of NSAIDs and home exercise program, radiographs show "
                "Kellgren-Lawrence grade 3 changes. Functional limitation reported but not "
                "quantified. No injection trial documented."
            )
        else:
            note = (
                "Member reports knee pain for several months. No radiographs on file, no "
                "conservative treatment history documented in the chart."
            )
        return note, "routine"

    if cid == "biologic_ra":
        if tier == "meets_criteria":
            note = (
                "4-month trial of methotrexate 20mg weekly with inadequate response. CRP "
                "elevated at 3.2 mg/dL, 8 tender/swollen joints on exam."
            )
        elif tier == "borderline":
            note = (
                "6-week methotrexate trial discontinued due to GI intolerance, switched to "
                "low-dose alternative. Labs pending, exam notes 'some joint tenderness.'"
            )
        else:
            note = (
                "Diagnosis of rheumatoid arthritis noted in chart. No conventional DMARD "
                "trial documented. Requesting biologic as first-line therapy."
            )
        return note, "routine"

    if cid == "dme_wheelchair":
        if tier == "meets_criteria":
            note = (
                "Face-to-face mobility evaluation completed 3 weeks ago. Member unable to "
                "self-propel manual wheelchair due to bilateral upper extremity weakness. "
                "Home assessment confirms adequate doorway clearance."
            )
        elif tier == "borderline":
            note = (
                "Mobility evaluation completed 5 months ago (outside typical currency "
                "window). Member reports difficulty with manual wheelchair but no formal "
                "in-home functional assessment on file."
            )
        else:
            note = (
                "Request submitted by DME supplier with prescription only, no face-to-face "
                "evaluation note in chart, no documentation of failed trial with manual "
                "wheelchair."
            )
        return note, "routine"

    if cid == "bariatric_surgery":
        if tier == "meets_criteria":
            note = (
                "BMI 43.2. Completed 7-month physician-supervised weight management program "
                "with dietitian visits documented monthly. Psychological evaluation completed, "
                "member cleared for surgery. Comorbid type 2 diabetes and hypertension."
            )
        elif tier == "borderline":
            note = (
                "BMI 36.8 with hypertension. 4 months of weight management program "
                "documented, program not physician-supervised (self-directed app-based "
                "program). Psych evaluation scheduled but not yet completed."
            )
        else:
            note = (
                "BMI 34.1, no documented comorbidity, no weight management program on file, "
                "no psychological evaluation."
            )
        return note, "routine"

    if cid == "genetic_brca":
        if tier == "meets_criteria":
            note = (
                "Member's mother diagnosed with ovarian cancer at age 46; maternal aunt with "
                "breast cancer at age 42. Meets NCCN family history criteria."
            )
        elif tier == "borderline":
            note = (
                "Member reports 'a relative' with breast cancer, relationship and age at "
                "diagnosis not specified in chart. Personal history negative."
            )
        else:
            note = (
                "Member requesting testing for general risk awareness. No personal or "
                "family history of breast or ovarian cancer documented."
            )
        return note, "routine"

    if cid == "screening_colonoscopy":
        if tier == "meets_criteria":
            note = (
                "Member age-eligible, average risk, no prior colonoscopy on file, due for "
                "routine screening per USPSTF guidelines."
            )
        elif tier == "borderline":
            note = (
                "Member had a screening colonoscopy 4 years ago (routine interval is "
                "10 years for average risk); requesting repeat without a documented "
                "clinical indication for early repeat."
            )
        else:
            note = (
                "Member is 38 years old, average risk, no family history -- outside the "
                "standard screening age range."
            )
        return note, "routine"

    raise ValueError(f"unknown category {cid}")


def _sample_tier(policy: Policy) -> str:
    return random.choices(TIERS, weights=policy.baseline_tier_weights, k=1)[0]


def _claimed_urgency(gt_urgency: str) -> str:
    # Providers sometimes over-claim urgency; occasionally under-claim too.
    if random.random() < 0.7:
        return gt_urgency if gt_urgency != "emergent" else "urgent"  # rarely self-labeled "emergent"
    return random.choices(["routine", "urgent", "stat"], weights=[0.5, 0.35, 0.15], k=1)[0]


def generate() -> list[PARequest]:
    requests = []
    for i in range(1, N_REQUESTS + 1):
        policy = random.choice(POLICIES)
        tier = _sample_tier(policy)
        note, gt_urgency = _clinical_note(policy, tier)
        diagnosis_code, diagnosis_desc = random.choice(policy.diagnoses)
        lo, hi = AGE_RANGES[policy.category_id]

        req = PARequest(
            request_id=f"PA-{i:05d}",
            member_id=f"SYN-{random.randint(100000, 999999)}",
            member_age=random.randint(lo, hi),
            plan_type=random.choice(PLAN_TYPES),
            ordering_provider_specialty=random.choice(SPECIALTIES[policy.category_id]),
            category_id=policy.category_id,
            procedure_name=policy.procedure_name,
            cpt_code=policy.cpt_code,
            diagnosis_code=diagnosis_code,
            diagnosis_description=diagnosis_desc,
            clinical_documentation=note,
            submitter_claimed_urgency=_claimed_urgency(gt_urgency),
            applicable_policy_criteria=policy.criteria_text,
            _gt_tier=tier,
            _gt_meets_criteria=(tier == "meets_criteria"),
            _gt_urgency=gt_urgency,
        )
        requests.append(req)
    return requests


def main() -> None:
    requests = generate()
    with OUTPUT_PATH.open("w") as f:
        for req in requests:
            f.write(json.dumps(asdict(req)) + "\n")
    print(f"Wrote {len(requests)} synthetic PA requests to {OUTPUT_PATH}")

    tier_counts: dict[str, int] = {}
    for req in requests:
        tier_counts[req._gt_tier] = tier_counts.get(req._gt_tier, 0) + 1
    print("Tier distribution:", tier_counts)


if __name__ == "__main__":
    main()
