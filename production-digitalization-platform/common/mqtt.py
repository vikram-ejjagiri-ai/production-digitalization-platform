"""MQTT client factory with connection retry (paho-mqtt 2.x)."""
import json
import time

import paho.mqtt.client as mqtt

from common import config
from common.log import get_logger

log = get_logger("mqtt")


def make_client(client_id: str, on_message=None, subscriptions: list[str] | None = None) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)

    def _on_connect(c, userdata, flags, reason_code, properties):
        log.info("%s connected to MQTT broker (%s)", client_id, reason_code)
        for t in subscriptions or []:
            c.subscribe(t, qos=0)
            log.info("%s subscribed to %s", client_id, t)

    client.on_connect = _on_connect
    if on_message:
        client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    for attempt in range(1, 61):
        try:
            client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
            return client
        except OSError as exc:
            log.info("Waiting for MQTT broker (%s/60): %s", attempt, exc)
            time.sleep(2)
    raise RuntimeError("MQTT broker not reachable")


def publish_json(client: mqtt.Client, topic: str, payload: dict, retain: bool = False) -> None:
    client.publish(topic, json.dumps(payload, default=str), qos=0, retain=retain)
