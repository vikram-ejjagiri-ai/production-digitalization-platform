"""AI advisor: turns machine alarms and KPIs into recommended actions.

1. Alarm advice - for every new compressor alarm:
   evidence (which features deviate, how much) + production context (ST30 stops)
   -> retrieve matching failure modes from the knowledge base (RAG)
   -> LLM writes cause / actions / urgency as JSON, grounded in those excerpts
   -> validated and stored in clean.ai_recommendations.
2. Shift summary - every SUMMARY_INTERVAL_MIN minutes a short management summary
   of OEE, yield, downtime Pareto and alarms is stored in kpi.ai_summaries.

If no LLM is reachable, a deterministic rule-based answer is produced from the
same retrieved knowledge, so the system never shows an empty panel.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone

from common import config, db
from common.log import get_logger
from services.ai_advisor import llm
from services.ai_advisor.retrieval import KnowledgeBase, query_from_contributors, section_field

log = get_logger("ai-advisor")

SYSTEM_ALARM = (
    "You are a maintenance engineering assistant in a manufacturing plant. You receive a machine alarm with "
    "measured evidence and excerpts from the plant's FMEA / SOP knowledge base. Base your answer ONLY on the "
    "evidence and the excerpts; if they do not support a conclusion, say so and lower the confidence. "
    "Reply with a single JSON object with exactly these keys: "
    '"likely_cause" (string, one sentence), "recommended_actions" (list of 3-5 short imperative strings, '
    'most important first), "urgency" ("low"|"medium"|"high"), "confidence" ("low"|"medium"|"high"), '
    '"evidence" (string, one or two sentences citing the measured deviations).'
)
SYSTEM_SUMMARY = (
    "You are a production engineer writing a shift summary for plant management. Write 3-5 plain sentences, "
    "no bullet points, no markdown. Mention OEE, first pass yield, the biggest loss (downtime reason), machine "
    "alarms and one concrete recommendation. Use only the numbers provided."
)


def describe(c: dict) -> str:
    return (f"{c['feature']} is {abs(c['z']):.1f} standard deviations {c['direction']} its commissioning "
            f"baseline ({c['value']} vs {c['baseline']})")


def rules_advice(contributors: list[dict], hits: list[dict]) -> dict:
    if not hits:
        return {"likely_cause": "Unknown deviation - no matching failure mode in the knowledge base.",
                "recommended_actions": ["Inspect the compressor and compare readings with the commissioning report."],
                "urgency": "medium", "confidence": "low",
                "evidence": "; ".join(describe(c) for c in contributors)}
    top = hits[0]
    actions = [a.strip(" .") for a in re.split(r"\s*\d\)\s*", section_field(top["text"], "Recommended actions")) if a.strip()]
    urgency = section_field(top["text"], "Urgency").split()[0].strip(" .–-").lower() or "medium"
    return {
        "likely_cause": f"{top['title']} (matched knowledge base entry)",
        "recommended_actions": actions[:5],
        "urgency": urgency if urgency in ("low", "medium", "high") else "medium",
        "confidence": "medium" if top["score"] > 0.15 else "low",
        "evidence": "; ".join(describe(c) for c in contributors),
    }


def parse_llm_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in response")
    data = json.loads(m.group(0))
    actions = data.get("recommended_actions")
    if isinstance(actions, str):
        actions = [a.strip() for a in re.split(r"\n|;", actions) if a.strip()]
    if not data.get("likely_cause") or not actions:
        raise ValueError("missing required keys")
    out = {
        "likely_cause": str(data["likely_cause"])[:500],
        "recommended_actions": [str(a)[:300] for a in actions][:6],
        "urgency": str(data.get("urgency", "medium")).lower(),
        "confidence": str(data.get("confidence", "medium")).lower(),
        "evidence": str(data.get("evidence", ""))[:800],
    }
    for key, allowed in (("urgency", ("low", "medium", "high")), ("confidence", ("low", "medium", "high"))):
        if out[key] not in allowed:
            out[key] = "medium"
    return out


def production_context(cur) -> str:
    cur.execute("""SELECT reason, count(*), round(sum(coalesce(duration_s,0))::numeric/60, 1)
                   FROM clean.line_events WHERE station_id = 'ST30' AND event_type = 'downtime_end'
                   AND ts > now() - interval '30 minutes' GROUP BY reason ORDER BY 3 DESC""")
    rows = cur.fetchall()
    if not rows:
        return "No stops at ST30 (panel bonding, uses compressed air) in the last 30 minutes."
    return "ST30 (panel bonding, uses compressed air) stops in last 30 min: " + ", ".join(
        f"{r[0]} x{r[1]} ({r[2]} min)" for r in rows)


def advise_alarms(conn, kb: KnowledgeBase) -> None:
    with db.cursor(conn) as cur:
        cur.execute("""SELECT a.alarm_id, a.machine_id, a.opened_at, a.source_ts_open, a.min_health, a.contributors, a.status
                       FROM clean.alarms a WHERE NOT EXISTS
                       (SELECT 1 FROM clean.ai_recommendations r WHERE r.alarm_id = a.alarm_id)
                       ORDER BY a.opened_at LIMIT 5""")
        alarms = cur.fetchall()
        context = production_context(cur) if alarms else ""
    for alarm_id, machine, opened, src_ts, min_health, contributors, status in alarms:
        contributors = contributors or []
        hits = kb.search(query_from_contributors(contributors), k=2)
        sop = kb.search("ST30 panel bonding compressed air low air pressure backup", k=1)
        excerpts = "\n\n".join(h["text"] for h in hits + sop)
        prompt = (
            f"Machine: {machine} (air production unit / compressor)\n"
            f"Alarm #{alarm_id} opened at {opened:%Y-%m-%d %H:%M} UTC (dataset time {src_ts}); "
            f"lowest health score so far {min_health:.0f}/100 (alarm threshold 50).\n"
            "Measured evidence:\n- " + "\n- ".join(describe(c) for c in contributors) + "\n"
            f"Production context: {context}\n\n"
            f"Knowledge base excerpts:\n{excerpts}\n\nReturn the JSON object now."
        )
        try:
            text, provider = llm.complete(SYSTEM_ALARM, prompt, want_json=True)
            advice, raw = parse_llm_json(text), text
        except (llm.LLMUnavailable, ValueError) as exc:
            log.info("Using rule-based advice for alarm #%s (%s)", alarm_id, exc)
            advice, provider, raw = rules_advice(contributors, hits), "rules", None
        with db.cursor(conn) as cur:
            cur.execute("""INSERT INTO clean.ai_recommendations (alarm_id, provider, likely_cause, recommended_actions,
                           urgency, confidence, evidence, knowledge_sources, raw_response)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (alarm_id, provider, advice["likely_cause"], db.json_param(advice["recommended_actions"]),
                         advice["urgency"], advice["confidence"], advice["evidence"],
                         db.json_param([{"source": h["source"], "title": h["title"], "score": h["score"]} for h in hits]),
                         raw))
        log.info("Advice for alarm #%s via %s: %s", alarm_id, provider, advice["likely_cause"])


