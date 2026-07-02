#!/usr/bin/env python
"""Test Azure OpenAI with correct parameters"""
import os
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv(override=True)

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
api_key = os.getenv("AZURE_OPENAI_KEY")
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
api_version = os.getenv("AZURE_OPENAI_API_VERSION")

print("Testing Azure OpenAI with CORRECT parameters...\n")

url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
print(f"URL: {url}\n")

headers = {
    "api-key": api_key,
    "Content-Type": "application/json",
}

payload = {
    "messages": [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Say hello"}
    ],
    "max_completion_tokens": 50,  # CORRECT parameter
    "temperature": 0.1
}

print("Sending request...")
try:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        print(f"✓ Status Code: {response.status}")
        data = json.load(response)
        if "choices" in data and len(data["choices"]) > 0:
            content = data["choices"][0]["message"]["content"]
            print(f"✓ Response: {content}")
            print(f"\n✅ SUCCESS: Azure OpenAI API is working!")
        else:
            print(f"Response:\n{json.dumps(data, indent=2)}")
        
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}")
    try:
        error_data = json.load(e.fp)
        print(f"Error:\n{json.dumps(error_data, indent=2)}")
    except:
        print(f"Error:\n{e.read().decode()}")
        
except Exception as e:
    print(f"Request failed: {type(e).__name__}: {e}")
