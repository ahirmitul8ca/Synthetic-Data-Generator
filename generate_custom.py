import json
import os
from pathlib import Path
import ollama

# Define paths matching your project layout
BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "Columns_Json" / "Double_ledger.json"
OUTPUT_DIR = BASE_DIR / "Synthetic_Data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_schema():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_synthetic_data(num_records=5):
    print(f"Loading schema from {SCHEMA_PATH}...")
    schema = load_schema()
    
    print(f"Generating {num_records} rows using local Ollama model 'gemma4:e4b'...")
    
    prompt = f"""
    Generate a JSON list of exactly {num_records} synthetic records based on this schema specification:
    {json.dumps(schema, indent=2)}
    
    Return ONLY a valid JSON array containing the objects. Do not include markdown code blocks or any extra text.
    """
    
    try:
        response = ollama.chat(
            model='gemma4:e4b',
            messages=[{'role': 'user', 'content': prompt}],
            options={'temperature': 0.7}
        )
        
        content = response['message']['content'].strip()
        
        # Clean potential markdown wrappers if returned
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        
        data = json.loads(content)
        
        output_file = OUTPUT_DIR / "Double_ledger_synthetic.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
        print(f"✅ Successfully generated and saved {len(data)} rows to {output_file}")
        
    except Exception as e:
        print(f"❌ Error during generation: {e}")

if __name__ == "__main__":
    generate_synthetic_data(5)