def kpi_snapshot(cur, since: datetime) -> dict:
    cur.execute("""SELECT avg(line_oee), sum(good_count), sum(scrap_count), avg(avg_lead_time_s), avg(throughput_per_hour)
                   FROM kpi.line_kpis WHERE bucket >= %s""", (since,))
    oee, good, scrap, lead, tph = cur.fetchone()
    cur.execute("""SELECT station_id, avg(oee) FROM kpi.station_kpis WHERE bucket >= %s AND oee IS NOT NULL
                   GROUP BY station_id ORDER BY 2 LIMIT 1""", (since,))
    worst = cur.fetchone()
    cur.execute("""SELECT station_id, reason, sum(downtime_s)/60 FROM kpi.downtime_reasons WHERE bucket >= %s
                   GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 3""", (since,))
    reasons = cur.fetchall()
    cur.execute("SELECT count(*), count(*) FILTER (WHERE status = 'open') FROM clean.alarms WHERE opened_at >= %s", (since,))
    alarms, open_alarms = cur.fetchone()
    good, scrap = int(good or 0), int(scrap or 0)
    return {
        "bottleneck_oee_pct": round(float(oee) * 100, 1) if oee is not None else None,
        "good_parts": good, "scrap_parts": scrap,
        "first_pass_yield_pct": round(100 * good / (good + scrap), 1) if good + scrap else None,
        "avg_lead_time_min": round(float(lead) / 60, 1) if lead else None,
        "throughput_per_hour": round(float(tph), 1) if tph else None,
        "worst_station": {"station": worst[0], "oee_pct": round(float(worst[1]) * 100, 1)} if worst else None,
        "top_downtime": [{"station": r[0], "reason": r[1], "minutes": round(float(r[2]), 1)} for r in reasons],
        "machine_alarms": int(alarms), "open_alarms": int(open_alarms),
    }


