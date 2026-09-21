"""
Simplified, illustrative prior-authorization medical-necessity policies.

These are NOT real payer policy documents. They are deliberately simplified
approximations of how InterQual/MCG-style clinical criteria are structured,
written for a synthetic-data demo. Do not use for actual coverage decisions.

Each policy defines:
  - the procedure being requested (CPT) and typical diagnoses (ICD-10)
  - the criteria text handed to Jev as policy context (this is what the
    model reasons against — it never sees a ground-truth label)
  - a `baseline_tier_weights` distribution used only by the synthetic data
    generator to decide how often to sample "clearly meets", "borderline",
    or "clearly does not meet" scenarios for this procedure category, which
    mirrors real-world approval-rate differences across service types.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    category_id: str
    procedure_name: str
    cpt_code: str
    diagnoses: tuple[tuple[str, str], ...]  # (icd10_code, description)
    criteria_text: str
    # relative sampling weights for (meets, borderline, does_not_meet)
    baseline_tier_weights: tuple[float, float, float]


POLICIES: list[Policy] = [
    Policy(
        category_id="lumbar_mri",
        procedure_name="MRI Lumbar Spine without Contrast",
        cpt_code="72148",
        diagnoses=(
            ("M54.50", "Low back pain, unspecified"),
            ("M51.26", "Other intervertebral disc displacement, lumbar region"),
        ),
        criteria_text=(
            "Advanced imaging (MRI) of the lumbar spine is medically necessary if EITHER: "
            "(a) the member has completed at least 6 weeks of conservative therapy "
            "(physical therapy and/or NSAIDs) without significant improvement, OR "
            "(b) one or more red-flag findings are documented: progressive neurological "
            "deficit, suspected cauda equina syndrome, suspected malignancy or infection, "
            "or significant trauma with fracture risk. Imaging requested before 6 weeks of "
            "conservative therapy, with no red-flag findings, does not meet criteria."
        ),
        baseline_tier_weights=(0.35, 0.30, 0.35),
    ),
    Policy(
        category_id="tka",
        procedure_name="Total Knee Arthroplasty",
        cpt_code="27447",
        diagnoses=(("M17.11", "Unilateral primary osteoarthritis, right knee"),),
        criteria_text=(
            "Total knee arthroplasty is medically necessary if ALL are documented: "
            "(a) at least 3 months of conservative treatment (NSAIDs, physical therapy, "
            "and/or intra-articular injections) with inadequate relief, "
            "(b) imaging confirming Kellgren-Lawrence grade 3 or 4 osteoarthritis, and "
            "(c) functional limitation affecting activities of daily living. "
            "Absence of imaging confirmation or conservative treatment history does not "
            "meet criteria regardless of reported pain severity."
        ),
        baseline_tier_weights=(0.30, 0.35, 0.35),
    ),
    Policy(
        category_id="biologic_ra",
        procedure_name="Adalimumab Therapy (Biologic DMARD)",
        cpt_code="J0135",
        diagnoses=(("M06.9", "Rheumatoid arthritis, unspecified"),),
        criteria_text=(
            "Biologic DMARD therapy is medically necessary if ALL are documented: "
            "(a) inadequate response to at least one conventional DMARD (e.g. methotrexate) "
            "for a minimum of 3 months at an adequate dose, and "
            "(b) objective evidence of active disease (elevated CRP/ESR or documented "
            "swollen/tender joint count). Requests without a documented conventional DMARD "
            "trial do not meet criteria."
        ),
        baseline_tier_weights=(0.30, 0.25, 0.45),
    ),
    Policy(
        category_id="dme_wheelchair",
        procedure_name="Power Wheelchair",
        cpt_code="K0823",
        diagnoses=(("G82.20", "Paraplegia, unspecified"),),
        criteria_text=(
            "A power wheelchair is medically necessary if ALL are documented: "
            "(a) a face-to-face mobility evaluation within the last 6 months, "
            "(b) the member cannot accomplish activities of daily living within the home "
            "using a cane, walker, or manual wheelchair, and "
            "(c) the home layout can accommodate the device. Missing face-to-face "
            "evaluation or absence of in-home functional limitation does not meet criteria."
        ),
        baseline_tier_weights=(0.40, 0.25, 0.35),
    ),
    Policy(
        category_id="bariatric_surgery",
        procedure_name="Laparoscopic Gastric Bypass",
        cpt_code="43644",
        diagnoses=(("E66.01", "Morbid (severe) obesity due to excess calories"),),
        criteria_text=(
            "Bariatric surgery is medically necessary if ALL are documented: "
            "(a) BMI of 40 or greater, OR BMI of 35-39.9 with at least one obesity-related "
            "comorbidity (e.g. type 2 diabetes, hypertension, obstructive sleep apnea), "
            "(b) at least 6 months of physician-supervised weight management with "
            "insufficient results, and (c) a psychological evaluation clearing the member "
            "for surgery. Any missing element does not meet criteria."
        ),
        baseline_tier_weights=(0.25, 0.30, 0.45),
    ),
    Policy(
        category_id="genetic_brca",
        procedure_name="BRCA1/BRCA2 Genetic Testing",
        cpt_code="81162",
        diagnoses=(("Z15.01", "Genetic susceptibility to malignant neoplasm of breast"),),
        criteria_text=(
            "BRCA1/2 genetic testing is medically necessary if the member meets NCCN "
            "criteria: a personal history of breast or ovarian cancer at a qualifying age, "
            "OR a first/second-degree relative with breast or ovarian cancer at a qualifying "
            "age, OR a known familial BRCA mutation. Testing requested for general population "
            "screening with no qualifying personal or family history does not meet criteria."
        ),
        baseline_tier_weights=(0.35, 0.20, 0.45),
    ),
    Policy(
        category_id="screening_colonoscopy",
        procedure_name="Screening Colonoscopy",
        cpt_code="45378",
        diagnoses=(("Z12.11", "Encounter for screening for malignant neoplasm of colon"),),
        criteria_text=(
            "Screening colonoscopy is medically necessary for average-risk members aged "
            "45-75 per USPSTF guidelines, with no prior authorization criteria beyond age "
            "and eligibility verification. This is a low-friction, typically auto-approved "
            "screening benefit."
        ),
        baseline_tier_weights=(0.85, 0.10, 0.05),
    ),
]

POLICIES_BY_ID: dict[str, Policy] = {p.category_id: p for p in POLICIES}
