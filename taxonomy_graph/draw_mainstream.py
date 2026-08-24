import argparse
import os
import textwrap
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import yaml


# Main stream to emphasize visually.
# Note: the YAML category key for "Function" is "Func".
MAIN_STREAM_NODES = ("File", "Class", "Func")
MAIN_STREAM_EDGES = (("File", "Class"), ("Class", "Func"))


def load_config(config_path):
    """Load taxonomy configuration from YAML file."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    categories = config["categories"]
    relations = [tuple(rel) for rel in config["relations"]]

    return categories, relations


def build_relation_graph(categories, relations):
    """Build the raw directed relation graph."""
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
    Hasse-style layout with subtree grouping.

    Compared with the original ranked_layout:
    - nodes are still arranged by rank / level
    - children with the same parent are grouped closer together
    - different parent groups are separated more clearly
    - For combined.yaml: Class, Func and their descendants are positioned at the very right
    """
    ranks = compute_ranks(G)

    by_rank = defaultdict(list)
    for node, rank in ranks.items():
        by_rank[rank].append(node)

    # Tune these three values.
    # Smaller sibling_gap = tighter nodes inside the same subtree.
    # Larger group_gap = more space between different subtrees.
    sibling_gap = 20.2
    group_gap = 25.5
    y_gap = 5.2

    pos = {}
    max_rank = max(ranks.values())
    
    # Define main stream nodes that should be on the right
    main_stream_nodes = {"Class", "Func"}
    
    # Identify main stream nodes and their descendants (Class and Func)
    main_stream_descendants = set()
    if "Class" in G.nodes:
        main_stream_descendants.add("Class")
        main_stream_descendants.update(nx.descendants(G, "Class"))
    if "Func" in G.nodes:
        main_stream_descendants.add("Func")
        main_stream_descendants.update(nx.descendants(G, "Func"))

    for rank in range(max_rank + 1):
        nodes = sorted(by_rank[rank])

        if rank == 0:
            n = len(nodes)
            for i, node in enumerate(nodes):
                x = (i - (n - 1) / 2) * group_gap
                pos[node] = (x, rank * y_gap)
            continue

        # Group nodes by their parent set.
        parent_groups = defaultdict(list)

        for node in nodes:
            parents = tuple(
                sorted(
                    G.predecessors(node),
                    key=lambda p: pos[p][0] if p in pos else 0,
                )
            )
            parent_groups[parents].append(node)

        # Separate main stream groups (Class/Func descendants) from others
        main_stream_groups = []
        other_groups = []

        for parents, group_nodes in parent_groups.items():
            # Sort nodes within group with priority:
            # 1. Non-main-stream nodes (not Class/Func or their descendants)
            # 2. Class descendants that are not Func or Func descendants
            # 3. Func and its descendants
            non_main = []
            class_only = []
            func_related = []
            
            for n in group_nodes:
                if n == "Func" or (n in main_stream_descendants and "Func" in G.nodes and
                                   (n in nx.descendants(G, "Func") or n == "Func")):
                    func_related.append(n)
                elif n in main_stream_nodes or n in main_stream_descendants:
                    class_only.append(n)
                else:
                    non_main.append(n)
            
            group_nodes = sorted(non_main) + sorted(class_only) + sorted(func_related)

            if parents:
                desired_x = sum(pos[p][0] for p in parents) / len(parents)
            else:
                desired_x = 0

            group_width = max(0, (len(group_nodes) - 1) * sibling_gap)
            
            # Check if this group contains Class, Func or their descendants
            is_main_stream = any(node in main_stream_descendants or node in main_stream_nodes for node in group_nodes)

            group_info = {
                "parents": parents,
                "nodes": group_nodes,
                "desired_x": desired_x,
                "width": group_width,
                "is_main_stream": is_main_stream,
            }
            
            if is_main_stream:
                main_stream_groups.append(group_info)
            else:
                other_groups.append(group_info)

        # Sort other groups by desired_x
        other_groups.sort(key=lambda g: g["desired_x"])
        # Sort main stream groups by desired_x
        main_stream_groups.sort(key=lambda g: g["desired_x"])
        
        # Combine: other groups first, then main stream groups (Class/Func) at the right
        group_data = other_groups + main_stream_groups

        current_right = None

        for group in group_data:
            nodes_in_group = group["nodes"]
            half_width = group["width"] / 2
            center_x = group["desired_x"]

            # Prevent overlap between different parent groups.
            if current_right is not None:
                min_allowed_center = current_right + group_gap + half_width
                center_x = max(center_x, min_allowed_center)

            start_x = center_x - half_width

            for i, node in enumerate(nodes_in_group):
                x = start_x + i * sibling_gap
                pos[node] = (x, rank * y_gap)

            current_right = center_x + half_width

    return pos


