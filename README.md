## TCG Card Art Labeler
A professional-grade data engineering and annotation platform designed to build high-quality ground-truth datasets for Pokémon TCG art classification.

This tool enables data analysts to rapidly curate and label card art styles and aesthetics, powering machine learning models that analyze the visual taxonomy of the Pokémon TCG.

## Key Features

1. **Integrated Pipeline:** Fully automated ingestion from the Pokémon TCG API, paired with a custom computer vision enrichment pipeline (CLIP + OWLv2).

2. **Structured Taxonomies:** Multi-dimensional labeling system supporting both "Art Styles" (minimalist, painterly, cinematic, etc.) and "Card Aesthetics" (kinetic, whimsical, legendary, etc.).

3. **Version-Controlled Ground Truth:** Supports side-by-side labeling experiments (v1, v2, etc.) to measure and improve model performance iteratively.

4. **Professional UI:** Built with Streamlit for a distraction-free, responsive labeling experience with features like auto-advancement, set-progress tracking, and dynamic visual navigation

## Pipeline Architecture
The system follows a modular ETL approach to ensure data integrity and model reproducibility.

1. **Ingestion:**  Python-based ingestion script fetches raw set metadata and pricing, storing them into a structured PostgreSQL database.

2. **Enrichment:**  An asynchronous worker processes images using CLIP (for style taxonomy) and OWLv2 (for object/cameo detection).

3. **Annotation:** The Streamlit dashboard serves as the human-in-the-loop layer, allowing for ground-truth validation against the ML model's initial predictions.

## Project Stucture
* src/ingest/: Core data ingestion, enrichment workers, and ML model wrappers.

* src/dashboard/: Streamlit web interface and labeling logic.

* config/: Configuration files for sets and taxonomy definitions.

* logs/: Pipeline execution logs for debugging ingestion failures.

## License
This project is for internal research and data analysis purposes.