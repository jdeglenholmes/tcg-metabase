import pandas as pd
import os

def print_distribution(csv_path="ground_truth_v1.csv"):
    try:
        df = pd.read_csv(csv_path)
    except FileNotFoundError:
        print(f"❌ Could not find '{csv_path}'")
        return

    print(f"\n📊 TOTAL CARDS LABELED: {len(df)}")
    print("=" * 55)
    
    # Exclude metadata columns
    tag_cols = [col for col in df.columns if col not in ['card_id', 'labeled_by']]
    
    # Calculate counts and sort
    counts = df[tag_cols].sum().sort_values(ascending=False)
    
    print(f"{'CATEGORY':<28} | {'COUNT':<5} | {'% OF DATASET'}")
    print("-" * 55)
    
    for tag, count in counts.items():
        pct = round((count / len(df)) * 100, 1)
        
        if count == 0:
            print(f"🔴 {tag:<25} | {int(count):<5} | {pct}%")
        elif count < 20:
            print(f"🟡 {tag:<25} | {int(count):<5} | {pct}%")
        else:
            print(f"🟢 {tag:<25} | {int(count):<5} | {pct}%")
            
    print("=" * 55)
    print("💡 TIP: Aim for at least 20-30 🟢 examples per category for ML training!")

if __name__ == "__main__":
    print_distribution()