def make_labels(G):
    """Use the human-readable category labels from the YAML config."""
    labels = {}

    for node, data in G.nodes(data=True):
        description = data.get("label", node)
        wrapped = "\n".join(textwrap.wrap(description, width=12))
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

    width = max(14, min(24, 10 + max_nodes_in_rank * 1.2))
    height = max(10, min(16, 8 + num_ranks * 1.5))

    return width, height


def split_main_stream_nodes(G):
    """Split nodes into normal nodes and emphasized main-stream nodes."""
    main_node_set = set(MAIN_STREAM_NODES)

    main_nodes = [node for node in MAIN_STREAM_NODES if node in G.nodes]
    normal_nodes = [node for node in G.nodes if node not in main_node_set]

    return normal_nodes, main_nodes


def split_main_stream_edges(G):
    """Split edges into normal edges and emphasized main-stream edges."""
    main_edge_set = set(MAIN_STREAM_EDGES)

    main_edges = [edge for edge in MAIN_STREAM_EDGES if G.has_edge(*edge)]
    normal_edges = [edge for edge in G.edges if edge not in main_edge_set]

    return normal_edges, main_edges


def draw_nodes_and_labels(G, pos, labels, node_size, font_size):
    """
    Draw normal nodes and emphasized main-stream nodes in separate layers.

    This is the key change:
    File, Class, and Func are drawn larger and with thicker borders.
    """
    normal_nodes, main_nodes = split_main_stream_nodes(G)

    main_node_size = node_size * 1.55
    main_font_size = int(font_size * 1.25)

    # Normal nodes.
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=normal_nodes,
        node_size=node_size,
        node_color="white",
        edgecolors="black",
        linewidths=1.5,
    )

    # Main-stream nodes: File, Class, Func.
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=main_nodes,
        node_size=main_node_size,
        node_color="white",
        edgecolors="black",
        linewidths=3.0,
    )

    # Normal labels.
    normal_labels = {node: labels[node] for node in normal_nodes}
    nx.draw_networkx_labels(
        G,
        pos,
        labels=normal_labels,
        font_size=int(font_size),
    )

    # Main-stream labels.
    main_labels = {node: labels[node] for node in main_nodes}
    nx.draw_networkx_labels(
        G,
        pos,
        labels=main_labels,
        font_size=main_font_size,
        font_weight="bold",
    )

    return main_node_size


def draw_hasse(
    G,
    title="Hint taxonomy Hasse diagram",
    output_dir="plots",
    path_prefix="hint_taxonomy_hasse",
):
    """
    Draw the Hasse diagram, emphasizing only:
      File -> Class -> Func

    File, Class, and Func are larger.
    The two arrows File -> Class and Class -> Func are thicker and larger.
    """
    pos = ranked_layout(G)
    labels = make_labels(G)
    figsize = calculate_figure_size(G)

    num_nodes = G.number_of_nodes()
    node_size = max(6000, min(8000, 90000 / num_nodes))
    font_size = max(12, min(14, 200 / (num_nodes ** 0.5)))

    normal_edges, main_edges = split_main_stream_edges(G)

    plt.figure(figsize=figsize)

    # Draw normal edges first so highlighted main-stream arrows sit on top.
    nx.draw_networkx_edges(
        G,
        pos,
        edgelist=normal_edges,
        arrowstyle="-|>",
        arrowsize=20,
        arrows=True,
        width=2.0,
        edge_color="black",
        alpha=0.65,
        node_size=node_size,
        connectionstyle="arc3,rad=0.1",
    )

    # Draw the highlighted main stream arrows:
    # File -> Class -> Function.
    nx.draw_networkx_edges(
        G,
        pos,
        edgelist=main_edges,
        arrowstyle="-|>",
        arrowsize=36,
        arrows=True,
        width=5.0,
        edge_color="black",
        node_size=node_size * 1.55,
        connectionstyle="arc3,rad=0.1",
    )

    # Draw nodes after edges so node borders stay crisp.
    draw_nodes_and_labels(G, pos, labels, node_size, font_size)

    plt.title(title, fontsize=12)
    plt.axis("off")
    plt.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    plt.savefig(f"{output_dir}/{path_prefix}.png", dpi=600, bbox_inches="tight")
    plt.savefig(f"{output_dir}/{path_prefix}.svg", bbox_inches="tight")
    plt.close()


