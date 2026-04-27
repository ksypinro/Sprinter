import hmac
import hashlib
import json
import logging
from flask import Flask, request, jsonify
from webhooks.settings import WebhookSettings
from orchestrator.event_buffer import EventBuffer
from orchestrator.store import OrchestratorStore
from orchestrator.models import OrchestratorEvent, EventType

app = Flask(__name__)
settings = WebhookSettings.from_env()
store = OrchestratorStore(settings.orchestrator_storage_root)
event_buffer = EventBuffer(store)

def verify_signature(secret, body, signature):
    if not signature: return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

@app.route("/webhooks/jira", methods=["POST"])
def handle_jira_webhook():
    body = request.get_data()
    signature = request.headers.get("X-Hub-Signature")
    if not verify_signature(settings.auth_secret, body, signature):
        return jsonify({"status": "error", "message": "invalid signature"}), 401
    
    data = request.json
    event_type = data.get("webhookEvent")
    issue_key = data.get("issue", {}).get("key")
    if event_type == "jira:issue_created" and issue_key:
        event = OrchestratorEvent.new(EventType.JIRA_ISSUE_CREATED, issue_key, {"issue_url": f"https://browse/{issue_key}"})
        event_buffer.submit(event)
        return jsonify({"status": "accepted", "event_id": event.event_id}), 202
    
    return jsonify({"status": "ignored"}), 200

@app.route("/ready")
def ready():
    return jsonify({"status": "ready"})

if __name__ == "__main__":
    app.run(port=settings.port)
