#!/usr/bin/env python
from dotenv import dotenv_values, load_dotenv
import os

print("=" * 60)
print("1. Testing dotenv_values():")
env_dict = dotenv_values('.env')
print(f"   Total keys loaded: {len(env_dict)}")
print(f"   AZURE_OPENAI_ENDPOINT: {env_dict.get('AZURE_OPENAI_ENDPOINT', 'NOT FOUND')}")

print("\n2. Testing load_dotenv(override=True):")
load_dotenv(override=True)
print(f"   AZURE_OPENAI_ENDPOINT from os.environ: {os.environ.get('AZURE_OPENAI_ENDPOINT', 'NOT SET')}")

print("\n3. Testing config.py:")
from config import Config
print(f"   Config.AZURE_OPENAI_ENDPOINT: {Config.AZURE_OPENAI_ENDPOINT}")
print(f"   Correct endpoint? {'naukri-agent-ai' in Config.AZURE_OPENAI_ENDPOINT}")
print("=" * 60)
