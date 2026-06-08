import pandas as pd
import csv

# 1. The underlying physical structure of the corrupted file (Do NOT change this!)
cols_23 = [
    "card_id", "labeled_by", "minimalist", "maximalist", "traditional_watercolor",
    "crisp_digital_portrait", "cinematic", "handcrafted_diorama", "surrealist",
    "kinetic", "chaotic", "modern", "whimsical", "legendary", 
    "standard_generic", "other_unique", "neutral", 
    "has_cameo", "is_trainer_gallery", "pop_art", 
    "urban_graffiti", "comic_book_illustration", "extra_ghost"
]

with open('ground_truth_v1.csv', 'r') as f:
    reader = csv.reader(f)
    header = next(reader)
    rows = list(reader)

# 2. Rebuild the DataFrame with the correct underlying alignment
df = pd.DataFrame(rows, columns=cols_23)

# 3. Your exact list of 21 columns to keep moving forward
cols_to_keep = [
    "card_id", "labeled_by", "minimalist", "maximalist", 
    "traditional_watercolor", "crisp_digital_portrait", "cinematic", 
    "handcrafted_diorama", "surrealist", "kinetic", "chaotic", 
    "modern", "whimsical", "legendary", "standard_generic", 
    "neutral", "has_cameo", "is_trainer_gallery", "pop_art", 
    "comic_book_illustration", "other_unique"
]

df_clean = df[cols_to_keep].copy()

# 4. Clean up empty Excel cells and ensure everything is a clean 1 or 0
for col in cols_to_keep[2:]:
    df_clean[col] = df_clean[col].replace('', '0')
    df_clean[col] = pd.to_numeric(df_clean[col], errors='coerce').fillna(0).astype(int)

# 5. Overwrite the corrupted file with the clean one!
df_clean.to_csv('ground_truth_v1.csv', index=False)
print("✅ CSV successfully realigned and restored with your chosen columns!")