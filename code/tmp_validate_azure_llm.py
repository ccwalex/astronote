import requests
from modules.azure_llm import AzureLLMConfig, send_messages

captured = {}


class Resp:
    ok = True
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "pong"}}]}


def fake_post(url, headers=None, json=None, timeout=None):
    captured["url"] = url
    captured["headers"] = headers or {}
    captured["json"] = json or {}
    return Resp()


endpoint = "https://alexchaucw-3042-resource.services.ai.azure.com/api/projects/alexchaucw-3042"
api_key = "4a2dsOPhCvqnDODDFd9eyyxyZzVorENjotPi44x6Sivr5R1U3rd7JQQJ99CFACHYHv6XJ3w3AAAAACOGM6xt"

original_post = requests.post
requests.post = fake_post
try:
    out = send_messages(
        AzureLLMConfig(endpoint=endpoint, api_key=api_key, deployment_id="gpt-5.4-mini"),
        [{"role": "user", "content": "ping"}],
        max_tokens=128,
    )
finally:
    requests.post = original_post

assert captured["url"] == "https://alexchaucw-3042-resource.services.ai.azure.com/openai/v1/chat/completions", captured["url"]
assert "api-version=" not in captured["url"], captured["url"]
assert captured["json"].get("model") == "gpt-5.4-mini", captured["json"]
assert "max_completion_tokens" in captured["json"], captured["json"]
print(out.get("text", ""))
print("VALIDATION_OK")
