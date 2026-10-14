from common import config
from services.ai_advisor.advisor import parse_llm_json, rules_advice
from services.ai_advisor.retrieval import KnowledgeBase, query_from_contributors

LEAK = [{"feature": "duty_loaded", "sensor": "motor_current", "z": 7.5, "direction": "above", "value": 0.77, "baseline": 0.27},
        {"feature": "reservoirs_min", "sensor": "reservoirs", "z": -4.0, "direction": "below", "value": 7.9, "baseline": 8.2}]


def test_retrieval_finds_air_leak_for_leak_signature():
    kb = KnowledgeBase(config.KNOWLEDGE_DIR)
    hits = kb.search(query_from_contributors(LEAK), k=1)
    assert "Air leak" in hits[0]["title"]


def test_rules_fallback_gives_actions():
    kb = KnowledgeBase(config.KNOWLEDGE_DIR)
    advice = rules_advice(LEAK, kb.search(query_from_contributors(LEAK)))
    assert advice["urgency"] == "high"
    assert len(advice["recommended_actions"]) >= 3


def test_llm_json_is_validated():
    text = 'Sure! {"likely_cause": "Air leak", "recommended_actions": ["Check fittings"], "urgency": "URGENT"}'
    out = parse_llm_json(text)
    assert out["likely_cause"] == "Air leak"
    assert out["urgency"] == "medium"  # invalid value replaced with a safe default
