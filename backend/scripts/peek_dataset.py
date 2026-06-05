import sys
from datasets import load_dataset

def main():
    print("Loading dataset...")
    dataset = load_dataset("KanoonGPT/indian-case-laws", data_dir="structured/v1", split="train", streaming=True)
    for item in dataset:
        print("Keys:", list(item.keys()))
        for k, v in item.items():
            val_str = str(v)
            print(f"{k}: {val_str[:100]}...")
        break

if __name__ == "__main__":
    main()
