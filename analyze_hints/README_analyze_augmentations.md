# Augmentation Data Analyzer

## Overview
A utility script to analyze the structure of augmentation data in the NoCode-bench dataset. It identifies all unique keys, their frequencies, and different key combinations present in the augmentation data field.

## Purpose
The NoCode-bench dataset has an `augmentations` field with a `data` key containing a list of items. These items may have different keys across instances. This script helps you understand:
- What keys exist in the augmentation data
- How frequently each key appears
- What combinations of keys are used
- Examples of each key combination

## Installation

```bash
pip install datasets rich
```

## Usage

### Basic Analysis
```bash
python analyze_augmentations.py
```

### Analyze Specific Instance
```bash
python analyze_augmentations.py --instance pytest-dev__pytest-2794
```

### Show More Examples
```bash
python analyze_augmentations.py --examples 10
```

### Export Results to JSON
```bash
python analyze_augmentations.py --export augmentation_report.json
```

### Use Different Split
```bash
python analyze_augmentations.py --split train
```

## Command-Line Arguments

| Argument | Short | Description | Default |
|----------|-------|-------------|---------|
| `--benchmark` | `-b` | Benchmark name | `nocode` |
| `--split` | `-s` | Dataset split (test/train/validation) | `test` |
| `--examples` | `-e` | Number of detailed examples to show | `5` |
| `--export` | `-o` | Export analysis to JSON file | None |
| `--instance` | `-i` | Analyze specific instance only | None |

## Output

### 1. Analysis Summary
Shows:
- Total number of instances
- Instances with augmentations
- Total augmentation items
- Number of unique keys found

### 2. Key Frequency Distribution
A table showing:
- Each unique key
- Number of occurrences
- Percentage of total items

### 3. Key Combinations
Lists all unique combinations of keys found, including:
- Keys in the combination
- Number of instances with this combination
- Example instance IDs
- Sample data for each combination

### 4. Detailed Examples
Shows full JSON structure of augmentation data items for different key combinations.

## Example Output

```
╭─────────────────────────────── Analysis Summary ───────────────────────────────╮
│ Total Instances: 500                                                           │
│ Instances with Augmentations: 450                                              │
│ Total Augmentation Items: 2500                                                 │
│ Unique Keys Found: 8                                                           │
╰────────────────────────────────────────────────────────────────────────────────╯

All Unique Keys in Augmentation Data:
  • type: 2500 occurrences (100.0%)
  • content: 2500 occurrences (100.0%)
  • source: 2400 occurrences (96.0%)
  • metadata: 1800 occurrences (72.0%)
  • timestamp: 1200 occurrences (48.0%)

Key Combinations Found: 5 unique combinations

Combination 1: (1500 instances)
  Keys: type, content, source, metadata
  Example instances: pytest-dev__pytest-2794, django__django-1234, ...
  Example from pytest-dev__pytest-2794:
    {
        "type": "test_case",
        "content": "def test_example(): ...",
        "source": "generated",
        "metadata": {"confidence": 0.95}
    }
```

## Export Format

When using `--export`, the script creates a JSON file with:

```json
{
  "all_keys": ["key1", "key2", ...],
  "key_frequency": {
    "key1": 100,
    "key2": 95,
    ...
  },
  "key_combinations": {
    "('key1', 'key2')": ["instance1", "instance2", ...],
    ...
  },
  "combination_examples": {
    "('key1', 'key2')": {
      "instance_id": "example-instance",
      "data": {...}
    },
    ...
  },
  "statistics": {
    "total_instances": 500,
    "instances_with_augmentations": 450,
    "total_augmentation_items": 2500,
    "unique_keys": 8,
    "unique_combinations": 5
  }
}
```

## Use Cases

### 1. Understanding Data Structure
Quickly understand what fields are available in augmentation data:
```bash
python analyze_augmentations.py
```

### 2. Validating Data Consistency
Check if all instances have the same augmentation structure:
```bash
python analyze_augmentations.py --export validation.json
```

### 3. Debugging Specific Instance
Examine augmentation data for a problematic instance:
```bash
python analyze_augmentations.py --instance pytest-dev__pytest-2794 --examples 10
```

### 4. Documentation
Generate documentation about augmentation data structure:
```bash
python analyze_augmentations.py --export augmentation_schema.json --examples 20
```

### 5. Data Quality Analysis
Identify missing or inconsistent fields:
```bash
python analyze_augmentations.py --split train --export train_analysis.json
python analyze_augmentations.py --split test --export test_analysis.json
# Compare the two files
```

## Tips

1. **Start with summary**: Run without arguments to get an overview
2. **Export for analysis**: Use `--export` to save results for further processing
3. **Check specific instances**: Use `--instance` to debug individual cases
4. **Compare splits**: Analyze train and test splits separately to ensure consistency
5. **Increase examples**: Use `--examples 20` to see more variety in data structures

## Integration with pretty_printing.py

You can use this script alongside `pretty_printing.py`:

```bash
# First, analyze augmentation structure
python analyze_augmentations.py --export aug_analysis.json

# Then, view specific augmentation data
python pretty_printing.py -i pytest-dev__pytest-2794 -k augmentations --plain
```

## Troubleshooting

### No augmentations found
If the script reports 0 instances with augmentations:
- Check that you're using the correct benchmark and split
- Verify the dataset has been loaded correctly
- Try a different split (train/test/validation)

### Memory issues with large datasets
For very large datasets:
- Analyze specific instances with `--instance`
- Process in batches by filtering the dataset
- Export to JSON and analyze offline

## Future Enhancements

Planned features:
- [ ] Statistical analysis of key value types
- [ ] Validation against expected schema
- [ ] Comparison between different splits
- [ ] Visualization of key distributions
- [ ] Automatic schema generation