def rules_summary(s: dict) -> str:
    parts = []
    if s["bottleneck_oee_pct"] is not None:
        parts.append(f"Bottleneck OEE averaged {s['bottleneck_oee_pct']} % with {s['good_parts']} good parts "
                     f"and a first pass yield of {s['first_pass_yield_pct']} %.")
    if s["top_downtime"]:
        t = s["top_downtime"][0]
        parts.append(f"The biggest loss was {t['reason'].replace('_', ' ')} at {t['station']} ({t['minutes']} min).")
    if s["machine_alarms"]:
        parts.append(f"{s['machine_alarms']} compressor alarm(s) were raised, {s['open_alarms']} still open; "
                     "check the recommended actions in the alarm log.")
    else:
        parts.append("No compressor alarms were raised.")
    if s["top_downtime"]:
        parts.append(f"Recommendation: address {s['top_downtime'][0]['reason'].replace('_', ' ')} "
                     f"at {s['top_downtime'][0]['station']} first.")
    return " ".join(parts) or "Not enough production data yet."


def write_summary(conn) -> None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=max(config.SUMMARY_INTERVAL_MIN, 60))
    with db.cursor(conn) as cur:
        snap = kpi_snapshot(cur, start)
    if snap["bottleneck_oee_pct"] is None:
        return
    try:
        text, provider = llm.complete(SYSTEM_SUMMARY, "KPIs for the period:\n" + json.dumps(snap, indent=1),
                                      want_json=False, max_tokens=300)
        text = text.strip()
        if not text:
            raise ValueError("empty summary")
    except (llm.LLMUnavailable, ValueError) as exc:
        log.info("Using rule-based summary (%s)", exc)
        text, provider = rules_summary(snap), "rules"
    with db.cursor(conn) as cur:
        cur.execute("INSERT INTO kpi.ai_summaries (period_start, period_end, provider, summary) VALUES (%s,%s,%s,%s)",
                    (start, end, provider, text))
    log.info("Shift summary written via %s", provider)


def main() -> None:
    kb = KnowledgeBase(config.KNOWLEDGE_DIR)
    log.info("Knowledge base loaded: %s sections. LLM provider: %s", len(kb.chunks), config.LLM_PROVIDER)
    conn = db.connect()
    next_summary = time.monotonic() + 5 * 60  # first summary once some KPIs exist
    while True:
        try:
            advise_alarms(conn, kb)
            if time.monotonic() >= next_summary:
                write_summary(conn)
                next_summary = time.monotonic() + config.SUMMARY_INTERVAL_MIN * 60
        except Exception as exc:
            log.exception("Advisor loop failed: %s", exc)
            try:
                conn.close()
            except Exception:
                pass
            conn = db.connect()
        time.sleep(10)


if __name__ == "__main__":
    main()
