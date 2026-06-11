import os
import json
import ast
import numpy as np
import pandas as pd
import joblib
from sqlalchemy import text
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier
from sklearn.multioutput import MultiOutputClassifier
from sklearn.metrics import classification_report, precision_recall_curve
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.pipeline import Pipeline

# Adjust import based on your actual path
from src.database.connection import get_engine

# --- DEFINE YOUR EXACT TARGET TAGS ---
# Pulled directly from your recent scorecard
TARGET_NAMES = [
    'chaotic', 'cinematic', 'comic_book_illustration', 'crisp_digital_portrait', 
    'handcrafted_diorama', 'has_cameo', 'is_trainer_gallery', 'kinetic', 
    'legendary', 'maximalist', 'minimalist', 'modern', 'neutral', 'pop_art', 
    'standard_generic', 'surrealist', 'traditional_hand_painted', 'whimsical'
]

def main():
    print("="*60)
    print("🚀 INITIALIZING MULTI-MODAL NEURAL NETWORK PIPELINE")
    print("="*60)

    # =========================================================================
    # STEP 1: LOAD & PREPARE MULTI-MODAL DATA (VISION + TEXT)
    # =========================================================================
    print("\n🧠 Step 1: Extracting Vision & Text Metadata from Database...")
    engine = get_engine()
    
    query = """
        SELECT tags, image_embedding, illustrator, has_trainer 
        FROM tcg_cards 
        WHERE tags IS NOT NULL 
        AND image_embedding IS NOT NULL
        AND supetype = 'Pokemon';
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
        
    if df.empty:
        print("❌ No labeled data found! Please label cards in the UI first.")
        return

    print(f"   ↳ Found {len(df)} fully verified human-labeled cards.")

    # 1A. Expand the 512-D Visual Embedding into separate columns
    print("   ↳ Unpacking 512-Dimensional Visual Vectors...")
    embeddings = np.array([ast.literal_eval(e) for e in df['image_embedding']])
    emb_cols = [f'emb_{i}' for i in range(512)]
    emb_df = pd.DataFrame(embeddings, columns=emb_cols)

    # 1B. Clean and format Text Metadata
    print("   ↳ Formatting Text Metadata (Illustrator & Trainer Flags)...")
    meta_df = df[['illustrator', 'has_trainer']].copy()
    meta_df['illustrator'] = meta_df['illustrator'].fillna('Unknown')
    meta_df['has_trainer'] = meta_df['has_trainer'].fillna(False).astype(int)

    # 1C. Combine into Master Feature Matrix (X)
    X = pd.concat([emb_df, meta_df], axis=1)

    # 1D. Extract Ground Truth Labels (y)
    y_data = []
    for tags_str in df['tags']:
        tags_dict = json.loads(tags_str) if isinstance(tags_str, str) else tags_str
        y_data.append([int(tags_dict.get(key, 0)) for key in TARGET_NAMES])
    y = pd.DataFrame(y_data, columns=TARGET_NAMES)


    # =========================================================================
    # STEP 2: BUILD MULTI-MODAL PIPELINE & TRAIN
    # =========================================================================
    print("\n⚙️ Step 2: Constructing Multi-Modal Architecture...")
    
    categorical_features = ['illustrator']
    numeric_features = ['has_trainer']

    # The ColumnTransformer is the "Traffic Controller". It routes different 
    # data types to different mathematical processors before they hit the brain.
    preprocessor = ColumnTransformer(
        transformers=[
            ('vision_scaler', StandardScaler(), emb_cols),
            ('text_encoder', OneHotEncoder(handle_unknown='ignore'), categorical_features), 
            ('numeric_passthrough', 'passthrough', numeric_features)
        ]
    )

    # The Neural Network Pipeline
    base_estimator = Pipeline([
        ('preprocessor', preprocessor),
        ('mlp', MLPClassifier(
            hidden_layer_sizes=(256, 128), # Dual-layer to handle text + vision
            activation='relu', 
            solver='adam', 
            max_iter=1000, 
            early_stopping=True,
            random_state=42
        ))
    ])
    
    model = MultiOutputClassifier(base_estimator)
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    print(f"   ↳ Training on {len(X_train)} samples, Validating on {len(X_test)} samples...")
    model.fit(X_train, y_train)
    print("   ✅ Training Complete!")


    # =========================================================================
    # STEP 3: AUTO-TUNE THRESHOLDS & EVALUATE
    # =========================================================================
    print("\n📈 Step 3: Auto-Tuning Optimal Thresholds per Class...")
    
    y_probs = model.predict_proba(X_test)
    y_pred_custom = np.zeros(y_test.shape)
    optimal_thresholds = {}

    for i, class_name in enumerate(TARGET_NAMES):
        # Extract probabilities and true labels for this specific class
        probs = y_probs[i][:, 1]
        true_labels = y_test.iloc[:, i].values
        
        # Calculate all possible thresholds and their resulting F1 scores
        precisions, recalls, thresholds = precision_recall_curve(true_labels, probs)
        
        # Avoid division by zero warnings
        numerator = 2 * (precisions * recalls)
        denominator = (precisions + recalls)
        f1_scores = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator!=0)
        
        # Find the threshold that yields the absolute highest F1-score for this class
        best_idx = np.argmax(f1_scores)
        best_threshold = thresholds[best_idx] if best_idx < len(thresholds) else 0.5
        
        # Prevent the threshold from being too extreme (cap between 0.15 and 0.85)
        best_threshold = max(0.15, min(0.85, best_threshold))
        optimal_thresholds[class_name] = round(float(best_threshold), 3)
        
        # Apply this specific threshold to our predictions
        y_pred_custom[:, i] = (probs >= best_threshold).astype(int)

    # Print the specific thresholds so you can see the model's logic
    print("\n🧠 Auto-Calculated Thresholds:")
    for k, v in optimal_thresholds.items():
        print(f"   {k}: {v:.3f}")

    print("\n" + "="*60)
    print("🏆 OPTIMIZED MODEL PERFORMANCE (Bespoke Thresholds)")
    print("="*60)
    print(classification_report(y_test, y_pred_custom, target_names=TARGET_NAMES, zero_division=0))


    # =========================================================================
    # STEP 4: SAVE ARTIFACTS FOR STREAMLIT UI
    # =========================================================================
    os.makedirs("src/ml/models", exist_ok=True)
    
    # Save the Neural Network
    model_path = "src/ml/models/custom_classifier.pkl"
    joblib.dump(model, model_path)
    
    # Save the Thresholds Dictionary
    threshold_path = "src/ml/models/optimal_thresholds.json"
    with open(threshold_path, "w") as f:
        json.dump(optimal_thresholds, f, indent=4)
        
    print(f"\n💾 Model and custom thresholds successfully saved to src/ml/models/")

if __name__ == "__main__":
    main()