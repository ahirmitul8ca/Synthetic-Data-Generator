import json
import glob
import pandas as pd
import data_designer.config as dd
from data_designer.interface import DataDesigner

# Import path management and directory creation strictly from File_Manager
from File_Manager import ensure_directories, create_parquet_timestamped_dir, Double_Ledger_Schema_DIR

def main():
    # 1. Ensure root directories are set up via File_Manager
    ensure_directories()
    
    # 2. Create the timestamped folder using File_Manager's custom helper function
    run_output_dir = create_parquet_timestamped_dir("double_ledger_parquet")
    print(f"📁 Created timestamped Parquet folder: {run_output_dir}")

    # 3. Locate all JSON schema files inside the schema directory managed by File_Manager
    schema_files = list(Double_Ledger_Schema_DIR.glob("*.json"))
    
    if not schema_files:
        raise FileNotFoundError(f"No JSON schema files found in directory: {Double_Ledger_Schema_DIR}")
    
    print(f"Found {len(schema_files)} schema configuration file(s) to process.")

    designer = DataDesigner()

    # 4. Loop through every schema file dynamically
    for schema_path in schema_files:
        dataset_name = schema_path.stem  # e.g., 'merchants', 'accounts', 'payment_intents'
        print(f"\n--- Processing Table Schema: {dataset_name} ({schema_path.name}) ---")

        with open(schema_path, "r", encoding="utf-8") as f:
            schema_data = json.load(f)

        target_num_rows = schema_data.get("num_records", 50000)

        # Initialize configuration builder and map columns for this specific table
        config_builder = dd.DataDesignerConfigBuilder()
        columns = schema_data.get("columns", [])
        
        for col in columns:
            col_name = col.get("name")
            col_type = col.get("type")
            
            if not col_name:
                continue

            if col_type == "sampler":
                values = col.get("values", ["Default"])
                
                config_builder.add_column(
                    dd.SamplerColumnConfig(
                        name=col_name,
                        sampler_type=dd.SamplerType.CATEGORY,
                        params=dd.CategorySamplerParams(values=values),
                    )
                )
            elif col_type == "sequence":
                # Handle unique sequence/incrementing primary keys for transactional tables
                prefix = col.get("prefix", "")
                start = col.get("start", 1)
                
                config_builder.add_column(
                    dd.SequenceColumnConfig(
                        name=col_name,
                        prefix=prefix,
                        start=start
                    )
                )

        # Configure run settings
        run_config = dd.RunConfig(buffer_size=1000)
        designer.set_run_config(run_config)

        print(f"🚀 Generating synthetic data for {dataset_name}...")
        
        # 5. Generate 50,000 records directly into the File_Manager timestamped path
        designer.create(
            config_builder=config_builder, 
            num_records=target_num_rows, 
            dataset_name=dataset_name,
            artifact_path=str(run_output_dir)
        )
        
        print(f"✅ Generation complete for {dataset_name}. Consolidating chunks...")

        # 6. Bundle chunks into single Parquet and CSV files inside the managed directory
        parquet_files = glob.glob(str(run_output_dir / f"*{dataset_name}*.parquet"), recursive=True)
        if not parquet_files:
            parquet_files = glob.glob(str(run_output_dir / "**/*.parquet"), recursive=True)

        if parquet_files:
            df = pd.concat([pd.read_parquet(f) for f in parquet_files], ignore_index=True)
            
            # Save single consolidated Parquet
            single_parquet_path = run_output_dir / f"{dataset_name}_complete.parquet"
            df.to_parquet(single_parquet_path, index=False)
            
            # Save CSV export for your analytics engineering downstream
            single_csv_path = run_output_dir / f"{dataset_name}_complete.csv"
            df.to_csv(single_csv_path, index=False)
            
            print(f"📦 Successfully created consolidated Parquet: {single_parquet_path.name}")
            print(f"📄 Successfully created CSV export: {single_csv_path.name}")

    print("\n🎉 All multi-table schemas processed and exported successfully via File_Manager!")

if __name__ == "__main__":
    main()