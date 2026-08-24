#!/usr/bin/env python3
"""
Find all SWE-bench Pro instances where the 'interface' key is not equal to "No new interfaces are introduced".

Usage:
    python find_swebench_pro_with_interfaces.py
    python find_swebench_pro_with_interfaces.py --output instances_with_interfaces.txt
    python find_swebench_pro_with_interfaces.py --split dev
"""
import argparse
import sys

try:
    from datasets import load_dataset
    DATASETS_AVAILABLE = True
except ImportError:
    DATASETS_AVAILABLE = False
    print("Error: 'datasets' library is required. Install with: pip install datasets")
    sys.exit(1)

def find_instances_with_interfaces(split='test'):
    """
    Find all instances where interface is not "No new interfaces are introduced".
    
    Args:
        split: Dataset split ('test' or 'dev')
    
    Returns:
        list: List of instance IDs with non-default interfaces
    """
    print(f"Loading SWE-bench Pro ({split} split)...")
    try:
        dataset = load_dataset('ScaleAI/SWE-bench_Pro', split=split)
    except Exception as e:
        print(f"Error loading dataset: {str(e)}")
        sys.exit(1)
    
    print(f"Scanning {len(dataset)} instances...")
    
    instances_with_interfaces = []
    no_interface_key = []
    
    for instance in dataset:
        instance_id = instance.get("instance_id", "N/A")
        interface = instance.get("interface", None)
        
        # Check if interface key exists
        if interface is None:
            no_interface_key.append(instance_id)
            continue
        
        # Check if interface is not the default message
        if interface != "No new interfaces are introduced":
            instances_with_interfaces.append({
                'instance_id': instance_id,
                'interface': interface
            })
    
    return instances_with_interfaces, no_interface_key

def print_results(instances_with_interfaces, no_interface_key, output_file=None):
    """Print the results."""
    output_lines = []
    
    output_lines.append("=" * 80)
    output_lines.append("SWE-BENCH PRO INSTANCES WITH NEW INTERFACES")
    output_lines.append("=" * 80)
    output_lines.append("")
    
    if instances_with_interfaces:
        output_lines.append(f"Found {len(instances_with_interfaces)} instances with new interfaces:\n")
        
        for item in instances_with_interfaces:
            output_lines.append(f"Instance: {item['instance_id']}")
            output_lines.append(f"Interface: {item['interface']}")
            output_lines.append("-" * 80)
    else:
        output_lines.append("No instances found with new interfaces.")
    
    output_lines.append("")
    output_lines.append("=" * 80)
    output_lines.append(f"SUMMARY")
    output_lines.append("=" * 80)
    output_lines.append(f"Instances with new interfaces: {len(instances_with_interfaces)}")
    output_lines.append(f"Instances without 'interface' key: {len(no_interface_key)}")
    output_lines.append("=" * 80)
    
    if no_interface_key:
        output_lines.append("")
        output_lines.append("Note: The following instances do not have an 'interface' key:")
        for inst_id in no_interface_key[:10]:  # Show first 10
            output_lines.append(f"  - {inst_id}")
        if len(no_interface_key) > 10:
            output_lines.append(f"  ... and {len(no_interface_key) - 10} more")
    
    output_text = "\n".join(output_lines)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output_text)
        print(f"Results written to: {output_file}")
        print(f"Total instances with new interfaces: {len(instances_with_interfaces)}")
    else:
        print(output_text)

def print_instance_ids_only(instances_with_interfaces, output_file=None):
    """Print only the instance IDs."""
    instance_ids = [item['instance_id'] for item in instances_with_interfaces]
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            for inst_id in instance_ids:
                f.write(f"{inst_id}\n")
        print(f"Instance IDs written to: {output_file}")
        print(f"Total: {len(instance_ids)} instances")
    else:
        for inst_id in instance_ids:
            print(inst_id)
        print(f"\nTotal: {len(instance_ids)} instances")

def main():
    parser = argparse.ArgumentParser(
        description='Find SWE-bench Pro instances with new interfaces',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Print all instances with new interfaces (detailed)
  %(prog)s
  
  # Print only instance IDs
  %(prog)s --ids-only
  
  # Save to file
  %(prog)s --output instances_with_interfaces.txt
  
  # Save only IDs to file
  %(prog)s --ids-only --output instance_ids.txt
  
  # Use dev split
  %(prog)s --split dev
        """
    )
    
    parser.add_argument(
        '--split', '-s',
        type=str,
        default='test',
        choices=['test', 'dev'],
        help='Dataset split (default: test)'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        help='Write output to file'
    )
    
    parser.add_argument(
        '--ids-only',
        action='store_true',
        help='Print only instance IDs (one per line)'
    )
    
    args = parser.parse_args()
    
    # Find instances
    instances_with_interfaces, no_interface_key = find_instances_with_interfaces(args.split)
    
    # Print results
    if args.ids_only:
        print_instance_ids_only(instances_with_interfaces, args.output)
    else:
        print_results(instances_with_interfaces, no_interface_key, args.output)

if __name__ == "__main__":
    main()

# Made with Bob
