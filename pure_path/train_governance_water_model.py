import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from xgboost import XGBClassifier
import pickle

# Load dataset
data = pd.read_csv(r"C:\Pure_path\merge_water_data.csv")

print("Dataset loaded:", len(data), "rows")

# Features (environment + governance)
X = data[[
    "latitude",
    "longitude",
    "rainfall_mm",
    "groundwater_level",
    "reservoir_percent",
    "escalation_count",
    "response_delay_days",
    "funding_allocated",
    "issue_reported"
]]

# Target
y = data["water_scarcity"]

# Split data
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# Create model
model = XGBClassifier(
    n_estimators=200,
    max_depth=6,
    learning_rate=0.05
)

# Train model
model.fit(X_train, y_train)

print("Model trained successfully")

# Test model
y_pred = model.predict(X_test)

accuracy = accuracy_score(y_test, y_pred)

print("Accuracy:", accuracy)

# Save model
pickle.dump(model, open(r"C:\pure_path\water_governance_model.pkl", "wb"))

print("Model saved")
