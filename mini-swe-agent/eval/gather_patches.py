#!/usr/bin/env python3
"""
Script to gather patches from a results directory and format them for swe_bench_pro_eval.py.

Supports two output formats:
  - SWE-agent:      instance folders containing *.pred files
  - mini-SWE-agent: a preds.json at the top of the output dir (written by mini-swe-agent
                    automatically), with individual *.traj.json files as fallback

Usage:
    python gather_patches.py --directory <path> --prefix <prefix> --output <output_file>

Examples:
    # From SWE-agent results directory (uses .pred files)
    python gather_patches.py --directory swe_bench_pro_results/sample1 --prefix sample1 --output sample1_patches.json

    # From mini-SWE-agent results directory (uses preds.json / .traj.json files)
    python gather_patches.py --directory /path/to/mini-swe-agent/output/run_name --prefix run1 --output run1_patches.json
"""

import argparse
import json
from pathlib import Path
from typing import List, Dict, Optional


def find_pred_file(directory: Path, instance_id: str) -> Optional[Path]:
    """
    Find the .pred file in a directory.
    
    Args:
        directory: The directory to search
        instance_id: The instance_id to look for
        
    Returns:
        Path to the .pred file or None if not found
    """
    # Look for files matching the pattern: <instance_id>*.pred
    pred_files = list(directory.glob(f"{instance_id}*.pred"))
    if pred_files:
        return pred_files[0]
    
    pred_files = list(directory.glob("*.pred"))
    if pred_files:
        return pred_files[0]
    
    return None


def gather_patches_from_local(directory: str, prefix: str) -> List[Dict[str, str]]:
    """
    Gather patches from a local directory.
    
    Args:
        directory: Path to the directory containing instance folders
        prefix: Prefix to add to each patch entry
        
    Returns:
        List of patch dictionaries
    """
    patches = []
    directory_path = Path(directory)
    
    if not directory_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    
    for item in sorted(directory_path.iterdir()):
        if not item.is_dir():
            continue
        
        if not item.name.startswith('instance_'):
            continue
        
        pred_file = find_pred_file(item, item.name)
        if not pred_file:
            print(f"Warning: No .pred file found in {item.name}")
            continue
        
        try:
            with open(pred_file, 'r') as f:
                content = f.read()
            
            instance_id = None
            patch_content = content
            
            try:
                pred_data = json.loads(content)
                
                if 'instance_id' in pred_data:
                    instance_id = pred_data['instance_id']
                
                if 'model_patch' in pred_data:
                    patch_content = pred_data['model_patch']
                elif 'patch' in pred_data:
                    patch_content = pred_data['patch']
                    
            except json.JSONDecodeError:
                pass
            
            if not instance_id:
                instance_id = item.name
                print(f"Warning: Using folder name as instance_id for {item.name}")
            
            patches.append({
                "instance_id": instance_id,
                "patch": patch_content,
                "prefix": prefix
            })
        except Exception as e:
            print(f"Error reading {pred_file}: {e}")
    
    return patches


def gather_patches_from_minisweagent(directory: str, prefix: str) -> List[Dict[str, str]]:
    """
    Gather patches from a mini-SWE-agent output directory.

    mini-SWE-agent writes a preds.json at the top level:
        {
            "<instance_id>": {
                "model_name_or_path": "...",
                "instance_id": "...",
                "model_patch": "<git diff output>"
            },
            ...
        }
    If preds.json is absent, falls back to reading info.submission from each
    *.traj.json inside per-instance subdirectories.

    Args:
        directory: Path to the mini-SWE-agent output directory
        prefix: Prefix to add to each patch entry

    Returns:
        List of patch dictionaries
    """
    patches = []
    directory_path = Path(directory)

    if not directory_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    preds_path = directory_path / "preds.json"

    if preds_path.exists():
        # Fast path: read the consolidated preds.json
        with open(preds_path) as f:
            preds = json.load(f)
        for instance_id, entry in preds.items():
            patches.append({
                "instance_id": instance_id,
                "model_patch": entry.get("model_patch", ""),
                "prefix": prefix,
            })
        print(f"Loaded {len(patches)} patches from {preds_path}")
    else:
        # Fallback: read info.submission from individual *.traj.json files
        print(f"No preds.json found in {directory}, falling back to *.traj.json files")
        for item in sorted(directory_path.iterdir()):
            if not item.is_dir() or not item.name.startswith("instance_"):
                continue
            traj_files = list(item.glob("*.traj.json"))
            if not traj_files:
                print(f"Warning: No .traj.json file found in {item.name}")
                continue
            traj_file = traj_files[0]
            try:
                with open(traj_file) as f:
                    traj = json.load(f)
                instance_id = traj.get("instance_id") or item.name
                submission = traj.get("info", {}).get("submission", "")
                patches.append({
                    "instance_id": instance_id,
                    "model_patch": submission,
                    "prefix": prefix,
                })
            except Exception as e:
                print(f"Error reading {traj_file}: {e}")

    return patches


def main():
    parser = argparse.ArgumentParser(
        description='Gather patches and format them for swe_bench_pro_eval.py',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--directory',
        type=str,
        required=True,
        help='Output directory to gather patches from'
    )
    parser.add_argument(
        '--prefix',
        type=str,
        required=True,
        help='Prefix to add to each patch entry'
    )
    parser.add_argument(
        '--output',
        type=str,
        required=True,
        help='Output JSON file path'
    )
    parser.add_argument(
        '--mini',
        action='store_true',
        default=False,
        help='Read from mini-SWE-agent output (preds.json / *.traj.json) instead of *.pred files'
    )

    args = parser.parse_args()

    if args.mini:
        patches = gather_patches_from_minisweagent(args.directory, args.prefix)
    else:
        patches = gather_patches_from_local(args.directory, args.prefix)
    
    print(f"Found {len(patches)} patches, writing to {args.output}")
    
    with open(args.output, 'w') as f:
        json.dump(patches, f, indent=2)


if __name__ == '__main__':
    main()
