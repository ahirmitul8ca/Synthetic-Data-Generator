import json
import glob
import pandas as pd
import data_designer.config as dd
from data_designer.interface import DataDesigner

# Import centralized path utilities and your custom directory helper from File_Manager
from File_Manager import ensure_directories, SCHEMAS_DIR, create_parquet_timestamped_dir

def main():
    ensure_directories()
    
    # 1. Create a dynamic timestamped folder using your custom function (appends hours and minutes)
    run_output_dir = create_parquet_timestamped_dir("double_ledger_parquet")
    print(f"📁 Created timestamped Parquet folder: {run_output_dir}")

    # 2. Locate and load your JSON schema file
    schema_path = SCHEMAS_DIR / "Double_ledger.json"
    print(f"Loading schema configuration dynamically from: {schema_path}")

    if not schema_path.exists():
        raise FileNotFoundError(f"Could not find schema file at: {schema_path}")

    with open(schema_path, "r", encoding="utf-8") as f:
        schema_data = json.load(f)

    # 3. Initialize configuration builder and map columns
    config_builder = dd.DataDesignerConfigBuilder()
    columns = schema_data.get("columns", [])
    
    for col in columns:
        col_name = col.get("name")
        col_type = col.get("type")
        
        if not col_name:
            continue

        if col_type == "sampler":
            sampler_type = col.get("sampler_type", "category").lower()
            values = col.get("values", ["Default"])
            
            config_builder.add_column(
                dd.SamplerColumnConfig(
                    name=col_name,
                    sampler_type=dd.SamplerType.CATEGORY,
                    params=dd.CategorySamplerParams(values=values),
                )
            )

    # 4. Configure run settings
    run_config = dd.RunConfig(buffer_size=1000)
    designer = DataDesigner()
    designer.set_run_config(run_config)

    print("🚀 Starting high-speed dynamic synthetic data generation pipeline...")
    
    # 5. Generate 50,000 records directly into the timestamped folder path
    designer.create(
        config_builder=config_builder, 
        num_records=50000, 
        dataset_name="double_ledger_output",
        artifact_path=str(run_output_dir)
    )
    
    print(f"✅ Generation complete. Consolidating chunks into a single Parquet file...")

    # 6. Automatically bundle all chunks inside this timestamp folder into one clean Parquet file
    parquet_files = glob.glob(str(run_output_dir / "**/*.parquet"), recursive=True)
    
    if parquet_files:
        df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
        single_parquet_path = run_output_dir / "double_ledger_complete.parquet"
        df.to_parquet(single_parquet_path, index=False)
        print(f"📦 Successfully created single consolidated Parquet file at: {single_parquet_path}")

if __name__ == "__main__":
    main()