# Pretty Printing Tool - Usage Guide

## Overview
A command-line tool for pretty printing benchmark instances with rich formatting support and plain text output for easy copying to files.

## Features
- ✅ **Configurable Benchmark**: Support for multiple benchmarks (currently: NoCode-bench, extensible for future benchmarks)
- ✅ **Configurable Instance ID**: Specify any instance from the benchmark
- ✅ **Configurable Keys**: Print single or multiple keys from an instance
- ✅ **Rich Formatting**: Syntax highlighting, panels, and visual separators
- ✅ **Plain Text Output**: Clean output suitable for copying to files (no formatting characters)
- ✅ **File Output**: Direct output to file with `--output` option
- ✅ **Multiple Display Styles**: JSON, tree, table, or patches view
- ✅ **List Instances**: Browse available instances in the benchmark

## Installation

```bash
pip install datasets rich
```

## Command-Line Usage

### Basic Usage

#### Print a single key
```bash
python pretty_printing.py --instance pytest-dev__pytest-2794 --key problem_statement
```

#### Print multiple keys
```bash
python pretty_printing.py --instance pytest-dev__pytest-2794 --key problem_statement feature_patch test_patch
```

### Advanced Options

#### Specify benchmark and split
```bash
python pretty_printing.py --benchmark nocode --split test --instance pytest-dev__pytest-2794 --key problem_statement
```

#### List all available instances
```bash
python pretty_printing.py --list-instances
```

#### List limited number of instances
```bash
python pretty_printing.py --list-instances --limit 10
```

#### Use different display styles
```bash
# Table view
python pretty_printing.py --instance pytest-dev__pytest-2794 --style table

# Tree view
python pretty_printing.py --instance pytest-dev__pytest-2794 --style tree

# JSON view
python pretty_printing.py --instance pytest-dev__pytest-2794 --style json

# Patches view (for diffs)
python pretty_printing.py --instance pytest-dev__pytest-2794 --style patches
```

#### Disable separators between keys
```bash
python pretty_printing.py --instance pytest-dev__pytest-2794 --key problem_statement feature_patch --no-separator
```

#### Plain text output (suitable for copying to files)
```bash
python pretty_printing.py --instance pytest-dev__pytest-2794 --key problem_statement feature_patch --plain
```

#### Save output directly to a file
```bash
python pretty_printing.py --instance pytest-dev__pytest-2794 --key problem_statement feature_patch --output output.txt
```

#### Save output to file (automatically uses plain text)
```bash
python pretty_printing.py --instance pytest-dev__pytest-2794 --key problem_statement feature_patch -o results.txt
```

## Command-Line Arguments

| Argument | Short | Description | Default |
|----------|-------|-------------|---------|
| `--benchmark` | `-b` | Benchmark name (nocode, etc.) | `nocode` |
| `--split` | `-s` | Dataset split (test/train/validation) | `test` |
| `--instance` | `-i` | Instance ID to print | Required* |
| `--key` | `-k` | Key(s) to print (space-separated) | Required** |
| `--list-instances` | `-l` | List all available instances | Flag |
| `--limit` | | Limit number of instances to list | None |
| `--no-separator` | | Disable visual separators | Flag |
| `--style` | | Display style (json/tree/table/patches) | None |
| `--plain` | | Output plain text without rich formatting | Flag |
| `--output` | `-o` | Write output to file (auto-enables plain) | None |

\* Required unless using `--list-instances`  
\** Required unless using `--style` or `--list-instances`

## Programmatic Usage

### Import and use functions directly

```python
from pretty_printing import (
    load_benchmark_dataset,
    print_instance_key,
    print_multiple_keys,
    print_instance
)

# Load a benchmark
dataset = load_benchmark_dataset('nocode', 'test')

# Print a single key
print_instance_key('pytest-dev__pytest-2794', 'problem_statement', dataset)

# Print multiple keys
print_multiple_keys(
    'pytest-dev__pytest-2794',
    ['problem_statement', 'feature_patch'],
    dataset=dataset,
    separator=True
)

# Print full instance with style
print_instance('pytest-dev__pytest-2794', style='table')
```

## Adding New Benchmarks

To add support for a new benchmark, modify the `load_benchmark_dataset` function:

```python
def load_benchmark_dataset(benchmark: str = 'nocode', split: str = 'test'):
    cache_key = f"{benchmark}_{split}"
    
    if cache_key in _dataset_cache:
        return _dataset_cache[cache_key]
    
    try:
        if benchmark.lower() == 'nocode':
            dataset = load_dataset('NoCode-bench/NoCode-bench_Verified', split=split)
        elif benchmark.lower() == 'swe-bench':
            # Add new benchmark here
            dataset = load_dataset('princeton-nlp/SWE-bench', split=split)
        else:
            raise ValueError(f"Unknown benchmark: {benchmark}")
        
        _dataset_cache[cache_key] = dataset
        return dataset
    except Exception as e:
        console.print(f"[red]Error loading benchmark '{benchmark}': {str(e)}[/red]")
        sys.exit(1)
```

## Examples

### Example 1: Quick inspection of a problem
```bash
python pretty_printing.py -i pytest-dev__pytest-2794 -k problem_statement
```

### Example 2: View all patches
```bash
python pretty_printing.py -i pytest-dev__pytest-2794 -k feature_patch test_patch
```

### Example 3: Full instance overview
```bash
python pretty_printing.py -i pytest-dev__pytest-2794 --style table
```

### Example 4: Browse available instances
```bash
python pretty_printing.py --list-instances --limit 20
```

### Example 5: Multiple keys without separators
```bash
python pretty_printing.py -i pytest-dev__pytest-2794 -k problem_statement feature_patch --no-separator
```

