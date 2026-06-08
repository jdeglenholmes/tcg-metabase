import pandas as pd
import json
from sqlalchemy import text
from sklearn.metrics import classification_report
from sklearn.preprocessing import MultiLabelBinarizer
from src.database.connection import get_engine

# --- TAXONOMIES (Must perfectly match your Labeler UI) ---
ART_STYLE_KEYS = [
    "minimalist", "maximalist", "traditional_watercolor", 
    "crisp_digital_portrait", "cinematic", "handcrafted_diorama", 
    "surrealist", "standard_generic",
    "pop_art", "comic_book_illustration"
]

AESTHETIC_KEYS = [
    "kinetic", "chaotic", "modern", "whimsical", "legendary", "neutral"
]

def load_ground_truth(csv_path="ground_truth_v1.csv"):
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            print(f"❌ Ground truth '{csv_path}' is empty. Label some cards first!")
            return None
        return df
    except FileNotFoundError:
        print(f"❌ Could not find '{csv_path}'. Please label some cards in the app first!")
        return None

def evaluate_taxonomy(df, db_df, keys, column_name, title):
    # 1. Format Human Data (True Labels)
    y_true = []
    for _, row in df.iterrows():
        # The CSV stores these as 1 or 0 (or they might be missing/NaN)
        human_labels = [key for key in keys if row.get(key, 0) == 1]
        y_true.append(human_labels)
        
    # 2. Format Machine Data (Predicted Labels)
    y_pred = []
    for _, row in db_df.iterrows():
        machine_labels = []
        if pd.notna(row[column_name]):
            try:
                machine_labels = json.loads(row[column_name])
            except:
                pass
        y_pred.append(machine_labels)

    # 3. Generate the Report Card
    mlb = MultiLabelBinarizer(classes=keys)
    true_matrix = mlb.fit_transform(y_true)
    pred_matrix = mlb.transform(y_pred)

    print("="*60)
    print(f"📊 {title.upper()}: MODEL vs HUMAN")
    print("="*60)
    # zero_division=0 hides warnings for classes that no human has labeled yet
    print(classification_report(true_matrix, pred_matrix, target_names=keys, zero_division=0))
    print("\n")

def run_evaluation(csv_path="ground_truth_v1.csv"):
    gt_df = load_ground_truth(csv_path)
    if gt_df is None:
        return

    # Fetch Machine Predictions for those exact cards
    engine = get_engine()
    card_ids = gt_df['card_id'].tolist()
    
    # Format for SQL IN clause safely
    if len(card_ids) == 1:
        query = f"SELECT card_id, art_style, card_aesthetic FROM tcg_cards WHERE card_id = '{card_ids[0]}'"
    else:
        query = f"SELECT card_id, art_style, card_aesthetic FROM tcg_cards WHERE card_id IN {tuple(card_ids)}"
        
    with engine.connect() as conn:
        ml_df = pd.read_sql_query(text(query), conn)

    # Ensure the DataFrames line up perfectly by merging on card_id
    merged_df = pd.merge(gt_df, ml_df, on='card_id', how='inner')
    
    print(f"\n✅ Evaluating {len(merged_df)} beautifully human-labeled cards...\n")

    # Run the report for both categories
    evaluate_taxonomy(merged_df, merged_df, ART_STYLE_KEYS, 'art_style', "Art Styles")
    evaluate_taxonomy(merged_df, merged_df, AESTHETIC_KEYS, 'card_aesthetic', "Card Aesthetics")

if __name__ == "__main__":
    run_evaluation()