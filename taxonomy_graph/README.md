# Hint Taxonomy Diagram Generator

Generate Hasse diagrams for hint taxonomies from YAML configuration files.

## Features

- **YAML-based configuration**: Define categories and relations in easy-to-edit YAML files
- **Automatic layout optimization**: Minimizes edge crossings by positioning children near parents
- **Multiple output formats**: Generates both PNG and SVG files
- **Configurable output**: Plots saved to `plots/` directory with names based on config file
- **Transitive reduction**: Automatically removes redundant edges to create clean Hasse diagrams

## Installation

Ensure you have the required dependencies:

```bash
pip install networkx matplotlib pyyaml
```

## Usage

### Basic Usage

Generate diagrams from the default config file:

```bash
python draw_hint_taxonomy_plt.py
```

This will:
- Load `config/hint_taxonomy_config.yaml`
- Generate diagrams in the `plots/hint_taxonomy_config/` directory
- Create files: `hint_taxonomy_config_hasse.png/svg` and `hint_taxonomy_config_raw_vs_hasse.png/svg`

### Custom Config File

Use a different configuration file:

```bash
python draw_hint_taxonomy_plt.py config/my_taxonomy.yaml
```

Output files will be saved in `plots/my_taxonomy/` directory

### Custom Output Directory

Specify a different output directory:

```bash
python draw_hint_taxonomy_plt.py --output-dir my_plots
```

## Configuration File Format

Create a YAML file with the following structure:

```yaml
# Define categories (nodes)
categories:
  NodeKey1: "Node Label 1"
  NodeKey2: "Node Label 2"
  NodeKey3: "Node Label 3"

# Define relations (edges)
# Format: [parent, child] means parent ⪯ child (child is more specific)
relations:
  - ["NodeKey1", "NodeKey2"]
  - ["NodeKey2", "NodeKey3"]
```

### Example

See `config/hint_taxonomy_config.yaml` for a complete example:

```yaml
categories:
  Func: "Function"
  Name: "Name"
  Sign: "Signature"
  # ... more categories

relations:
  - ["Func", "Name"]
  - ["Func", "Sign"]
  - ["Sign", "InS"]
  # ... more relations
```

## Output Files

The script generates two types of diagrams in `plots/<config_name>/`:

1. **Hasse Diagram** (`<config_name>_hasse.png/svg`)
   - Clean, minimal representation showing only essential relationships
   - Arrows indicate hierarchy direction (parent → child)

2. **Raw vs Hasse Comparison** (`<config_name>_raw_vs_hasse.png/svg`)
   - Diagnostic diagram showing:
     - Solid black edges: Essential relations kept in Hasse diagram
     - Dashed gray edges: Redundant transitive relations removed
   - Useful for understanding which edges were simplified

Each config file gets its own subdirectory in `plots/` with filenames matching the config name.

## Features Explained

### Transitive Reduction

The script automatically removes redundant edges. For example:
- If you have: A → B, B → C, and A → C
- The Hasse diagram will only show: A → B and B → C
- The A → C edge is redundant (implied by transitivity)

### Layout Optimization

The layout algorithm:
- Positions nodes in ranks based on their distance from root nodes
- Places children near their parents to minimize edge crossings
- Centers each rank for visual balance
- Results in cleaner, more readable diagrams

## Command-Line Options

```
usage: draw_hint_taxonomy_plt.py [-h] [--output-dir OUTPUT_DIR] [config]

positional arguments:
  config                Path to YAML config file (default: config/hint_taxonomy_config.yaml)

optional arguments:
  -h, --help            show this help message and exit
  --output-dir OUTPUT_DIR
                        Output directory for plots (default: plots)
```

## Tips

1. **Organize your taxonomy**: Start with root concepts and build hierarchically
2. **Use meaningful keys**: Short keys (e.g., "Func", "Sign") for internal use
3. **Descriptive labels**: Full names (e.g., "Function", "Signature") for display
4. **Test incrementally**: Add relations gradually and check the output
5. **Check for redundancy**: The script will report removed redundant edges

## Example Workflow

1. Create or modify a YAML config file:
   ```yaml
   categories:
     Root: "Root Concept"
     Child1: "First Child"
     Child2: "Second Child"
   
   relations:
     - ["Root", "Child1"]
     - ["Root", "Child2"]
   ```

2. Generate diagrams:
   ```bash
   python draw_hint_taxonomy_plt.py config/my_config.yaml
   ```

3. Check the output in `plots/my_config/` directory

4. Iterate: Modify the YAML and regenerate as needed

## Directory Structure

```
workspace/
├── config/
│   ├── hint_taxonomy_config.yaml
│   └── my_taxonomy.yaml
├── plots/
│   ├── hint_taxonomy_config/
│   │   ├── hint_taxonomy_config_hasse.png
│   │   ├── hint_taxonomy_config_hasse.svg
│   │   ├── hint_taxonomy_config_raw_vs_hasse.png
│   │   └── hint_taxonomy_config_raw_vs_hasse.svg
│   └── my_taxonomy/
│       ├── my_taxonomy_hasse.png
│       ├── my_taxonomy_hasse.svg
│       ├── my_taxonomy_raw_vs_hasse.png
│       └── my_taxonomy_raw_vs_hasse.svg
├── draw_hint_taxonomy_plt.py
└── README.md
```