def draw_raw_vs_hasse(
    G,
    H,
    title="Raw relations with Hasse edges",
    output_dir="plots",
    path_prefix="hint_taxonomy_raw_vs_hasse",
):
    """
    Optional diagnostic plot:
    - solid black = cover relations kept in Hasse graph
    - dashed gray = redundant relations removed by transitive reduction
    - extra-thick black = emphasized main stream File -> Class -> Func
    """
    pos = ranked_layout(H)
    labels = make_labels(H)
    figsize = calculate_figure_size(H)

    num_nodes = H.number_of_nodes()
    node_size = max(6000, min(8000, 90000 / num_nodes))
    font_size = max(12, min(14, 200 / (num_nodes ** 0.5)))

    hasse_edges = set(H.edges())
    main_edge_set = set(MAIN_STREAM_EDGES)

    main_edges = [edge for edge in MAIN_STREAM_EDGES if edge in hasse_edges]
    normal_hasse_edges = [edge for edge in hasse_edges if edge not in main_edge_set]
    redundant_edges = [edge for edge in G.edges() if edge not in hasse_edges]

    plt.figure(figsize=figsize)

    # Hasse edges except the emphasized main-stream edges.
    nx.draw_networkx_edges(
        H,
        pos,
        arrowstyle="-|>",
        arrowsize=20,
        edgelist=normal_hasse_edges,
        arrows=True,
        width=2.0,
        edge_color="black",
        alpha=0.65,
        node_size=node_size,
        connectionstyle="arc3,rad=0.1",
    )

    # Redundant raw edges.
    nx.draw_networkx_edges(
        G,
        pos,
        arrowstyle="-|>",
        arrowsize=18,
        edgelist=redundant_edges,
        arrows=True,
        width=1.5,
        style="dashed",
        alpha=0.35,
        edge_color="gray",
        node_size=node_size,
        connectionstyle="arc3,rad=0.1",
    )

    # Emphasized main-stream edges.
    nx.draw_networkx_edges(
        H,
        pos,
        arrowstyle="-|>",
        arrowsize=36,
        edgelist=main_edges,
        arrows=True,
        width=5.0,
        edge_color="black",
        node_size=node_size * 1.55,
        connectionstyle="arc3,rad=0.1",
    )

    # Draw nodes after edges so larger main nodes cover any edge overlaps.
    draw_nodes_and_labels(H, pos, labels, node_size, font_size)

    plt.title(title, fontsize=12)
    plt.axis("off")
    plt.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    plt.savefig(f"{output_dir}/{path_prefix}.png", dpi=600, bbox_inches="tight")
    plt.savefig(f"{output_dir}/{path_prefix}.svg", bbox_inches="tight")
    plt.close()


def minimal_nodes(G):
    """Return all minimal nodes."""
    return [node for node in G.nodes if G.in_degree(node) == 0]


def maximal_nodes(G):
    """Return all maximal nodes."""
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
    """Generate taxonomy diagrams from a YAML config file."""
    parser = argparse.ArgumentParser(
        description="Generate hint taxonomy diagrams from YAML config"
    )
    parser.add_argument(
        "config",
        nargs="?",
        default="config/combined.yaml",
        help="Path to YAML config file, default: config/combined.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="plots",
        help="Output directory for plots, default: plots",
    )

    args = parser.parse_args()

    print(f"Loading configuration from: {args.config}")
    categories, relations = load_config(args.config)

    config_name = Path(args.config).stem
    output_dir = os.path.join(args.output_dir, config_name)

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

    print(f"\nGenerating diagrams in '{output_dir}/' directory...")

    draw_hasse(
        H,
        title=f"{config_name.replace('_', ' ').title()} Hasse Diagram",
        output_dir=output_dir,
        path_prefix=f"{config_name}_hasse",
    )

    draw_raw_vs_hasse(
        G,
        H,
        title=f"{config_name.replace('_', ' ').title()} - Raw vs Hasse",
        output_dir=output_dir,
        path_prefix=f"{config_name}_raw_vs_hasse",
    )

    print("\nMaximal chains:")
    for chain in maximal_chains(H):
        print("  " + " -> ".join(chain))

    print(f"\nDiagrams saved to '{output_dir}/' directory:")
    print(f"  - {config_name}_hasse.png/svg")
    print(f"  - {config_name}_raw_vs_hasse.png/svg")


if __name__ == "__main__":
    main()
