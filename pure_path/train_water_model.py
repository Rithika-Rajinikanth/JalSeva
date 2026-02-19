import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from xgboost import XGBClassifier
import pickle

# Load dataset
data = pd.read_csv(r"C:\pure_path\merge_csv_files.csv")

# Features
X = data[[
    "latitude",
    "longitude",
    "rainfall_mm",
    "groundwater_level",
    "reservoir_percent"
]]

# Target
y = data["water_scarcity"]

# Split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# Train model
model = XGBClassifier()
model.fit(X_train, y_train)

print("Model trained successfully")

# Accuracy
y_pred = model.predict(X_test)
print("Accuracy:", accuracy_score(y_test, y_pred))

# Save model
pickle.dump(model, open(r"C:\pure_path\water_model.pkl", "wb"))

# Correct prediction input (5 features only)
new_alert = [[13.0827, 80.2707, 10, 2.5, 25]]

prediction = model.predict(new_alert)

if prediction[0] == 1:
    print("HIGH RISK → Escalate")
else:
    print("LOW RISK → Safe")
