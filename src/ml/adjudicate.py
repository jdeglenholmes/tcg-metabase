import pandas as pd
import os

def adjudicate_data(input_file="ground_truth_labels.csv"):
    if not os.path.exists(input_file):
        print(f"Error: Could not find {input_file}.")
        return

    # 1. Load your single master CSV
    df = pd.read_csv(input_file)
    print(f"Loaded {len(df)} total annotations from {input_file}.")

    # 2. Drop the flawed 'sumi_e_ink' category
    if "sumi_e_ink" in df.columns:
        df = df.drop(columns=["sumi_e_ink"])
        print("Dropped 'sumi_e_ink' category.")

    # 3. Handle skipped cards: If ANY user skipped a card, we discard it entirely
    skipped_cards = df[df["is_skipped"] == 1]["card_id"].unique()
    df_clean = df[~df["card_id"].isin(skipped_cards)].copy()
    print(f"Discarded {len(skipped_cards)} skipped cards.")

    # 4. Group by card_id to find agreements and conflicts
    # We only care about the art style columns (drop metadata for the comparison)
    art_columns = [col for col in df_clean.columns if col not in ["card_id", "labeled_by", "is_skipped"]]
    
    master_rows = []
    conflict_rows = []

    # Grouping by card_id brings all labels for the same card together
    grouped = df_clean.groupby("card_id")
    
    for card_id, group in grouped:
        # If only one person labeled it so far (e.g., your Legacy data), accept it
        if len(group) == 1:
            row_dict = {"card_id": card_id}
            for col in art_columns:
                row_dict[col] = group.iloc[0][col]
            master_rows.append(row_dict)
            continue
            
        # If multiple people labeled it (Dual-Labeling), check for complete agreement
        conflict = False
        row_dict = {"card_id": card_id}
        
        for col in art_columns:
            unique_values = group[col].unique()
            # If everyone gave the exact same answer (1 or 0), it's a match!
            if len(unique_values) == 1:
                row_dict[col] = unique_values[0]
            else:
                # Disagreement found!
                conflict = True
                row_dict[col] = "CONFLICT"
                
        if conflict:
            conflict_rows.append(row_dict)
        else:
            master_rows.append(row_dict)

    # 5. Export the results
    if master_rows:
        master_df = pd.DataFrame(master_rows)
        master_df.to_csv("master_ground_truth.csv", index=False)
        print(f"✅ Created 'master_ground_truth.csv' with {len(master_df)} unified labels.")

    if conflict_rows:
        conflict_df = pd.DataFrame(conflict_rows)
        conflict_df.to_csv("conflicts_to_review.csv", index=False)
        print(f"⚠️ Found {len(conflict_df)} conflicts! Please review 'conflicts_to_review.csv'.")

if __name__ == "__main__":
    adjudicate_data()