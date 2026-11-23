"""The plain-language summary of one screening: the same words everywhere the patient sees their result.

Pure: it reads only the screening's stored fields (no database queries), so other code can reuse it.
Wording rules: short, calm, never "you have" (say "possible signs of" or "the screening flagged"), and always
a screening, not a diagnosis. A result from a source the model was not evaluated on (phone + 20D, or unknown) is
never presented as reliable.
"""
from typing import Any

from app.modules.model_card.router import LIMITATIONS
from app.modules.screenings.models import ImageSource, Screening
from app.modules.screenings.schemas import (PatientSummary, SummaryFinding, SummaryNextStep, SummaryQuality)
from app.modules.screenings.service import MIN_SHARPNESS, MIN_SHARPNESS_DISC

NEAR = 0.10  # a probability this close to its threshold is "borderline" (same band as the web app's NEAR_NOTCH)
URGENT_CARE = ("Whatever this result says, get urgent medical care for sudden loss of vision, flashes of light, "
               "a curtain or shadow over your vision, or eye pain.")
NOT_A_DIAGNOSIS = "A screening is not a diagnosis."
PHONE_HEADLINE = ("This phone photo was read by a model that has not been tested on phone photos, "
                  "so this is not a reliable result.")
UNKNOWN_HEADLINE = ("We don't know where this photo came from, and the model has only been tested on photos "
                    "from eye clinics, so this is not a reliable result.")
EYE_EXAM = ("Book an eye examination with an eye doctor (ophthalmologist) to check this finding. "
            f"{NOT_A_DIAGNOSIS}")
CLINIC_PHOTO = ("Get a fundus photo taken at an eye clinic, or book an eye examination with an eye doctor "
                f"(ophthalmologist). {NOT_A_DIAGNOSIS}")
ROUTINE = ("Keep up regular eye check-ups. People with diabetes are usually advised to have a yearly eye exam. "
           f"{NOT_A_DIAGNOSIS}")
CONSIDER = ("One score was close to the cut-off, so consider an eye examination to be sure. "
            f"{NOT_A_DIAGNOSIS}")


def _source(screening: Screening) -> str:
    value = getattr(screening, "image_source", None) or ImageSource.unknown
    return getattr(value, "value", value)


def _quality(meta: dict[str, Any] | None) -> SummaryQuality:
    """The photo already passed the upload gate, so this explains it rather than judging it again."""
    sharp = (meta or {}).get("sharpness")
    if sharp is None:
        return SummaryQuality(ok=None, label="Quality not recorded", detail="This photo's sharpness was not recorded.")
    minimum = MIN_SHARPNESS if sharp >= MIN_SHARPNESS else MIN_SHARPNESS_DISC
    return SummaryQuality(ok=True, label="Good enough to check",
                          detail=f"The photo was sharp enough ({sharp:.2f}; at least {minimum:.2f} is needed).")


def _plain_finding(f: dict[str, Any], validated: bool) -> SummaryFinding:
    name = str(f["disease"]).lower()
    flagged = bool(f["positive"])
    borderline = abs(float(f["probability"]) - float(f["threshold"])) <= NEAR
    if validated:
        plain = (f"Possible signs of {name} were found." if flagged
                 else f"No signs of {name} were found by the screening.")
    else:
        plain = (f"The model flagged possible signs of {name}, but this reading is experimental." if flagged
                 else f"The model did not flag {name}, but this reading is experimental and does not rule it out.")
    return SummaryFinding(code=str(f["code"]), disease=str(f["disease"]), flagged=flagged, plain=plain,
                          borderline=borderline)


def _names(findings: list[SummaryFinding]) -> str:
    names = [f.disease.lower() for f in findings]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def patient_summary(screening: Screening) -> PatientSummary:
    source = _source(screening)
    validated = source == ImageSource.clinic_fundus.value
    result = screening.result
    limits = [*LIMITATIONS, NOT_A_DIAGNOSIS]

    if not screening.image_filename:
        return PatientSummary(
            state="no_photo", validated_source=validated, headline="No photo has been added yet.",
            next_step=SummaryNextStep(urgency="none", text="Add a photo of the back of your eye to start."),
            urgent_care=URGENT_CARE, limits=limits)
    quality = _quality(screening.image_meta)
    if not result:
        return PatientSummary(
            state="waiting", validated_source=validated, quality=quality,
            headline="Your photo is ready. The screening has not been run yet.",
            next_step=SummaryNextStep(urgency="none", text="Run the screening to see the result."),
            urgent_care=URGENT_CARE, limits=limits)

    findings = [_plain_finding(f, validated) for f in result.get("findings", [])]
    flagged = [f for f in findings if f.flagged]
    close = [f for f in findings if f.borderline]
    uncertainty = [f"The {f.disease.lower()} score was close to the cut-off, so this result is less certain."
                   for f in close]
    if result.get("demo"):
        uncertainty.append("This is a stored demo result for a sample photo, not a live run of the model.")

    if validated:
        headline = (f"The screening flagged possible signs of {_names(flagged)}." if flagged else
                    "The screening did not flag signs of myopia, cataract, glaucoma or diabetic retinopathy.")
        if flagged:
            step = SummaryNextStep(urgency="soon", text=EYE_EXAM)
        elif close:
            step = SummaryNextStep(urgency="consider", text=CONSIDER)
        else:
            step = SummaryNextStep(urgency="routine", text=ROUTINE)
        state = "result"
    else:
        headline = PHONE_HEADLINE if source == ImageSource.phone_20d.value else UNKNOWN_HEADLINE
        uncertainty.insert(0, "The model has only been tested on fundus photos from eye clinics, "
                              "so it may be wrong on this photo.")
        step = SummaryNextStep(urgency="soon" if flagged else "consider", text=CLINIC_PHOTO)
        state = "experimental"
    return PatientSummary(state=state, validated_source=validated, quality=quality, headline=headline,
                          findings=findings, uncertainty=uncertainty, next_step=step, urgent_care=URGENT_CARE,
                          limits=limits)
