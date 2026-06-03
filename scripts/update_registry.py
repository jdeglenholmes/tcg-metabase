import requests
import yaml

def generate_registry():
    print("📡 Fetching official set list from API...")
    response = requests.get("https://api.pokemontcg.io/v2/sets")
    data = response.json().get("data", [])
    
    # Create the mapping
    # Key: The 'id' (official) and 'name' (slugified)
    # Value: The 'id' (canonical)
    registry = {}
    for s in data:
        canonical_id = s['id']
        registry[canonical_id] = canonical_id
        registry[s['name'].lower().replace(" ", "-")] = canonical_id
    
    # Add your custom overrides/aliases (like '151')
    registry['151'] = 'sv03.5'
    
    with open('config/sets.yaml', 'w') as f:
        yaml.dump({'sets': registry}, f)
    print(f"✅ Registry updated with {len(registry)} entries.")

if __name__ == "__main__":
    generate_registry()