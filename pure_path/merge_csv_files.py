import pandas as pd
import glob
import os

# Correct folder path
folder_path = r"C:\pure_path"

output_file = r"C:\pure_path\merge_csv_files.csv"

csv_files = glob.glob(os.path.join(folder_path, "*.csv"))

print("Found CSV files:", len(csv_files))

df_list = []

for file in csv_files:
    print("Reading:", file)
    
    try:
        df = pd.read_csv(file, encoding="latin1")
        df["source_file"] = os.path.basename(file)
        df_list.append(df)
        
    except Exception as e:
        print("Skipped:", file)
        print("Error:", e)

if len(df_list) > 0:
    
    merged_df = pd.concat(df_list, ignore_index=True)
    
    merged_df.to_csv(output_file, index=False)
    
    print("\nSUCCESS!")
    print("Saved at:", output_file)

else:
    print("No valid CSV files found.")
