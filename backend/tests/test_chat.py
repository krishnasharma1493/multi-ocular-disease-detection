"""Eye-health chat API: history, ownership, server-built context, retrieval, source filtering, outage, limits."""
import itertools
from datetime import timedelta

import httpx
import pytest
from sqlmodel import Session, select

from app.core.db import engine
from app.core.security import create_access_token
from app.modules.chat import llm
from app.modules.chat.models import ChatMessage, ChatRole
from app.modules.screenings.models import Eye, Screening, ScreeningStatus
from app.modules.users.models import User
from app.utils.time import utcnow

API = "/api/v1"
_ids = itertools.count(1)


class FakeProvider:
    """Records every prompt; replies with a fixed reply, or the next one of a list, or raises."""

    def __init__(self, *replies):
        self.replies = list(replies) or [{"in_scope": True, "answer": "Here is an answer [S1].", "sources_used": ["S1"]}]
        self.calls: list[tuple[str, list[dict]]] = []

    def generate(self, system, turns):
        self.calls.append((system, [dict(t) for t in turns]))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture()
def fake(monkeypatch):
    def install(*replies):
        provider = FakeProvider(*replies)
        monkeypatch.setattr(llm, "get_provider", lambda: provider)
        return provider
    return install


def _messages(screening_id: int) -> list[ChatMessage]:
    with Session(engine) as s:
        return list(s.exec(select(ChatMessage).where(ChatMessage.screening_id == screening_id)).all())


@pytest.fixture()
def patient(client):
    """A new patient with exactly one analyzed screening (not part of the seeded demo story)."""
    n = next(_ids)
    with Session(engine) as s:
        user = User(email=f"chat-patient-{n}@example.com", name=f"Chat Patient {n}")
        s.add(user)
        s.commit()
        s.refresh(user)
        screening = Screening(owner_id=user.id, patient_ref=f"P-9{n:03d}", eye=Eye.left,
                              status=ScreeningStatus.analyzed, notes="Private note about my aunt",
                              result={"overall": "Possible: Glaucoma", "any_positive": True, "demo": False,
                                      "findings": [{"code": "G", "disease": "Glaucoma", "probability": 0.6,
                                                    "threshold": 0.5418, "positive": True}]})
        s.add(screening)
        s.commit()
        s.refresh(screening)
        return {"headers": {"Authorization": f"Bearer {create_access_token(int(user.id))}"},
                "screening_id": int(screening.id), "email": user.email, "name": user.name}


def test_fresh_thread_then_history_in_order(client, auth, fake):
    sid = 5
    assert client.get(f"{API}/screenings/{sid}/chat", headers=auth).json() == {"success": True, "data": []}
    fake({"in_scope": True, "answer": "Glaucoma damages the optic nerve [S1].", "sources_used": ["S1"]})
    r = client.post(f"{API}/screenings/{sid}/chat", headers=auth, json={"message": "  What is glaucoma?  "})
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["user_message"]["role"] == "user" and data["user_message"]["content"] == "What is glaucoma?"
    a = data["assistant_message"]
    assert a["role"] == "assistant" and a["in_scope"] is True and "optic nerve" in a["content"]
    assert a["sources"][0]["id"] == "S1" and a["sources"][0]["title"] == "Glaucoma"
    assert set(a["sources"][0]) == {"id", "title", "section", "version", "url", "review_status"}
    assert a["sources"][0]["url"].startswith("https://www.nei.nih.gov/")
    thread = client.get(f"{API}/screenings/{sid}/chat", headers=auth).json()["data"]
    assert [m["role"] for m in thread] == ["user", "assistant"]
    assert [m["id"] for m in thread] == [data["user_message"]["id"], a["id"]]


