import pandas as pd
import numpy as np
import json
import ast
from sklearn.neighbors import KNeighborsClassifier

def main():
    print("🚀 Starting local database enrichment (Type-Safe Version)...")
    df = pd.read_csv('new_output.csv')
    
    # 1. The Ground Truth Artist Mapping
    illustrator_mapping = {
        "5ban Graphics": "3d_cgi_render", "PLANETA Mochizuki": "3d_cgi_render",
        "PLANETA Tsuji": "3d_cgi_render", "PLANETA Igarashi": "3d_cgi_render",
        "PLANETA": "3d_cgi_render", "N-DESIGN Inc.": "3d_cgi_render",
        "aky CG Works": "3d_cgi_render", "Toyste Beach": "3d_cgi_render",
        "Ken Sugimori": "watercolor_and_ink", "Mitsuhiro Arita": "watercolor_and_ink",
        "Kagemaru Himeno": "watercolor_and_ink", "Naoyo Kimura": "watercolor_and_ink",
        "Atsuko Nishida": "watercolor_and_ink", "Tomokazu Komiya": "heavy_acrylic_oil",
        "Oswaldo KATO": "heavy_acrylic_oil", "sowsow": "chalk_pastel",
        "Asako Ito": "textile_craft", "Yuka Morii": "handcrafted_diorama",
        "Tetsu Kayama": "pen_and_ink_stippling", "Shinji Kanda": "pen_and_ink_stippling",
        "Naoki Saito": "crisp_digital_portrait", "kirisAki": "crisp_digital_portrait",
        "miki kudo": "crisp_digital_portrait", "OOYAMA": "crisp_digital_portrait",
        "Kanahei": "crisp_digital_portrait", "AKIRA EGAWA": "crisp_digital_portrait",
        "Kouki Saitou": "crisp_digital_portrait", "Shin Nagasawa": "crisp_digital_portrait",
        "Akira Komayama": "crisp_digital_portrait", "Oku": "pop_art", 
        "RYOTA MURAYAMA": "pop_art", "Hideki Ishikawa": "comic_book_illustration",
        "jaco": "comic_book_illustration"
    }

    # FIX: Force the column datatype to be an object to allow text strings
    df['art_style_enriched'] = df['art_style'].astype(object)
    pokemon_idx = df['supertype'].str.lower() == 'pokemon'

    # Apply strict anchors
    mapped_series = df.loc[pokemon_idx, 'illustrator'].map(illustrator_mapping)
    df.loc[pokemon_idx, 'art_style_enriched'] = mapped_series

    # 2. Parse embeddings for the ML Model
    def safe_parse(val):
        try:
            return ast.literal_eval(val) if isinstance(val, str) else val
        except:
            return None

    df['parsed_emb'] = df['image_embedding'].apply(safe_parse)

    # 3. Train KNN on known artists
    valid_labeled_idx = pokemon_idx & df['art_style_enriched'].notna() & df['parsed_emb'].notna()
    X_labeled = np.stack(df.loc[valid_labeled_idx, 'parsed_emb'].values)
    y_labeled = df.loc[valid_labeled_idx, 'art_style_enriched'].values

    knn = KNeighborsClassifier(n_neighbors=5, weights='distance')
    knn.fit(X_labeled, y_labeled)

    # 4. Predict unknown artists
    valid_unlabeled_idx = pokemon_idx & df['art_style_enriched'].isna() & df['parsed_emb'].notna()
    valid_unlabeled_subset = df[valid_unlabeled_idx]
    X_unlabeled = np.stack(valid_unlabeled_subset['parsed_emb'].values)

    probs = knn.predict_proba(X_unlabeled)
    max_probs = np.max(probs, axis=1)
    preds = knn.classes_[np.argmax(probs, axis=1)]

    # 5. Apply Confidence Threshold (60%)
    final_preds = [p if m >= 0.6 else "Manual review needed" for p, m in zip(preds, max_probs)]
    df.loc[valid_unlabeled_subset.index, 'art_style_enriched'] = final_preds
    df.loc[pokemon_idx & df['art_style_enriched'].isna(), 'art_style_enriched'] = "Manual review needed"

    # 6. Update the JSON tags column for Streamlit
    ART_STYLE_KEYS = [
        "watercolor_and_ink", "heavy_acrylic_oil", "chalk_pastel", "textile_craft", 
        "handcrafted_diorama", "crisp_digital_portrait", "3d_cgi_render", "pixel_art", 
        "retro_90s_anime", "ukiyo_e", "comic_book_illustration", "stained_glass", 
        "pop_art", "standard_generic", "pen_and_ink_stippling"
    ]

    def update_tags(row):
        if row['supertype'].lower() != 'pokemon':
            return row['tags']
        style = row['art_style_enriched']
        if pd.isna(style) or style == "Manual review needed":
            return row['tags']
        
        try:
            current_tags = json.loads(row['tags']) if isinstance(row['tags'], str) else {}
        except:
            current_tags = {}
            
        for k in ART_STYLE_KEYS:
            current_tags.pop(k, None)
            
        current_tags[style] = True
        return json.dumps(current_tags)

    df['tags'] = df.apply(update_tags, axis=1)
    df['art_style'] = df['art_style_enriched'].astype(str)

    # Clean up and save
    df = df.drop(columns=['art_style_enriched', 'parsed_emb'])
    df.to_csv('new_output_enriched.csv', index=False)
    print("✅ Successfully saved enriched database to 'new_output_enriched.csv'")

if __name__ == "__main__":
    main()