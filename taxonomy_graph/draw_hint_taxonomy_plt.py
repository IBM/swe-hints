import argparse
import os
import textwrap
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import yaml


def load_config(config_path):
    """Load taxonomy configuration from YAML file."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    categories = config['categories']
    relations = [tuple(rel) for rel in config['relations']]
    
    return categories, relations


def build_relation_graph(categories, relations):
    G = nx.DiGraph()

    for node, label in categories.items():
        G.add_node(node, label=label)

    G.add_edges_from(relations)

    if not nx.is_directed_acyclic_graph(G):
        raise ValueError("The relation graph has a cycle, so it is not a valid poset.")

    return G


def hasse_graph(G):
    """
    Convert the raw relation graph into its Hasse diagram.

    This removes redundant transitive edges like:
      C5 -> C8
    when paths like:
      C5 -> C6 -> C8
    already exist.
    """
    H = nx.transitive_reduction(G)

    # transitive_reduction preserves nodes/edges but not necessarily attributes.
    for node, data in G.nodes(data=True):
        H.nodes[node].update(data)

    return H


def compute_ranks(G):
    """
    Rank by longest distance from a minimal node.
    Lower rank = less revealing / less specific.
    """
    ranks = {node: 0 for node in G.nodes}

    for node in nx.topological_sort(G):
        preds = list(G.predecessors(node))
        if preds:
            ranks[node] = max(ranks[pred] + 1 for pred in preds)

    return ranks


def ranked_layout(G):
    """
    Improved Hasse-style layout that minimizes edge crossings:
    - y coordinate is rank
    - nodes positioned near their parents to reduce crossings
    - automatically adjusts spacing based on graph size
    """
    ranks = compute_ranks(G)

    by_rank = defaultdict(list)
    for node, rank in ranks.items():
        by_rank[rank].append(node)

    # Calculate max nodes in any rank to determine spacing
    max_nodes_in_rank = max(len(nodes) for nodes in by_rank.values())
    
    # Adaptive spacing: more nodes = tighter spacing, but with minimum
    x_gap = max(2.5, min(4.0, 30.0 / max_nodes_in_rank))
    y_gap = 2.0

    pos = {}
    
    # Process ranks from bottom to top
    max_rank = max(ranks.values())
    
    for rank in range(max_rank + 1):
        nodes = by_rank[rank]
        
        if rank == 0:
            # Root level: center them
            nodes = sorted(nodes)
            n = len(nodes)
            for i, node in enumerate(nodes):
                x = (i - (n - 1) / 2) * x_gap
                pos[node] = (x, rank * y_gap)
        else:
            # Position nodes near their parents' average position
            node_positions = []
            for node in nodes:
                parents = list(G.predecessors(node))
                if parents:
                    # Average x position of parents
                    parent_x = sum(pos[p][0] for p in parents) / len(parents)
                    node_positions.append((node, parent_x))
                else:
                    # Fallback: use 0
                    node_positions.append((node, 0))
            
            # Sort by desired x position
            node_positions.sort(key=lambda x: x[1])
            
            # Assign actual positions with spacing
            n = len(node_positions)
            for i, (node, desired_x) in enumerate(node_positions):
                # Use desired position but ensure minimum spacing
                if i == 0:
                    x = desired_x
                else:
                    prev_x = pos[node_positions[i-1][0]][0]
                    x = max(desired_x, prev_x + x_gap)
                
                pos[node] = (x, rank * y_gap)
            
            # Center the rank
            if node_positions:
                min_x = min(pos[node][0] for node, _ in node_positions)
                max_x = max(pos[node][0] for node, _ in node_positions)
                center_offset = -(min_x + max_x) / 2
                for node, _ in node_positions:
                    x, y = pos[node]
                    pos[node] = (x + center_offset, y)

    return pos


def make_labels(G):
    labels = {}

    for node, data in G.nodes(data=True):
        description = data.get("label", node)
        # Adaptive text wrapping based on label length
        #wrap_width = 15 if len(description) > 20 else 18
        wrap_width = 15
        wrapped = "\n".join(textwrap.wrap(description, width=wrap_width))
        labels[node] = wrapped

    return labels


def calculate_figure_size(G):
    """Calculate optimal figure size based on graph complexity."""
    ranks = compute_ranks(G)
    by_rank = defaultdict(list)
    for node, rank in ranks.items():
        by_rank[rank].append(node)
    
    max_nodes_in_rank = max(len(nodes) for nodes in by_rank.values())
    num_ranks = len(by_rank)
    
    # Base size + scaling for complexity
    width = max(14, min(24, 10 + max_nodes_in_rank * 1.2))
    height = max(10, min(16, 8 + num_ranks * 1.5))
    
    return (width, height)


def draw_hasse(G, title="Hint taxonomy Hasse diagram", output_dir="plots", path_prefix="hint_taxonomy_hasse"):
    pos = ranked_layout(G)
    labels = make_labels(G)
    figsize = calculate_figure_size(G)
    
    # Calculate adaptive node size based on number of nodes - larger sizes
    num_nodes = G.number_of_nodes()
    node_size = max(6000, min(8000, 90000 / num_nodes))
    font_size = max(12, min(14, 200 / (num_nodes ** 0.5)))

    plt.figure(figsize=figsize)

    # Draw nodes first (as background)
    nx.draw_networkx_nodes(
        G,
        pos,
        node_size=node_size,
        node_color="white",
        edgecolors="black",
        linewidths=1.5,
    )

    # Draw edges with arrows on top of nodes
    nx.draw_networkx_edges(
        G,
        pos,
        arrowstyle="-|>",
        arrowsize=20,
        arrows=True,
        width=2.5,
        edge_color="black",
        node_size=node_size,
        connectionstyle="arc3,rad=0.1",
    )

    nx.draw_networkx_labels(
        G,
        pos,
        labels=labels,
        font_size=int(font_size),
    )

    plt.title(title, fontsize=12)
    plt.axis("off")
    plt.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    plt.savefig(f"{output_dir}/{path_prefix}.png", dpi=600, bbox_inches="tight")
    plt.savefig(f"{output_dir}/{path_prefix}.svg", bbox_inches="tight")
    #plt.show()


def draw_raw_vs_hasse(G, H, title="Raw relations with Hasse edges", output_dir="plots", path_prefix="hint_taxonomy_raw_vs_hasse"):
    """
    Optional diagnostic plot:
    - solid black = cover relations kept in Hasse graph
    - dashed gray = redundant relations removed by transitive reduction
    """
    pos = ranked_layout(H)
    labels = make_labels(H)
    figsize = calculate_figure_size(H)
    
    # Calculate adaptive node size based on number of nodes - larger sizes
    num_nodes = H.number_of_nodes()
    node_size = max(6000, min(8000, 90000 / num_nodes))
    font_size = max(12, min(14, 200 / (num_nodes ** 0.5)))

    hasse_edges = set(H.edges())
    redundant_edges = [edge for edge in G.edges() if edge not in hasse_edges]

    plt.figure(figsize=figsize)

    # Draw nodes first
    nx.draw_networkx_nodes(
        H,
        pos,
        node_size=node_size,
        node_color="white",
        edgecolors="black",
        linewidths=1.5,
    )

    # Draw Hasse edges with arrows
    nx.draw_networkx_edges(
        H,
        pos,
        arrowstyle="-|>",
        arrowsize=20,
        edgelist=list(hasse_edges),
        arrows=True,
        width=2.5,
        edge_color="black",
        node_size=node_size,
        connectionstyle="arc3,rad=0.1",
    )

    # Draw redundant edges with arrows
    nx.draw_networkx_edges(
        G,
        pos,
        arrowstyle="-|>",
        arrowsize=20,
        edgelist=redundant_edges,
        arrows=True,
        width=1.5,
        style="dashed",
        alpha=0.45,
        edge_color="gray",
        node_size=node_size,
        connectionstyle="arc3,rad=0.1",
    )

    nx.draw_networkx_labels(
        H,
        pos,
        labels=labels,
        font_size=int(font_size),
    )

    plt.title(title, fontsize=12)
    plt.axis("off")
    plt.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    plt.savefig(f"{output_dir}/{path_prefix}.png", dpi=600, bbox_inches="tight")
    plt.savefig(f"{output_dir}/{path_prefix}.svg", bbox_inches="tight")
    # plt.show()


def minimal_nodes(G):
    return [node for node in G.nodes if G.in_degree(node) == 0]


def maximal_nodes(G):
    return [node for node in G.nodes if G.out_degree(node) == 0]


def maximal_chains(G):
    """
    Return all maximal chains from minimal nodes to maximal nodes.

    Use this on the Hasse graph H, not the raw relation graph G.
    """
    mins = minimal_nodes(G)
    maxs = maximal_nodes(G)

    chains = []

    for source in sorted(mins):
        if source in maxs:
            chains.append([source])
            continue

        for target in sorted(maxs):
            if nx.has_path(G, source, target):
                chains.extend(nx.all_simple_paths(G, source, target))

    return chains


def main():
    """Main function to generate taxonomy diagrams from config file."""
    parser = argparse.ArgumentParser(description='Generate hint taxonomy diagrams from YAML config')
    parser.add_argument(
        'config',
        nargs='?',
        default='config/hint_taxonomy_config.yaml',
        help='Path to YAML config file (default: config/hint_taxonomy_config.yaml)'
    )
    parser.add_argument(
        '--output-dir',
        default='plots',
        help='Output directory for plots (default: plots)'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    print(f"Loading configuration from: {args.config}")
    categories, relations = load_config(args.config)
    
    # Extract base name from config file for output naming
    config_name = Path(args.config).stem
    
    # Create output directory: plots/<config_name>/
    output_dir = os.path.join(args.output_dir, config_name)
    
    # Build graphs
    G = build_relation_graph(categories, relations)
    H = hasse_graph(G)
    
    print("\nRaw relation edges:")
    for u, v in G.edges():
        print(f"  {u} -> {v}")
    
    print("\nHasse edges after transitive reduction:")
    for u, v in H.edges():
        print(f"  {u} -> {v}")
    
    print("\nRemoved redundant edges:")
    redundant = sorted(set(G.edges()) - set(H.edges()))
    if redundant:
        for edge in redundant:
            print(f"  {edge[0]} -> {edge[1]}")
    else:
        print("  (none)")
    
    # Generate diagrams
    print(f"\nGenerating diagrams in '{output_dir}/' directory...")
    draw_hasse(
        H,
        title=f"{config_name.replace('_', ' ').title()} Hasse Diagram",
        output_dir=output_dir,
        path_prefix=f"{config_name}_hasse"
    )
    
    draw_raw_vs_hasse(
        G, H,
        title=f"{config_name.replace('_', ' ').title()} - Raw vs Hasse",
        output_dir=output_dir,
        path_prefix=f"{config_name}_raw_vs_hasse"
    )
    
    print("\nMaximal chains:")
    for chain in maximal_chains(H):
        print("  " + " -> ".join(chain))
    
    print(f"\nDiagrams saved to '{output_dir}/' directory:")
    print(f"  - {config_name}_hasse.png/svg")
    print(f"  - {config_name}_raw_vs_hasse.png/svg")


if __name__ == "__main__":
    main()