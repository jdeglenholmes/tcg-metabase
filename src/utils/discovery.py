import httpx
from thefuzz import fuzz
from collections import Counter

# Use a global timeout and client config
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

def discover_tcg_sets(target_set_name: str = None, min_cards=80, series_name=None, fuzzy_threshold: int = 70):
    """
    Purpose:   
        Fetches a list of Pokemon Trading Card Game (TCG) Sets from the TCGdex API based on user criertia.
        
    :params:
        :target_set_name: TCG 'Set Name'.
        :min_cards: 'Minimum Card Count'.
        :series_name: TCG 'Series Name'.

    Returns:
        List of dictionaries containing matching TCG Sets.
        When called without params 'ALL' TCG sets located at TCGdex are returned.
    """

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            # 1. Fetch series and sets
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
        
        is_large_enough = total_cards >= min_cards
        is_series_match = True if not series_name else s['series_name'] == series_name

        if is_match and is_large_enough and is_series_match:
            s['match_score'] = score
            results.append(s)
    
    return sorted(results, key=lambda x: x.get('match_score', 0) if target_set_name else x.get('name', ''), reverse=True)

def get_rarity_ratio(set_id: str):
    """Reuses connection to fetch card samples efficiently."""
    with httpx.Client(timeout=TIMEOUT) as client:
        # Fetch set list
        set_url = f"https://api.tcgdex.net/v2/en/sets/{set_id}"
        try:
            resp = client.get(set_url)
            resp.raise_for_status()
            cards = resp.json().get('cards', [])
        except:
            return "No data"

        if not cards: return "No data"
        
        sample_size = min(len(cards), 10)
        sample_rarities = []
        
        for i in range(sample_size):
            try:
                card_id = cards[i]['id']
                # Reusing the client connection here
                card_resp = client.get(f"https://api.tcgdex.net/v2/en/cards/{card_id}")
                card_resp.raise_for_status()
                sample_rarities.append(card_resp.json().get('rarity', 'Unknown'))
            except:
                continue

        if not sample_rarities: return "Unknown"

        total = len(sample_rarities)
        counts = Counter(sample_rarities)
        return " | ".join([f"{r}: {round((c/total)*100)}%" for r, c in counts.items()])
    
import httpx

def fetch_set_list(set_id: str = "") -> list:
    """
    Fetches the TCG set data.
    - If set_id is empty or missing, returns a list of all available global sets.
    - If set_id is provided, returns the detailed card manifest list for that specific set.
    """
    set_id_clean = set_id.strip() if set_id else ""
    
    # Dynamically toggle between the global sets index and a specific set summary
    if not set_id_clean:
        url = "https://api.tcgdex.net/v2/en/sets"
    else:
        url = f"https://api.tcgdex.net/v2/en/sets/{set_id_clean}"
        
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        
        payload = response.json()
        
        # The global list returns an array directly, whereas a specific set returns a dictionary 
        # where the card array lives under the 'cards' key.
        if isinstance(payload, list):
            return payload
        return payload.get('cards', [])
        
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP Error fetching TCG data: {e.response.status_code} for URL: {url}")
        return []
    except Exception as e:
        print(f"❌ Unexpected network or parsing exception in discovery: {e}")
        return []

def fetch_card_details(card_id: str):
    url = f"https://api.tcgdex.net/v2/en/cards/{card_id}"
    response = httpx.get(url)
    return response.json()

