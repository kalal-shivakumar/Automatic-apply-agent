from dotenv import dotenv_values

env_dict = dotenv_values('.env')
print(f"Keys in .env ({len(env_dict)} total):")
for i, key in enumerate(list(env_dict.keys())[:10]):
    print(f"  {i+1}. {key} = {env_dict[key][:40] if len(env_dict[key]) > 40 else env_dict[key]}")

# Check if any key contains "AZURE"
azure_keys = [k for k in env_dict.keys() if 'AZURE' in k]
print(f"\nAzure-related keys: {azure_keys}")

# Print raw file content
print("\n.env file raw content (first 500 chars):")
with open('.env', 'r') as f:
    content = f.read()
    print(repr(content[:500]))
