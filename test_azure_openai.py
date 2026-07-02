#!/usr/bin/env python
"""Test Azure OpenAI endpoint connectivity and functionality"""
import os
from dotenv import load_dotenv
from openai import AzureOpenAI

print("=" * 70)
print("TESTING AZURE OPENAI ENDPOINT")
print("=" * 70)

# Load environment
load_dotenv(override=True)

endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
api_key = os.getenv("AZURE_OPENAI_KEY")
deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")
api_version = os.getenv("AZURE_OPENAI_API_VERSION")

print(f"\n1. Environment Variables:")
print(f"   Endpoint:    {endpoint}")
print(f"   Key:         {api_key[:20]}...***")
print(f"   Deployment:  {deployment}")
print(f"   API Version: {api_version}")

if not all([endpoint, api_key, deployment, api_version]):
    print("\n❌ ERROR: Missing required environment variables!")
    exit(1)

print(f"\n2. Creating AzureOpenAI client...")
try:
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
    )
    print("   ✓ Client created successfully")
except Exception as e:
    print(f"   ❌ Failed to create client: {e}")
    exit(1)

print(f"\n3. Testing API call (simple completion)...")
try:
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say 'Hello, Azure OpenAI!' in exactly those words."}
        ],
        temperature=0.1,
        max_completion_tokens=50
    )
    result = response.choices[0].message.content.strip()
    print(f"   ✓ API call successful!")
    print(f"   Response: {result}")
    
    if "Hello, Azure OpenAI!" in result:
        print(f"\n✅ SUCCESS: Azure OpenAI endpoint is working correctly!")
    else:
        print(f"\n⚠️  WARNING: Response received but didn't match expected output")
        
except Exception as e:
    print(f"   ❌ API call failed: {e}")
    print(f"   Error type: {type(e).__name__}")
    exit(1)

print("\n" + "=" * 70)
