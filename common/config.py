"""Central configuration. Every value can be overridden with an environment variable
(set in .env / docker-compose.yml), so the same code runs in Docker and locally."""
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


ROOT = Path(__file__).resolve().parent.parent

# --- Plant / asset identity (used in MQTT topics and database keys) ---
PLANT = _env("PLANT_ID", "plant1")
LINE = _env("LINE_ID", "line1")
MACHINE_ID = _env("MACHINE_ID", "compressor01")

# --- Infrastructure ---
DB_HOST = _env("DB_HOST", "localhost")
DB_PORT = int(_env("DB_PORT", "5432"))
DB_NAME = _env("DB_NAME", "factory")
DB_USER = _env("DB_USER", "factory")
DB_PASSWORD = _env("DB_PASSWORD", "factory")

MQTT_HOST = _env("MQTT_HOST", "localhost")
MQTT_PORT = int(_env("MQTT_PORT", "1883"))

# --- Paths ---
DATA_DIR = Path(_env("DATA_DIR", str(ROOT / "data")))
MODEL_DIR = Path(_env("MODEL_DIR", str(ROOT / "models")))
REPORT_DIR = Path(_env("REPORT_DIR", str(ROOT / "reports")))
KNOWLEDGE_DIR = Path(_env("KNOWLEDGE_DIR", str(ROOT / "knowledge_base")))

# --- Dataset & split ---
DATASET = _env("DATASET", "metropt3")  # metropt3 | synthetic
COMMISSIONING_END = _env("COMMISSIONING_END", "2020-03-01")  # Part 1 = everything before this

# --- Replay ---
REPLAY_SPEED = float(_env("REPLAY_SPEED", "60"))  # 60 = one hour of data per real minute
LIVE_START = _env("LIVE_START", "auto")  # auto = 12 h before the first known failure
REPLAY_LOOP = _env("REPLAY_LOOP", "true").lower() == "true"

# --- Streaming feature window (rows; MetroPT-3 is sampled roughly every 10 s) ---
WINDOW_ROWS = int(_env("WINDOW_ROWS", "180"))  # 180 rows ~ 30 min of machine time
STEP_ROWS = int(_env("STEP_ROWS", "6"))  # score every 6 rows ~ 1 min of machine time
ALARM_PERSIST = int(_env("ALARM_PERSIST", "10"))  # consecutive bad windows before alarm opens
CLEAR_PERSIST = int(_env("CLEAR_PERSIST", "10"))  # consecutive good windows before alarm closes

# --- Line simulator ---
LINE_TIME_SCALE = float(_env("LINE_TIME_SCALE", "1"))  # >1 runs the line faster than real time

# --- KPI engine ---
KPI_INTERVAL_S = int(_env("KPI_INTERVAL_S", "30"))
KPI_BUCKET_MINUTES = int(_env("KPI_BUCKET_MINUTES", "15"))
KPI_LOOKBACK_HOURS = int(_env("KPI_LOOKBACK_HOURS", "3"))

# --- AI advisor ---
LLM_PROVIDER = _env("LLM_PROVIDER", "ollama")  # ollama | anthropic | rules
OLLAMA_URL = _env("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2.5:1.5b")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-haiku-5-5")
SUMMARY_INTERVAL_MIN = int(_env("SUMMARY_INTERVAL_MIN", "15"))


def topic(asset: str, kind: str) -> str:
    """ISA-95 style topic: factory/<plant>/<line>/<asset>/<kind>."""
    return f"factory/{PLANT}/{LINE}/{asset}/{kind}"
