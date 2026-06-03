import httpx
import requests
from thefuzz import fuzz
import yaml
import os
from collections import Counter

# Use a global timeout and client config
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# --- Discovery Logic ---

def discover_tcg_sets(target_set_name: str = None, min_cards=80, series_name=None, fuzzy_threshold: int = 70):
    """Fetches a list of Pokemon TCG Sets from TCGdex API."""
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            series_resp = client.get("https://api.tcgdex.net/v2/en/series")
            series_resp.raise_for_status()
            series_data = sorted(series_resp.json(), key=lambda x: len(x['id']), reverse=True)
            series_map = {ser['id']: ser['name'] for ser in series_data}

            sets_resp = client.get("https://api.tcgdex.net/v2/en/sets")
            sets_resp.raise_for_status()
            all_sets = sets_resp.json()
    except Exception as e:
        print(f"❌ API Error: {e}")
        return []
    
    results = []
    for s in all_sets:
        set_id = s.get('id', '')
        detected_series_id = next((sid for sid in series_map if set_id.startswith(sid)), None)
        s['series_name'] = series_map.get(detected_series_id, "Unknown")

        total_cards = s.get('cardCount', {}).get('total', 0)
        
        is_match = True
        score = 0
        if target_set_name:
            name_lower = s.get('name', '').lower()
            search_lower = target_set_name.lower()
            if search_lower in name_lower:
                score = 100
            else:
                score = fuzz.token_set_ratio(search_lower, name_lower)
                is_match = score >= fuzzy_threshold
        
        if is_match and (total_cards >= min_cards) and (not series_name or s['series_name'] == series_name):
            s['match_score'] = score
            results.append(s)
    
    return sorted(results, key=lambda x: x.get('match_score', 0) if target_set_name else x.get('name', ''), reverse=True)

# --- Auto-Validator Bridge ---

def validate_and_fix_id(discovery_id: str) -> str:
    """Pings the Ingestion API and patches .5 to pt5 format."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    ingestion_url = f"https://api.pokemontcg.io/v2/sets/{discovery_id}"
    
    try:
        response = httpx.get(ingestion_url, timeout=5.0, headers=headers)
        if response.status_code == 200:
            return discovery_id
            
        # Patch logic (e.g., sv06.5 -> sv6pt5)
        if ".5" in discovery_id:
            fixed_id = discovery_id.replace(".5", "pt5").replace("sv0", "sv") 
            print(f"⏳ Validator: '{discovery_id}' not found, trying '{fixed_id}'...")
            
            check = httpx.get(f"https://api.pokemontcg.io/v2/sets/{fixed_id}", timeout=5.0, headers=headers)
            if check.status_code == 200:
                print(f"✅ Auto-Validator: Successfully patched to '{fixed_id}'")
                return fixed_id

    except (httpx.ReadTimeout, httpx.ConnectError):
        print(f"⚠️ Validator Warning: Network timed out. Returning original ID.")
        return discovery_id
        
    return discovery_id

def resolve_set_id(target_input: str) -> str:
    """
    The Bulletproof Pipeline:
    1. Check Registry (YAML) for direct mapping.
    2. If not found, use Fuzzy Matching (TCGdex) to find the ID.
    3. Patch/Validate the ID against the PokemonTCG API.
    """
    
    # STEP 1: Registry Lookup (Fastest)
    registry = load_set_registry()
    if target_input.lower() in registry:
        print(f"✅ Found '{target_input}' in Registry.")
        return registry[target_input.lower()]
    
    # STEP 2: Fuzzy Resolution (Fallback)
    print(f"🔍 '{target_input}' not in registry. Searching TCGdex...")
    results = discover_tcg_sets(target_set_name=target_input, min_cards=0)
    
    if not results:
        print(f"❌ Could not resolve '{target_input}' via Fuzzy Match.")
        return None
    
    if results:
        discovered_id = results[0].get('id')
        final_id = validate_and_fix_id(discovered_id)
        print(f"\n💡 Hint: To speed up future runs, add this to config/sets.yaml:")
        print(f"   {target_input.lower().replace(' ', '-')}: {final_id}")

        return final_id
    return None

def load_set_registry():
    config_path = os.path.join(os.path.dirname(__file__), '../../config/sets.yaml')
    
    if not os.path.exists(config_path):
        print(f"❌ Error: Registry file not found at {config_path}")
        return {}

    with open(config_path, 'r') as f:
        data = yaml.safe_load(f)
        
        # Add this check: if data is None (empty file), return an empty dict
        if data is None:
            return {}
            
        return data.get('sets', {})

def get_normalized_db_id(input_id):
    """
    Returns the canonical database-compliant ID for a given input.
    If the ID is unknown, it logs a warning and returns the input as-is.
    """
    if not input_id:
        return None
        
    registry = load_set_registry()
    # Normalize input and lookup in registry
    normalized = registry.get(input_id.lower())
    
    if not normalized:
        print(f"⚠️ Warning: '{input_id}' not found in registry. Using raw ID.")
        return input_id
        
    return normalized