### Example 6: Plain text output for copying
```bash
python pretty_printing.py -i pytest-dev__pytest-2794 -k problem_statement --plain
```

### Example 7: Save to file
```bash
python pretty_printing.py -i pytest-dev__pytest-2794 -k problem_statement feature_patch -o output.txt
```

### Example 8: Plain text with multiple keys
```bash
python pretty_printing.py -i pytest-dev__pytest-2794 -k instance_id problem_statement feature_patch --plain
```

## Output Formats

### Rich Formatted Output (Default)
The default output uses the Rich library for beautiful terminal formatting:
- Colored syntax highlighting
- Bordered panels
- Visual separators
- Diff highlighting for patches

**Best for:** Interactive terminal use, quick inspection

### Plain Text Output (`--plain`)
Clean, unformatted text output without any special characters:
- No ANSI color codes
- No box-drawing characters
- Simple `=` separators
- Easy to copy and paste

**Best for:**
- Copying to documentation
- Saving to plain text files
- Piping to other tools
- Email or chat messages

**Example output:**
```
================================================================================
CONFIGURATION
================================================================================
Benchmark: nocode
Split: test
Instance: pytest-dev__pytest-2794
Keys: problem_statement, feature_patch
================================================================================

================================================================================
PROBLEM STATEMENT
================================================================================
[Content here...]
================================================================================
```

### File Output (`--output` or `-o`)
Automatically uses plain text format and writes to a file:
```bash
python pretty_printing.py -i pytest-dev__pytest-2794 -k problem_statement -o output.txt
```

After completion, displays: `Output written to: output.txt`

## Key Features Explained

### 1. Configurable Benchmark
The tool supports multiple benchmarks through the `--benchmark` flag. Currently supports:
- `nocode`: NoCode-bench dataset
- Future: Add more benchmarks as needed

### 2. Configurable Instance ID
Specify any instance ID from the benchmark using `--instance` or `-i`:
```bash
python pretty_printing.py -i your-instance-id -k problem_statement
```

### 3. Configurable Keys
Print one or more keys using `--key` or `-k`:
```bash
# Single key
python pretty_printing.py -i instance-id -k problem_statement

# Multiple keys
python pretty_printing.py -i instance-id -k problem_statement feature_patch test_patch
```

### 4. Plain Text Mode
Enable with `--plain` flag for clean output:
- No rich formatting or colors
- Simple text separators using `=` characters
- Perfect for copying to files or documentation
- Automatically enabled when using `--output`

### 5. File Output
Save directly to a file with `--output`:
- Automatically uses plain text format
- Creates or overwrites the specified file
- Displays confirmation message after writing
- UTF-8 encoding for international characters

### 6. Visual Formatting (Rich Mode)
- **Patches**: Displayed with diff syntax highlighting
- **Long text**: Shown in panels with syntax highlighting
- **JSON data**: Pretty-printed with syntax highlighting
- **Separators**: Visual dividers between multiple keys (can be disabled)

## Error Handling

The tool includes comprehensive error handling:
- Invalid instance IDs show available instances
- Missing keys display available keys for the instance
- Failed benchmark loads show clear error messages
- Graceful handling of missing or malformed data

## Performance

- **Dataset Caching**: Benchmarks are cached after first load
- **Efficient Printing**: Only requested keys are processed
- **Lazy Loading**: Data loaded on-demand

## Tips

1. Use `--list-instances` to discover available instances
2. Use `--style table` for a quick overview of all keys
3. Use `--style patches` to view diffs with proper highlighting
4. Combine `--key` with multiple keys to compare related data
5. Use `--no-separator` for compact output when piping to files
6. **Use `--plain` when copying output to documentation or files**
7. **Use `--output` to save directly to a file (auto-enables plain text)**
8. Combine `--plain` with `--no-separator` for ultra-compact output
9. Use `-o` as shorthand for `--output`

## Troubleshooting

### Issue: "Instance not found"
- Use `--list-instances` to see available instances
- Check spelling of instance ID
- Verify you're using the correct benchmark and split

### Issue: "Key not found"
- The tool will show available keys for the instance
- Check spelling of key name
- Use `--style table` to see all available keys

### Issue: Import errors
- Install required packages: `pip install datasets rich`
- Ensure you're using Python 3.9+

## Comparison: Rich vs Plain Output

| Feature | Rich (Default) | Plain (`--plain`) |
|---------|---------------|-------------------|
| Colors | ✅ Yes | ❌ No |
| Syntax highlighting | ✅ Yes | ❌ No |
| Box borders | ✅ Yes | ❌ No |
| Copy-paste friendly | ⚠️ Partial | ✅ Yes |
| File output | ⚠️ With formatting | ✅ Clean text |
| Terminal display | ✅ Beautiful | ✅ Simple |
| Piping to tools | ⚠️ May have issues | ✅ Works well |

## Use Cases

### When to use Rich formatting (default):
- Interactive terminal exploration
- Quick visual inspection
- Presentations or demos
- When you want beautiful output

### When to use Plain text (`--plain`):
- Copying to documentation
- Saving to text files
- Sharing via email/chat
- Piping to other command-line tools
- Creating reports
- Version control (git diff friendly)

### When to use File output (`--output`):
- Batch processing
- Automated scripts
- Creating documentation
- Archiving results
- Sharing with non-technical users

## Future Enhancements

Planned features:
- [ ] Support for SWE-bench and other benchmarks
- [ ] Export to markdown and HTML formats
- [ ] Search/filter instances by criteria
- [ ] Batch processing of multiple instances
- [ ] Custom output templates
- [ ] Interactive mode with prompts
- [ ] JSON export option