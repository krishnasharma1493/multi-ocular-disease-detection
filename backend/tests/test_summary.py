"""The plain-language patient summary: pure function tests on constructed screenings, plus the API."""
import re

import pytest

from app.modules.screenings.models import Eye, ImageSource, Screening
from app.modules.screenings.summary import patient_summary

API = "/api/v1"
BANNED = re.compile(r"\byou have\b|\bdiagnosed\b|\bdiagnosis of\b", re.I)


def finding(code, disease, p, t):
    return {"code": code, "disease": disease, "probability": p, "threshold": t, "positive": round(p, 4) >= round(t, 4)}


def result(*findings, demo=False):
    positives = [f["disease"] for f in findings if f["positive"]]
    return {"overall": f"Possible: {', '.join(positives)}" if positives else "none", "any_positive": bool(positives),
            "findings": list(findings), "source": "fixture" if demo else "live", "demo": demo}


def make(source="clinic_fundus", photo=True, res=None, sharpness=0.55):
    return Screening(id=1, owner_id=1, eye=Eye.right, image_source=ImageSource(source),
                     image_filename="a.jpg" if photo else None,
                     image_meta={"sharpness": sharpness} if photo else None, result=res)


FOUR = [("M", "Myopia", 0.78), ("C", "Cataract", 0.29), ("G", "Glaucoma", 0.54), ("D", "Diabetic Retinopathy", 0.48)]


def clear_result(**over):
    probs = {"M": 0.02, "C": 0.03, "G": 0.05, "D": 0.1} | over
    return result(*[finding(c, d, probs[c], t) for c, d, t in FOUR])


def check_wording(summary):
    text = " ".join([summary.headline, summary.next_step.text, *summary.uncertainty,
                     *[f.plain for f in summary.findings]])
    assert not BANNED.search(text)
    assert summary.is_diagnosis is False
    assert "sudden loss of vision" in summary.urgent_care  # urgent-care line, whatever the result
    assert any("not a diagnosis" in line.lower() for line in summary.limits)


def test_no_photo():
    s = patient_summary(make(photo=False))
    assert s.state == "no_photo" and s.quality is None and s.findings == [] and s.next_step.urgency == "none"
    check_wording(s)


def test_waiting():
    s = patient_summary(make())
    assert s.state == "waiting" and s.quality.ok and "0.55" in s.quality.detail and "0.30" in s.quality.detail
    assert s.findings == [] and s.next_step.urgency == "none"
    check_wording(s)


def test_clinic_result_with_one_flag_and_one_borderline():
    s = patient_summary(make(res=clear_result(C=0.88, D=0.45)))
    assert s.state == "result" and s.validated_source
    assert s.headline == "The screening flagged possible signs of cataract."
    by = {f.code: f for f in s.findings}
    assert by["C"].flagged and by["C"].plain == "Possible signs of cataract were found."
    assert not by["D"].flagged and by["D"].borderline
    assert by["D"].plain == "No signs of diabetic retinopathy were found by the screening."
    assert not by["M"].borderline
    assert s.uncertainty == ["The diabetic retinopathy score was close to the cut-off, so this result is less certain."]
    assert s.next_step.urgency == "soon" and "eye doctor" in s.next_step.text
    check_wording(s)


def test_two_flags_are_listed_together():
    s = patient_summary(make(res=clear_result(C=0.9, G=0.9)))
    assert s.headline == "The screening flagged possible signs of cataract and glaucoma."


def test_clinic_all_clear():
    s = patient_summary(make(res=clear_result()))
    assert s.state == "result" and s.next_step.urgency == "routine" and "yearly eye exam" in s.next_step.text
    assert s.headline.startswith("The screening did not flag signs of")
    assert s.uncertainty == [] and not any(f.flagged for f in s.findings)
    check_wording(s)


def test_all_clear_but_borderline_is_consider():
    s = patient_summary(make(res=clear_result(G=0.50)))
    assert s.next_step.urgency == "consider" and s.findings[2].borderline
    check_wording(s)


def test_phone_20d_is_experimental():
    s = patient_summary(make("phone_20d", res=clear_result(C=0.9)))
    assert s.state == "experimental" and not s.validated_source
    assert s.headline == ("This phone photo was read by a model that has not been tested on phone photos, "
                          "so this is not a reliable result.")
    cataract = next(f for f in s.findings if f.code == "C")
    assert cataract.plain.startswith("The model flagged possible signs of cataract") and "experimental" in cataract.plain
    assert "fundus photo" in s.next_step.text and "eye examination" in s.next_step.text
    assert s.next_step.urgency in {"soon", "consider"} and s.next_step.urgency != "routine"
    assert any("only been tested on fundus photos from eye clinics" in u for u in s.uncertainty)
    assert "reliable result" not in s.next_step.text.replace("not a reliable", "")
    check_wording(s)


def test_phone_20d_all_clear_is_never_routine():
    s = patient_summary(make("phone_20d", res=clear_result()))
    assert s.state == "experimental" and s.next_step.urgency == "consider"
    assert all("does not rule it out" in f.plain for f in s.findings)
    check_wording(s)


def test_unknown_source_is_experimental():
    s = patient_summary(make("unknown", res=clear_result(D=0.9)))
    assert s.state == "experimental" and not s.validated_source and "not a reliable result" in s.headline
    assert s.next_step.urgency == "soon" and "fundus photo" in s.next_step.text
    check_wording(s)


def test_demo_fixture_is_labelled():
    s = patient_summary(make(res=result(*[finding(c, d, 0.05, t) for c, d, t in FOUR], demo=True)))
    assert any("stored result" in u for u in s.uncertainty)
    check_wording(s)


def test_quality_when_not_recorded_and_for_soft_photos():
    s = patient_summary(make(res=clear_result(), sharpness=None))
    assert s.quality.ok is None and s.quality.label == "Quality not recorded"
    soft = patient_summary(make(res=clear_result(), sharpness=0.2))
    assert "0.18" in soft.quality.detail


def test_does_not_change_the_screening():
    screening = make(res=clear_result(C=0.9))
    before = screening.model_dump()
    patient_summary(screening)
    assert screening.model_dump() == before


def test_api_returns_the_summary(client, auth):
    data = client.get(f"{API}/screenings/4", headers=auth).json()["data"]  # seeded DR screening, fixture result
    assert data["summary"]["is_diagnosis"] is False and data["summary"]["state"] == "result"
    assert data["summary"]["headline"].startswith("The screening flagged possible signs of diabetic retinopathy")
    assert any("stored result" in u for u in data["summary"]["uncertainty"])
    waiting = client.get(f"{API}/screenings/7", headers=auth).json()["data"]  # photo, no result yet
    assert waiting["summary"]["state"] == "waiting" and waiting["summary"]["is_diagnosis"] is False
    listed = client.get(f"{API}/screenings", headers=auth).json()["data"]
    assert all(row["summary"] is not None for row in listed)


@pytest.mark.parametrize("sid", [1, 2, 3, 4, 5, 6])
def test_every_seeded_result_has_clean_wording(client, auth, sid):
    from app.modules.screenings.schemas import PatientSummary

    summary = PatientSummary(**client.get(f"{API}/screenings/{sid}", headers=auth).json()["data"]["summary"])
    check_wording(summary)
