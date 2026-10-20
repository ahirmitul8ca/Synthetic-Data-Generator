
import json
import sys
import os
from data_designer.interface import DataDesigner
import data_designer.config as dd

# Import your file manager helper functions
from File_Manager import ensure_directories, get_target_file_path, SCHEMAS_DIR, SYNTHETIC_DATA_DIR




if __name__ == "__main__":
    # ==========================================
    # 1. CONFIGURATION & CLI ARGUMENTS
    # ==========================================
    schema_filename = "columns_registry.json"
    num_records = 50000

    if len(sys.argv) > 1:
        schema_filename = sys.argv[1]
    
    if len(sys.argv) > 2:
        try:
            num_records = int(sys.argv[2])
        except ValueError:
            print("Warning: Invalid record count provided. Defaulting to 50,000.")

    # ==========================================
    # 2. ENSURE DIRECTORIES EXIST
    # ==========================================
    ensure_directories()  # Checks and builds logs, exports, data, archive, synthetic_data

    # Build schema file path
    registry_path = os.path.join(SCHEMAS_DIR, schema_filename)
    print(f"\nLoading schema from '{registry_path}'...")
    print(f"Target record volume: {num_records:,} rows using local Ollama (gemma4:e4b)...")

    # ==========================================
    # 3. LOAD SCHEMA CONFIGURATION
    # ==========================================
    try:
        with open(registry_path, "r") as f:
            registry_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: Could not find schema file at '{registry_path}'.")
        sys.exit(1)

    # ==========================================
    # 4. MODEL CONFIGURATION & EXECUTION
    # ==========================================
    model_configs = [
        dd.ModelConfig(
            alias="local-ollama",
            model="gemma4:e4b",
            provider="openai",
        )
    ]

    model_providers = [
        dd.ModelProvider(
            name="openai",
            endpoint="http://127.0.0.1:11434/v1",
            provider_type="openai",
            api_key="ollama",
        )
    ]

    config_builder = dd.DataDesignerConfigBuilder(model_configs=model_configs)
    
    for col in registry_data.get("columns", []):
        if col["type"] == "sampler":
            config_builder.add_column(
                dd.SamplerColumnConfig(
                    name=col["name"],
                    sampler_type=dd.SamplerType.CATEGORY,
                    params=dd.CategorySamplerParams(values=col["values"]),
                )
            )
        elif col["type"] == "llm_text":
            config_builder.add_column(
                dd.LLMTextColumnConfig(
                    name=col["name"],
                    model_alias=col["model_alias"],
                    prompt=col["prompt"],
                )
            )

    data_designer = DataDesigner(model_providers=model_providers)
    
    print("\nRunning pipeline at scale...")
    dataset_result = data_designer.create(
        config_builder, 
        num_records=num_records, 
        dataset_name="ledger_routing_dataset"
    )

    # ==========================================
    # 5. EXPORT WITH TIMESTAMPED FILENAME
    # ==========================================
    base_name = os.path.splitext(schema_filename)[0]
    
    # Generate dynamic output path with a date timestamp (e.g., synthetic_data/columns_registry_2026-06-06.csv)
    output_path = get_target_file_path(
        prefix=base_name, 
        target_folder=SYNTHETIC_DATA_DIR, 
        extension="csv",
        include_time=False  # Set to True if you want hour-minute-second uniqueness
    )

    dataset_result.to_csv(output_path)
    print(f"\nSuccessfully generated and saved {num_records:,} rows to '{output_path}'!")