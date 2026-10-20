import glob
import pandas as pd
import File_Manager as fm
from pathlib import Path

# Import your custom project paths from File_Manager
from File_Manager import SYNTHETIC_DATA_DIR

def main():
    print("🔄 Scanning for generated Parquet output files...")
    
    # Find all generated parquet files recursively
    parquet_files = glob.glob(str(SYNTHETIC_DATA_DIR / "**/*.parquet"), recursive=True)
    
    if parquet_files:
        print(f"Found {len(parquet_files)} parquet chunk(s). Merging data...")
        # Read and combine all chunks into a single pandas DataFrame
        df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
        
        
        fnm=fm.get_timestamped_filename("Double_Ledger","csv",True)
        csv_output_path = SYNTHETIC_DATA_DIR / fnm
        df.to_csv(csv_output_path, index=False)
        print(f"✅ Successfully exported CSV to: {csv_output_path}")
    else:
        print(f"⚠️ No parquet files found in {SYNTHETIC_DATA_DIR}. Please run Double_Ledger_Gen.py first.")

if __name__ == "__main__":
    main()