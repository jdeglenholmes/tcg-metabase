import os
import json
import ast
import pandas as pd
import numpy as np
import joblib
from sqlalchemy import text
from src.database.connection import get_engine

TARGET_NAMES = [
    'chaotic', 'cinematic', 'comic_book_illustration', 'crisp_digital_portrait', 
    'handcrafted_diorama', 'has_cameo', 'is_trainer_gallery', 'kinetic', 
    'legendary', 'maximalist', 'minimalist', 'modern', 'neutral', 'pop_art', 
    'standard_generic', 'surrealist', 'traditional_hand_painted', 'whimsical'
]

def main():
    print("="*60)
    print("🕵️ THE AI CRITIC: Hunting for Human Inconsistencies")
    print("="*60)

    model_path = "src/ml/models/custom_classifier.pkl"
    threshold_path = "src/ml/models/optimal_thresholds.json"
    
    if not os.path.exists(model_path):
        print("❌ Model not found. Please train the model first.")
        return
        
    ai_model = joblib.load(model_path)
    with open(threshold_path, "r") as f:
        optimal_thresholds = json.load(f)

    engine = get_engine()
    query = """
        SELECT card_id, name, tags, image_embedding, illustrator, has_trainer 
        FROM tcg_cards 
        WHERE tags IS NOT NULL 
        AND image_embedding IS NOT NULL
        AND supertype IN ('Pokémon', 'Pokemon');
    """
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)

    if df.empty:
        print("❌ No labeled data found.")
        return

    embeddings = np.array([ast.literal_eval(e) for e in df['image_embedding']])
    emb_cols = [f'emb_{i}' for i in range(512)]
    X_input = pd.DataFrame(embeddings, columns=emb_cols)
    X_input['illustrator'] = df['illustrator'].fillna('Unknown')
    X_input['has_trainer'] = df['has_trainer'].fillna(False).astype(int)

    print(f"🧠 AI is auditing {len(df)} cards...")
    y_probs = ai_model.predict_proba(X_input)

    audit_flags = []

    for i, row in df.iterrows():
        human_tags = json.loads(row['tags']) if isinstance(row['tags'], str) else row['tags']
        
        for class_idx, tag_name in enumerate(TARGET_NAMES):
            human_label = int(human_tags.get(tag_name, 0))
            
            if y_probs[class_idx].shape[1] > 1:
                ai_prob = y_probs[class_idx][i, 1]
            else:
                ai_prob = 0.0
                
            ai_threshold = optimal_thresholds.get(tag_name, 0.5)
            
            # THE CRITIC LOGIC
            if human_label == 0 and ai_prob > (ai_threshold + 0.35):
                audit_flags.append({
                    "card_id": row['card_id'],
                    "card_name": row['name'],
                    "tag_in_question": tag_name,
                    "issue_type": "Missed Tag",
                    "human_said": "NO",
                    "ai_confidence": f"{ai_prob*100:.1f}% YES",
                    "ai_threshold_was": f"{ai_threshold*100:.1f}%"
                })
                
            elif human_label == 1 and ai_prob < max(0.05, ai_threshold - 0.35):
                audit_flags.append({
                    "card_id": row['card_id'],
                    "card_name": row['name'],
                    "tag_in_question": tag_name,
                    "issue_type": "False Positive",
                    "human_said": "YES",
                    "ai_confidence": f"{(1-ai_prob)*100:.1f}% NO",
                    "ai_threshold_was": f"{ai_threshold*100:.1f}%"
                })

    if not audit_flags:
        print("✅ Wow! The AI agrees with 100% of your labels. No inconsistencies found.")
        return

    print(f"\n🚨 FOUND {len(audit_flags)} MAJOR DISAGREEMENTS 🚨\n")
    
    # Export all results to CSV
    export_path = "ai_audit_report.csv"
    audit_df = pd.DataFrame(audit_flags)
    
    # Sort by the most confident AI disagreements first
    audit_df = audit_df.sort_values(by="ai_confidence", ascending=False)
    audit_df.to_csv(export_path, index=False)
    
    # Print the top 5 to the terminal just for a quick preview
    print("--- TOP 5 MOST EGREGIOUS CARDS ---")
    for _, flag in audit_df.head(5).iterrows():
        print(f"[{flag['card_id']}] {flag['card_name']} | 🔴 {flag['issue_type']}: {flag['tag_in_question']} (AI is {flag['ai_confidence']} sure)")
        
    print("============================================================")
    print(f"📁 FULL REPORT SAVED TO: {export_path}")
    print("💡 NEXT STEP: Open this CSV, search for the card_ids in your UI,")
    print("and decide who is right: You or the AI.")
    print("============================================================")

if __name__ == "__main__":
    main()