def test_other_patients_screening_is_404_and_nothing_stored(client, judge, fake):
    provider = fake()
    before = len(_messages(1))
    assert client.get(f"{API}/screenings/1/chat", headers=judge).status_code == 404
    r = client.post(f"{API}/screenings/1/chat", headers=judge, json={"message": "What did my screening show?"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert provider.calls == [] and len(_messages(1)) == before
    assert client.post(f"{API}/screenings/999999/chat", headers=judge, json={"message": "hi"}).status_code == 404


def test_context_has_own_records_only(client, auth, fake):
    provider = fake()
    assert client.post(f"{API}/screenings/1/chat", headers=auth,
                       json={"message": "What did my latest screening show?"}).status_code == 201
    system, turns = provider.calls[-1]
    # This screening's findings, with thresholds, and the demo / experimental caveats
    assert "THIS SCREENING: screening #1" in system
    assert "Myopia: probability 100%, threshold 78%, FLAGGED as a possible sign" in system
    assert "Glaucoma: probability 0%, threshold 54%, not flagged" in system
    assert "DEMO result" in system and "EXPERIMENTAL reading" in system and "image source unknown" in system
    # The patient's other screenings, never another patient's (#8 belongs to judge)
    for other in range(2, 8):
        assert f"screening #{other} " in system
    assert "screening #8" not in system and "dr_90" not in system and "P-0201" not in system
    assert "cannot support a reliable conclusion about change" in system
    # Never the user's name, email, notes or patient reference
    for secret in ("demo@example.com", "Screening technician", "Wears thick glasses", "P-0147",
                   "Family history of glaucoma", "Diabetic; previous laser"):
        assert secret not in system and all(secret not in t["content"] for t in turns)
    assert turns[-1] == {"role": "user", "content": "What did my latest screening show?"}


def test_borderline_flag(client, auth, fake):
    provider = fake()
    client.post(f"{API}/screenings/6/chat", headers=auth, json={"message": "Is my myopia score close?"})
    system = provider.calls[-1][0]
    this = system.split("HISTORY")[0]
    assert "Myopia: probability 46%, threshold 78%, not flagged" in this and "BORDERLINE" not in this
    assert "Diabetic Retinopathy: probability 9%, threshold 48%" in system


def test_follow_up_retrieves_glaucoma_passages(client, auth, fake):
    provider = fake()
    assert client.post(f"{API}/screenings/3/chat", headers=auth,
                       json={"message": "What are the symptoms of glaucoma?"}).status_code == 201
    assert client.post(f"{API}/screenings/3/chat", headers=auth,
                       json={"message": "My father had it. Does that affect my risk?"}).status_code == 201
    system, turns = provider.calls[-1]
    passages = system.split("REFERENCE PASSAGES", 1)[1]
    assert "[S1] Glaucoma > " in passages and "Am I at risk for glaucoma?" in passages
    assert "family history" in passages.lower()
    # Earlier turns are sent, oldest first, ending with the new question
    assert [t["role"] for t in turns] == ["user", "assistant", "user"]
    assert turns[0]["content"] == "What are the symptoms of glaucoma?"


def test_unsupplied_sources_are_filtered(client, auth, fake):
    fake({"in_scope": True, "answer": "Cataracts cloud the lens [S1]. Also see [S9].", "sources_used": ["S1", "S9", "X"]})
    r = client.post(f"{API}/screenings/2/chat", headers=auth, json={"message": "What is a cataract?"})
    a = r.json()["data"]["assistant_message"]
    assert [s["id"] for s in a["sources"]] == ["S1"]
    assert "[S9]" not in a["content"] and "[S1]" in a["content"]


def test_no_passages_means_no_sources(client, auth, fake):
    provider = fake({"in_scope": True, "answer": "The approved sources don't cover that [S1].", "sources_used": ["S1"]})
    r = client.post(f"{API}/screenings/4/chat", headers=auth, json={"message": "Qwzx blorft?"})
    assert "none matched this question" in provider.calls[-1][0]
    assert r.json()["data"]["assistant_message"]["sources"] == []


def test_off_topic_reply_is_stored_as_is(client, auth, fake):
    redirect = "I can only help with eye-health questions. Is there anything about your eyes I can help with?"
    fake({"in_scope": False, "answer": redirect, "sources_used": []})
    r = client.post(f"{API}/screenings/5/chat", headers=auth, json={"message": "What is 2 + 2?"})
    assert r.status_code == 201
    a = r.json()["data"]["assistant_message"]
    assert a["in_scope"] is False and a["content"] == redirect and a["sources"] == []
    assert client.get(f"{API}/screenings/5/chat", headers=auth).json()["data"][-1]["in_scope"] is False


def _assert_outage(client, auth, sid):
    before = len(_messages(sid))
    r = client.post(f"{API}/screenings/{sid}/chat", headers=auth, json={"message": "What is glaucoma?"})
    assert r.status_code == 503
    assert r.json()["error"] == {"code": "CHAT_UNAVAILABLE",
                                 "message": "The assistant is unavailable right now. Your screening result is still available."}
    assert len(_messages(sid)) == before  # nothing stored
    screening = client.get(f"{API}/screenings/{sid}", headers=auth)
    assert screening.status_code == 200 and screening.json()["data"]["result"]["findings"]


def test_outage_provider_raises(client, auth, fake):
    fake(RuntimeError("connection reset"))
    _assert_outage(client, auth, 1)
    fake(llm.LLMUnavailable("timeout"))
    _assert_outage(client, auth, 1)


def test_outage_missing_key_with_real_provider(client, auth, monkeypatch):
    monkeypatch.setattr(llm.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no request without a key"))
    _assert_outage(client, auth, 1)


def test_invalid_json_is_retried_once(client, auth, fake):
    provider = fake(llm.LLMInvalidOutput("bad"), {"in_scope": True, "answer": "Fine.", "sources_used": []})
    assert client.post(f"{API}/screenings/2/chat", headers=auth, json={"message": "Is glare normal?"}).status_code == 201
    assert len(provider.calls) == 2
    provider = fake(llm.LLMInvalidOutput("bad"), llm.LLMInvalidOutput("still bad"))
    _assert_outage(client, auth, 2)
    assert len(provider.calls) == 2


@pytest.mark.parametrize("body", [{"message": ""}, {"message": "   \n "}, {}, {"message": "x" * 4001}])
def test_validation(client, auth, fake, body):
    provider = fake()
    r = client.post(f"{API}/screenings/1/chat", headers=auth, json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert provider.calls == []


def test_long_message_at_the_limit_is_accepted(client, patient, fake):
    fake()
    r = client.post(f"{API}/screenings/{patient['screening_id']}/chat", headers=patient["headers"],
                    json={"message": "eye " * 1000})
    assert r.status_code == 201


def test_rate_limit(client, patient, fake):
    sid = patient["screening_id"]
    with Session(engine) as s:
        owner = s.get(Screening, sid).owner_id
        old = utcnow() - timedelta(hours=2)
        for i in range(25):  # 19 in the last hour, 6 older ones that no longer count
            s.add(ChatMessage(owner_id=owner, screening_id=sid, role=ChatRole.user, content=f"q{i}",
                              **({"created_at": old} if i >= 19 else {})))
        s.commit()
    provider = fake()
    assert client.post(f"{API}/screenings/{sid}/chat", headers=patient["headers"],
                       json={"message": "One more?"}).status_code == 201   # the 20th this hour
    r = client.post(f"{API}/screenings/{sid}/chat", headers=patient["headers"], json={"message": "And another?"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    assert "per hour" in r.json()["error"]["message"] and len(provider.calls) == 1


def test_no_previous_screening_note(client, patient, fake):
    provider = fake()
    r = client.post(f"{API}/screenings/{patient['screening_id']}/chat", headers=patient["headers"],
                    json={"message": "Has my glaucoma score changed?"})
    assert r.status_code == 201
    system = provider.calls[-1][0]
    assert "no previous screening" in system
    assert "Glaucoma: probability 60%, threshold 54%, FLAGGED as a possible sign - BORDERLINE" in system
    assert "left eye" in system and "no photo uploaded" in system
    for secret in (patient["email"], patient["name"], "Private note about my aunt", "P-9"):
        assert secret not in system


def test_deleting_a_screening_deletes_its_chat(client, patient, fake):
    fake()
    sid = patient["screening_id"]
    client.post(f"{API}/screenings/{sid}/chat", headers=patient["headers"], json={"message": "What is glaucoma?"})
    assert len(_messages(sid)) == 2
    assert client.delete(f"{API}/screenings/{sid}", headers=patient["headers"]).status_code == 200
    assert _messages(sid) == []


# Gemini provider (no network: httpx.post is replaced) ----------------------------------------------------------

def _gemini(monkeypatch, response=None, exc=None):
    sent = {}

    def post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers, timeout=timeout)
        if exc:
            raise exc
        return response

    monkeypatch.setattr(httpx, "post", post)
    return llm.GeminiProvider("test-key", "gemini-2.5-flash", 20), sent


def _ok(parts):
    return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": parts},
                                                     "finishReason": "STOP"}]})


def test_gemini_request_and_reply(monkeypatch):
    provider, sent = _gemini(monkeypatch, _ok([
        {"text": "thinking about it", "thought": True},
        {"text": '{"in_scope": true, "answer": "Hello [S1]", "sources_used": ["S1"]}'}]))
    reply = provider.generate("RULES", [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"},
                                        {"role": "user", "content": "q2"}])
    assert reply == {"in_scope": True, "answer": "Hello [S1]", "sources_used": ["S1"]}
    assert sent["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    assert sent["headers"] == {"x-goog-api-key": "test-key"} and "key=" not in sent["url"]
    body = sent["json"]
    assert body["systemInstruction"] == {"parts": [{"text": "RULES"}]}
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][1]["parts"] == [{"text": "a1"}]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["temperature"] <= 0.3 and sent["timeout"] == 20


@pytest.mark.parametrize("response,exc,error", [
    (None, httpx.ReadTimeout("slow"), llm.LLMUnavailable),
    (None, httpx.ConnectError("down"), llm.LLMUnavailable),
    (httpx.Response(500, json={"error": {"status": "INTERNAL"}}), None, llm.LLMUnavailable),
    (httpx.Response(429, text="quota"), None, llm.LLMUnavailable),
    (httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}), None, llm.LLMUnavailable),
    (httpx.Response(200, json={"candidates": []}), None, llm.LLMUnavailable),
    (_ok([{"text": "not json"}]), None, llm.LLMInvalidOutput),
    (_ok([{"text": '{"in_scope": "yes", "answer": "x"}'}]), None, llm.LLMInvalidOutput),
    (_ok([{"text": '{"in_scope": true, "answer": ""}'}]), None, llm.LLMInvalidOutput),
])
def test_gemini_failures(monkeypatch, response, exc, error):
    provider, _ = _gemini(monkeypatch, response, exc)
    with pytest.raises(error):
        provider.generate("RULES", [{"role": "user", "content": "q"}])


def test_parse_reply_tolerates_a_fenced_block():
    assert llm.parse_reply('```json\n{"in_scope": false, "answer": "Eyes only."}\n```') == \
        {"in_scope": False, "answer": "Eyes only.", "sources_used": []}
