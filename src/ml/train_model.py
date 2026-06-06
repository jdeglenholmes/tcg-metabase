import os
import ast
import pandas as pd
import numpy as np
import joblib
from sqlalchemy import text
from sklearn.model_selection import train_test_split
from sklearn.multioutput import MultiOutputClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from src.database.connection import get_engine

def load_training_data():
    """Merges your master CSV labels with the 512-d CLIP embeddings from the DB."""
    csv_path = "master_ground_truth.csv"
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Cannot find {csv_path}. Have you run adjudicate.py yet?")
        
    # 1. Load the pristine labels
    df_labels = pd.read_csv(csv_path)
    
    # BULLETPROOF FIX 1: Strip any invisible trailing spaces from the CSV
    df_labels['card_id'] = df_labels['card_id'].astype(str).str.strip()
    
    y_cols = [c for c in df_labels.columns if c != 'card_id']
    print(f"🎯 Training on {len(df_labels)} cards across {len(y_cols)} art styles.")

    # 2. Fetch Embeddings from the Database
    # BULLETPROOF FIX 2: Do not use the massive IN clause. Pull all enriched cards and let Pandas match them.
    engine = get_engine()
    query = "SELECT card_id, image_embedding FROM tcg_cards WHERE image_embedding IS NOT NULL;"
    
    with engine.connect() as conn:
        df_embeddings = pd.read_sql_query(text(query), conn)

    # Strip DB card IDs just in case
    df_embeddings['card_id'] = df_embeddings['card_id'].astype(str).str.strip()

    # 3. Merge Data (Pandas will only keep the rows that exist in BOTH dataframes)
    df_merged = pd.merge(df_labels, df_embeddings, on='card_id')
    print(f"🔗 Successfully matched {len(df_merged)} embeddings to your labels.")
    
    if len(df_merged) == 0:
        raise ValueError("CRITICAL ERROR: Match failed. Check if 'image_embedding' column actually contains data.")

    # Parse the pgvector string into a pure numpy array
    def parse_vector(v):
        if isinstance(v, str):
            return np.array(ast.literal_eval(v))
        return np.array(v)

    # X = The 512 numbers (The Features)
    X = np.vstack(df_merged['image_embedding'].apply(parse_vector).values)
    
    # y = Your 1s and 0s (The Targets)
    y = df_merged[y_cols].values

    return X, y, y_cols

def train_and_save_model():
    print("🧠 Step 1: Loading data from CSV and Database...")
    X, y, target_names = load_training_data()
    
    # Split 80% for training, 20% for testing the model's accuracy
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print("\n⚙️ Step 2: Training the Multi-Label Linear Classifier...")
    # class_weight='balanced' is the magic parameter here. 
    # It mathematically forces the model to pay extra attention to your rare classes 
    # (like Surreal Abstract) so they aren't drowned out by Crisp Digital Portrait.
    base_estimator = LogisticRegression(max_iter=2000, class_weight='balanced')
    model = MultiOutputClassifier(base_estimator)
    
    model.fit(X_train, y_train)

    print("\n📈 Step 3: Evaluating Model Performance on Unseen Test Data...")
    y_pred = model.predict(X_test)
    
    # Print the scorecard!
    print(classification_report(y_test, y_pred, target_names=target_names, zero_division=0))

    print("\n💾 Step 4: Saving Model Artifacts...")
    os.makedirs("src/ml/models", exist_ok=True)
    
    # Save the trained model and the column names for the ingestion script to use later
    joblib.dump(model, "src/ml/models/aesthetic_classifier.pkl")
    joblib.dump(target_names, "src/ml/models/target_names.pkl")
    print("✅ Success! Model saved to src/ml/models/")

if __name__ == "__main__":
    train_and_save_model()