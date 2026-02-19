import pickle
import pandas as pd

# Load model
model = pickle.load(open(r"C:\pure_path\water_governance_model.pkl", "rb"))

# New incoming report
new_report = pd.DataFrame([{
    "latitude": 13.08,
    "longitude": 80.27,
    "rainfall_mm": 8,
    "groundwater_level": 2.0,
    "reservoir_percent": 22,
    "escalation_count": 3,
    "response_delay_days": 15,
    "funding_allocated": 0,
    "issue_reported": 1
}])

prediction = model.predict(new_report)

print("\nAlert Status:")

if prediction[0] == 1:
    print("HIGH RISK")
    print("Action Required:")
    print("- Escalate to District Authority")
    print("- Assign responsible officer")
    print("- Require field validation")
else:
    print("LOW RISK")
    print("Monitor situation")
