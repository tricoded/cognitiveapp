# app/ml/intent_classifier.py

import os
import json
import pickle
import numpy as np
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

MODEL_PATH = Path("app/ml/models/intent_classifier.pkl")
LABEL_PATH = Path("app/ml/models/intent_labels.pkl")

class IntentClassifier:
    """
    Lightweight intent classifier using TF-IDF + Logistic Regression.
    Fast, explainable, works on CPU, no GPU needed.
    Upgradeable to DistilBERT later.
    """

    def __init__(self):
        self.model    = None
        self.encoder  = LabelEncoder()
        self.vectorizer = None
        self.is_trained = False
        self._load()

    def _load(self):
        if MODEL_PATH.exists() and LABEL_PATH.exists():
            with open(MODEL_PATH, "rb") as f:
                saved = pickle.load(f)
                self.model      = saved["model"]
                self.vectorizer = saved["vectorizer"]
            with open(LABEL_PATH, "rb") as f:
                self.encoder = pickle.load(f)
            self.is_trained = True

    def train(self, training_data: list[tuple[str, str]]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts  = [t[0] for t in training_data]
        labels = [t[1] for t in training_data]

        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 3),
            max_features=5000,
            sublinear_tf=True,
        )
        X = self.vectorizer.fit_transform(texts)
        y = self.encoder.fit_transform(labels)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42
        )

        self.model = LogisticRegression(
            max_iter=1000,
            C=5.0,
            class_weight="balanced",
        )
        self.model.fit(X_train, y_train)

        # Report
        y_pred = self.model.predict(X_test)
        print(classification_report(
            y_test, y_pred,
            target_names=self.encoder.classes_
        ))

        # Save
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MODEL_PATH, "wb") as f:
            pickle.dump({"model": self.model, "vectorizer": self.vectorizer}, f)
        with open(LABEL_PATH, "wb") as f:
            pickle.dump(self.encoder, f)

        self.is_trained = True
        return self

    def predict(self, message: str) -> tuple[str, float]:
        """Returns (intent, confidence_score)."""
        if not self.is_trained:
            return "general_chat", 0.0

        X = self.vectorizer.transform([message.lower()])
        proba  = self.model.predict_proba(X)[0]
        top_idx = np.argmax(proba)
        intent  = self.encoder.inverse_transform([top_idx])[0]
        confidence = proba[top_idx]

        # Low confidence → fall back to general_chat
        if confidence < 0.45:
            return "general_chat", confidence

        return intent, confidence


# Singleton
intent_clf = IntentClassifier()
