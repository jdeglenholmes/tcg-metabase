import os
import json
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
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

def load_training_data():
    """Fetches human tags (Y) and CLIP embeddings (X) directly from PostgreSQL."""
    print("🧠 Step 1: Loading human-verified labels and CLIP embeddings from DB...")
    engine = get_engine()
    
    # ⚠️ NOTE: Update 'image_embedding' if your DB column is named slightly differently 
    # (e.g., 'embedding', 'clip_embedding', etc.)
    query = """
        SELECT card_id, tags, image_embedding 
        FROM tcg_cards 
        WHERE tags IS NOT NULL 
        AND image_embedding IS NOT NULL;
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)

    if df.empty:
        raise ValueError("❌ No data found! Ensure you have tagged cards and generated embeddings.")

    # --- 1. Parse the human labels (Y) ---
    def parse_tags(val):
        if isinstance(val, str):
            try: return json.loads(val)
            except: return {}
        return val if isinstance(val, dict) else {}

    # Convert the JSON tags into separate binary columns
    tags_list = df['tags'].apply(parse_tags).tolist()
    df_tags = pd.DataFrame(tags_list).fillna(0).astype(int)
    
    # Sort columns alphabetically so the model always predicts in the same order
    df_tags = df_tags.reindex(sorted(df_tags.columns), axis=1)
    
    target_names = df_tags.columns.tolist()
    y = df_tags.values

    # --- 2. Parse the CLIP embeddings (X) ---
    def parse_embedding(val):
        if isinstance(val, str):
            try: 
                # Sometimes arrays are stored as stringified lists
                return ast.literal_eval(val) 
            except: 
                pass
        return val

    # Stack the lists into a 2D numpy array (NumCards x 512)
    X = np.stack(df['image_embedding'].apply(parse_embedding).values)
    
    print(f"🎯 Loaded {len(df)} cards across {len(target_names)} target categories.")
    return X, y, target_names

def train_and_save_model():
    X, y, target_names = load_training_data()
    
    # Split 80% for training, 20% for testing the model's accuracy
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print("\n⚙️ Step 2: Training the Custom Supervised Layer (MLP Neural Network)...")
    
    # 2. Replace LogisticRegression with MLPClassifier
    # This creates a neural network with one hidden layer of 256 neurons
    base_estimator = Pipeline([
        ('scaler', StandardScaler()),
        ('mlp', MLPClassifier(
            hidden_layer_sizes=(256,), 
            activation='relu', 
            solver='adam', 
            max_iter=1000, 
            early_stopping=True,
            random_state=42
        ))
    ])
    
    # Wrap the entire pipeline in the MultiOutputClassifier
    model = MultiOutputClassifier(base_estimator)
    
    model.fit(X_train, y_train)

    print("\n📈 Step 3: Evaluating Model Performance on Unseen Test Data...")
    y_pred = model.predict(X_test)
    
    # Print the scorecard!
    print("="*60)
    print("🏆 SUPERVISED MODEL PERFORMANCE")
    print("="*60)
    print(classification_report(y_test, y_pred, target_names=target_names, zero_division=0))

    print("\n💾 Step 4: Saving Model Artifacts...")
    os.makedirs("src/ml/models", exist_ok=True)
    
    # Save the trained weights
    joblib.dump(model, "src/ml/models/linear_probe_model.pkl")
    # Save the target names so your dashboard knows which prediction is which
    joblib.dump(target_names, "src/ml/models/target_names.pkl")
    
    print("✅ Supervised Model successfully trained and saved!")

if __name__ == "__main__":
    train_and_save_model()