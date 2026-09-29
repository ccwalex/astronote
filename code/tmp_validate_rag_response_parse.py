import sys

sys.path.insert(0, "code")
import api

payload = {
    "raw": {
        "choices": [
            {
                "message": {
                    "content": "parsed-from-message-content"
                }
            }
        ]
    }
}

result = api._extract_response_text_from_llm_result(payload)
print(result)
if result != "parsed-from-message-content":
    raise SystemExit(1)
