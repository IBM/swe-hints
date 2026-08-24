import argparse
import os
import textwrap
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import yaml


# Main stream to emphasize visually.
MAIN_STREAM_NODES = ("File", "Class", "Func")
MAIN_STREAM_EDGES = (("File", "Class"), ("Class", "Func"))

# Benchmark definitions with their colored nodes
BENCHMARKS = {
    "NoCode Bench": {
        "nodes": [
            "FileLoc", "ModifiedFile", "NewFile", "Import", 
            "ClassName", "ExceptType", "ExceptValue", "Func"
        ],
        "color": "#FF6B6B",  # Red
        "isolated_nodes": []
    },
    "SWE Bench Pro Interface": {
        "nodes": [
            "LocParClass", "LocCompClass", "WeakSClass",
            "LocParFunc", "LocCompFunc", "WeakSFunc",
            "InN", "InT", "OutCT",
            "File", "FileLoc", "ModifiedFile", "NewFile"
        ],
        "color": "#4ECDC4",  # Teal
        "isolated_nodes": []
    },
    "SWE Bench Pro Requirements": {
        "nodes": [
            "StrongSFunc", "StrongSClass",
            "LocParFunc", "LocParClass",
            "FileLoc"
        ],
        "color": "#95E1D3",  # Light green
        "isolated_nodes": []
    },
    "FEA-Bench Brief": {
        "nodes": [
            "FuncName", "LocParFunc", "LocCompFunc", "FileLoc",
            "Sign", "InN", "ModifiedFile", "NewFile",
            "ClassName", "LocParClass", "LocCompClass"
        ],
        "color": "#F38181",  # Pink
        "isolated_nodes": []
    },
    "FEA-Bench Detailed": {
        "nodes": [
            # All nodes from FEA-Bench Brief
            "FuncName", "LocParFunc", "LocCompFunc", "FileLoc",
            "Sign", "InN", "ModifiedFile", "NewFile",
            "ClassName", "LocParClass", "LocCompClass"
        ],
        "color": "#AA96DA",  # Purple
        "isolated_nodes": ["Non-py Changes"]
    }
}


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
    """Convert the raw relation graph into its Hasse diagram."""
    H = nx.transitive_reduction(G)

    for node, data in G.nodes(data=True):
        H.nodes[node].update(data)

    return H


def compute_ranks(G):
    """Rank by longest distance from a minimal node."""
    ranks = {node: 0 for node in G.nodes}

    for node in nx.topological_sort(G):
        preds = list(G.predecessors(node))
        if preds:
            ranks[node] = max(ranks[pred] + 1 for pred in preds)

    return ranks


def get_all_ancestors(G, node):
    """Get all ancestors (parents) of a node."""
    if node not in G.nodes:
        return set()
    return set(nx.ancestors(G, node))


def compute_benchmark_colors(G, benchmarks):
    """
    Compute which nodes should be colored for each benchmark.
    Includes specified nodes plus all their ancestors.
    """
    benchmark_node_sets = {}
    
    for bench_name, bench_info in benchmarks.items():
        colored_nodes = set()
        
        # Add specified nodes
        for node in bench_info["nodes"]:
            if node in G.nodes:
                colored_nodes.add(node)
                # Add all ancestors
                colored_nodes.update(get_all_ancestors(G, node))
        
        benchmark_node_sets[bench_name] = colored_nodes
    
    return benchmark_node_sets


def ranked_layout(G):
    """Hasse-style layout with main stream on the right."""
    ranks = compute_ranks(G)

    by_rank = defaultdict(list)
    for node, rank in ranks.items():
        by_rank[rank].append(node)

    sibling_gap = 20.2
    group_gap = 25.5
    y_gap = 5.2

    pos = {}
    max_rank = max(ranks.values())
    
    main_stream_nodes = {"Class", "Func"}
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

        parent_groups = defaultdict(list)

        for node in nodes:
            parents = tuple(
                sorted(
                    G.predecessors(node),
                    key=lambda p: pos[p][0] if p in pos else 0,
                )
            )
            parent_groups[parents].append(node)

        main_stream_groups = []
        other_groups = []

        for parents, group_nodes in parent_groups.items():
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

        other_groups.sort(key=lambda g: g["desired_x"])
        main_stream_groups.sort(key=lambda g: g["desired_x"])
        
        group_data = other_groups + main_stream_groups

        current_right = None

        for group in group_data:
            nodes_in_group = group["nodes"]
            half_width = group["width"] / 2
            center_x = group["desired_x"]

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


def calculate_figure_size(G, num_isolated=0):
    """Calculate optimal figure size based on graph complexity."""
    ranks = compute_ranks(G)

    by_rank = defaultdict(list)
    for node, rank in ranks.items():
        by_rank[rank].append(node)

    max_nodes_in_rank = max(len(nodes) for nodes in by_rank.values())
    num_ranks = len(by_rank)

    width = max(16, min(28, 12 + max_nodes_in_rank * 1.2))
    height = max(12, min(20, 10 + num_ranks * 1.5))
    
    # Add space for isolated nodes
    if num_isolated > 0:
        height += 3

    return width, height


def draw_benchmark_coverage(
    G,
    benchmark_name,
    benchmark_info,
    colored_nodes,
    title="Benchmark Coverage",
    output_dir="plots",
    path_prefix="benchmark_coverage",
):
    """Draw the Hasse diagram with benchmark-specific node coloring."""
    pos = ranked_layout(G)
    labels = make_labels(G)
    
    # Add isolated nodes if any
    isolated_nodes = benchmark_info.get("isolated_nodes", [])
    num_isolated = len(isolated_nodes)
    
    figsize = calculate_figure_size(G, num_isolated)

    node_size = 6000
    font_size = 12

    plt.figure(figsize=figsize)

    # Draw edges
    nx.draw_networkx_edges(
        G,
        pos,
        arrowstyle="-|>",
        arrowsize=20,
        arrows=True,
        width=2.0,
        edge_color="black",
        alpha=0.65,
        node_size=node_size,
        connectionstyle="arc3,rad=0.1",
    )

    # Draw main stream edges (emphasized)
    main_edges = [edge for edge in MAIN_STREAM_EDGES if G.has_edge(*edge)]
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

    # Separate nodes into colored and uncolored
    colored = [node for node in G.nodes if node in colored_nodes]
    uncolored = [node for node in G.nodes if node not in colored_nodes]

    # Draw uncolored nodes (white)
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=uncolored,
        node_size=node_size,
        node_color="white",
        edgecolors="black",
        linewidths=1.5,
    )

    # Draw colored nodes (benchmark color)
    if colored:
        # Check if node is in main stream for sizing
        main_colored = [n for n in colored if n in MAIN_STREAM_NODES]
        normal_colored = [n for n in colored if n not in MAIN_STREAM_NODES]

        if normal_colored:
            nx.draw_networkx_nodes(
                G,
                pos,
                nodelist=normal_colored,
                node_size=node_size,
                node_color=benchmark_info["color"],
                edgecolors="black",
                linewidths=2.5,
            )

        if main_colored:
            nx.draw_networkx_nodes(
                G,
                pos,
                nodelist=main_colored,
                node_size=node_size * 1.55,
                node_color=benchmark_info["color"],
                edgecolors="black",
                linewidths=3.5,
            )

    # Draw labels
    normal_labels = {node: labels[node] for node in G.nodes if node not in MAIN_STREAM_NODES}
    main_labels = {node: labels[node] for node in G.nodes if node in MAIN_STREAM_NODES}
    
    nx.draw_networkx_labels(G, pos, labels=normal_labels, font_size=font_size)
    nx.draw_networkx_labels(G, pos, labels=main_labels, font_size=int(font_size * 1.25), font_weight="bold")

    # Draw isolated nodes if any
    if isolated_nodes:
        # Find the rightmost and bottommost position
        max_x = max(x for x, y in pos.values())
        min_y = min(y for x, y in pos.values())
        
        isolated_y = min_y - 8  # Place below the main graph
        isolated_x_start = max_x - (len(isolated_nodes) - 1) * 25 / 2
        
        for i, iso_node in enumerate(isolated_nodes):
            iso_x = isolated_x_start + i * 25
            iso_pos = (iso_x, isolated_y)
            
            # Draw isolated node
            plt.scatter([iso_x], [isolated_y], s=node_size, 
                       c=benchmark_info["color"], edgecolors="black", 
                       linewidths=2.5, zorder=3)
            
            # Draw label
            wrapped_label = "\n".join(textwrap.wrap(iso_node, width=12))
            plt.text(iso_x, isolated_y, wrapped_label, 
                    ha='center', va='center', fontsize=font_size, zorder=4)

    plt.title(title, fontsize=14, fontweight='bold')
    plt.axis("off")
    plt.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    plt.savefig(f"{output_dir}/{path_prefix}.png", dpi=600, bbox_inches="tight")
    plt.savefig(f"{output_dir}/{path_prefix}.svg", bbox_inches="tight")
    plt.close()


def draw_all_benchmarks_combined(
    G,
    benchmarks,
    benchmark_node_sets,
    title="All Benchmarks Coverage",
    output_dir="plots",
    path_prefix="all_benchmarks_coverage",
):
    """Draw the Hasse diagram with one color per unique benchmark-coverage combination."""
    import numpy as np

    pos = ranked_layout(G)
    labels = make_labels(G)

    bench_names = list(benchmarks.keys())

    # Collect all isolated nodes across all benchmarks (deduplicated, preserving order)
    all_isolated = []
    seen_isolated = set()
    for bench_info in benchmarks.values():
        for iso in bench_info.get("isolated_nodes", []):
            if iso not in seen_isolated:
                all_isolated.append(iso)
                seen_isolated.add(iso)

    figsize = calculate_figure_size(G, len(all_isolated))
    # Extra width for the combination legend
    figsize = (figsize[0] + 5, figsize[1])

    node_size = 6000
    font_size = 12

    # ------------------------------------------------------------------
    # Build coverage signatures: node -> frozenset of benchmark names
    # ------------------------------------------------------------------
    node_signature = {}
    for node in G.nodes:
        sig = frozenset(b for b in bench_names if node in benchmark_node_sets[b])
        node_signature[node] = sig

    # Also handle isolated nodes
    iso_signature = {}
    for iso_node in all_isolated:
        sig = frozenset(
            b for b in bench_names
            if iso_node in benchmarks[b].get("isolated_nodes", [])
        )
        iso_signature[iso_node] = sig

    # Collect unique non-empty signatures, sorted for determinism:
    # primary sort by count (ascending), secondary by names
    all_sigs = sorted(
        {s for s in node_signature.values() if s}
        | {s for s in iso_signature.values() if s},
        key=lambda s: (len(s), sorted(s)),
    )

    # Assign a distinct color to each signature using a qualitative palette.
    # Tab10 has 10 distinct colors — more than enough for realistic combos.
    cmap = plt.get_cmap("tab10")
    sig_color = {sig: cmap(i / max(len(all_sigs), 1)) for i, sig in enumerate(all_sigs)}

    def node_fill_color(sig):
        """Return (r,g,b,a) for a signature, or white for uncovered."""
        if not sig:
            return (1.0, 1.0, 1.0, 1.0)
        return sig_color[sig]

    # ------------------------------------------------------------------
    # Figure
    # ------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=figsize)

    # --- Edges ---
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        arrowstyle="-|>", arrowsize=20, arrows=True,
        width=2.0, edge_color="black", alpha=0.65,
        node_size=node_size, connectionstyle="arc3,rad=0.1",
    )
    main_edges = [edge for edge in MAIN_STREAM_EDGES if G.has_edge(*edge)]
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edgelist=main_edges,
        arrowstyle="-|>", arrowsize=36, arrows=True,
        width=5.0, edge_color="black",
        node_size=node_size * 1.55, connectionstyle="arc3,rad=0.1",
    )

    # --- Nodes: draw by signature group ---
    main_nodes = [n for n in G.nodes if n in MAIN_STREAM_NODES]

    # Base pass: white fill + border for all nodes
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_size=node_size,
        node_color="white",
        edgecolors="black",
        linewidths=1.5,
    )
    if main_nodes:
        nx.draw_networkx_nodes(
            G, pos, ax=ax,
            nodelist=main_nodes,
            node_size=node_size * 1.55,
            node_color="white",
            edgecolors="black",
            linewidths=3.5,
        )

    # Color pass: one draw call per signature group at 50 % alpha
    for sig in all_sigs:
        color = sig_color[sig]
        group = [n for n in G.nodes if node_signature[n] == sig]
        if not group:
            continue

        normal = [n for n in group if n not in MAIN_STREAM_NODES]
        main   = [n for n in group if n in MAIN_STREAM_NODES]

        if normal:
            nx.draw_networkx_nodes(
                G, pos, ax=ax,
                nodelist=normal,
                node_size=node_size,
                node_color=[color],
                edgecolors="none",
                alpha=0.5,
            )
        if main:
            nx.draw_networkx_nodes(
                G, pos, ax=ax,
                nodelist=main,
                node_size=node_size * 1.55,
                node_color=[color],
                edgecolors="none",
                alpha=0.5,
            )

    # Border redraw on top so borders are always crisp
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_size=node_size,
        node_color="none",
        edgecolors="black",
        linewidths=1.5,
    )
    if main_nodes:
        nx.draw_networkx_nodes(
            G, pos, ax=ax,
            nodelist=main_nodes,
            node_size=node_size * 1.55,
            node_color="none",
            edgecolors="black",
            linewidths=3.5,
        )

    # --- Labels ---
    normal_labels = {n: labels[n] for n in G.nodes if n not in MAIN_STREAM_NODES}
    main_labels   = {n: labels[n] for n in G.nodes if n in MAIN_STREAM_NODES}
    nx.draw_networkx_labels(G, pos, labels=normal_labels, font_size=font_size, ax=ax)
    nx.draw_networkx_labels(G, pos, labels=main_labels,
                            font_size=int(font_size * 1.25), font_weight="bold", ax=ax)

    # --- Isolated nodes ---
    if all_isolated:
        max_x = max(x for x, y in pos.values())
        min_y = min(y for x, y in pos.values())
        isolated_y = min_y - 8
        isolated_x_start = max_x - (len(all_isolated) - 1) * 25 / 2

        for i, iso_node in enumerate(all_isolated):
            iso_x = isolated_x_start + i * 25
            sig = iso_signature[iso_node]
            fill = sig_color[sig] if sig else (1.0, 1.0, 1.0, 1.0)

            ax.scatter([iso_x], [isolated_y], s=node_size,
                       c="white", edgecolors="black", linewidths=2.5, zorder=3)
            if sig:
                ax.scatter([iso_x], [isolated_y], s=node_size,
                           c=[fill], edgecolors="none", alpha=0.5, zorder=4)
            ax.scatter([iso_x], [isolated_y], s=node_size,
                       c="none", edgecolors="black", linewidths=2.5, zorder=5)
            wrapped_label = "\n".join(textwrap.wrap(iso_node, width=12))
            ax.text(iso_x, isolated_y, wrapped_label,
                    ha='center', va='center', fontsize=font_size, zorder=6)

    # --- Legend ---
    # Short aliases for benchmark names
    bench_aliases = {b: f"B{i+1}" for i, b in enumerate(bench_names)}

    legend_patches = []

    # First entry: uncovered (white)
    legend_patches.append(
        mpatches.Patch(facecolor="white", edgecolor="black", linewidth=1,
                       label="(none)")
    )

    # One entry per signature — label is just the alias list (e.g. "B1, B3")
    for sig in all_sigs:
        color = sig_color[sig]
        ordered = [b for b in bench_names if b in sig]
        alias_str = ", ".join(bench_aliases[b] for b in ordered)
        legend_patches.append(
            mpatches.Patch(facecolor=color, edgecolor="black", linewidth=1,
                           alpha=0.5, label=alias_str)
        )

    # Alias key in the title block
    alias_lines = [f"  {v}  =  {k}" for k, v in bench_aliases.items()]
    alias_block = "\n".join(alias_lines)
    legend_title = "Covered by  (50 % opacity)\n\n" + alias_block

    leg = ax.legend(
        handles=legend_patches,
        loc="upper left",
        fontsize=13,
        framealpha=0.95,
        title=legend_title,
        title_fontsize=11,
        handlelength=2.5,
        handleheight=2.0,
        borderpad=1.2,
        labelspacing=1.0,
        handletextpad=1.0,
    )
    leg.get_title().set_fontweight("bold")

    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.axis("off")
    plt.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    plt.savefig(f"{output_dir}/{path_prefix}.png", dpi=600, bbox_inches="tight")
    plt.savefig(f"{output_dir}/{path_prefix}.svg", bbox_inches="tight")
    plt.close()


def draw_all_benchmarks_dots(
    G,
    benchmarks,
    benchmark_node_sets,
    title="All Benchmarks Coverage (Dots)",
    output_dir="plots",
    path_prefix="all_benchmarks_coverage_dots",
):
    """
    Draw the Hasse diagram with all nodes unchanged (white fill, black border).
    For each benchmark that covers a node, place a small colored dot inside it.
    Dots are arranged in a tight grid centered on the node so they never overlap.
    """
    import numpy as np
    import matplotlib.transforms as mtransforms

    pos = ranked_layout(G)
    labels = make_labels(G)

    bench_names = list(benchmarks.keys())

    # Override colors for the dots plot only, so every dot is visually distinct.
    # B3 (SWE Bench Pro Requirements) was too close to B2 (teal);
    # B4 (FEA-Bench Brief) was too close to B1 (red).
    DOT_COLOR_OVERRIDES = {
        "SWE Bench Pro Requirements": "#F4A261",  # Orange  (replaces light green)
        "FEA-Bench Brief":            "#2176AE",  # Blue    (replaces pink)
    }
    bench_colors = [
        DOT_COLOR_OVERRIDES.get(b, benchmarks[b]["color"])
        for b in bench_names
    ]

    # Collect all isolated nodes across all benchmarks (deduplicated)
    all_isolated = []
    seen_isolated = set()
    for bench_info in benchmarks.values():
        for iso in bench_info.get("isolated_nodes", []):
            if iso not in seen_isolated:
                all_isolated.append(iso)
                seen_isolated.add(iso)

    figsize = calculate_figure_size(G, len(all_isolated))
    figsize = (figsize[0] + 4, figsize[1])   # extra width for legend

    node_size = 6000
    font_size = 12

    fig, ax = plt.subplots(figsize=figsize)

    # --- Edges ---
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        arrowstyle="-|>", arrowsize=20, arrows=True,
        width=2.0, edge_color="black", alpha=0.65,
        node_size=node_size, connectionstyle="arc3,rad=0.1",
    )
    main_edges = [edge for edge in MAIN_STREAM_EDGES if G.has_edge(*edge)]
    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edgelist=main_edges,
        arrowstyle="-|>", arrowsize=36, arrows=True,
        width=5.0, edge_color="black",
        node_size=node_size * 1.55, connectionstyle="arc3,rad=0.1",
    )

    # --- Nodes: all white, borders only ---
    main_nodes = [n for n in G.nodes if n in MAIN_STREAM_NODES]
    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_size=node_size,
        node_color="white",
        edgecolors="black",
        linewidths=1.5,
    )
    if main_nodes:
        nx.draw_networkx_nodes(
            G, pos, ax=ax,
            nodelist=main_nodes,
            node_size=node_size * 1.55,
            node_color="white",
            edgecolors="black",
            linewidths=3.5,
        )

    # --- Labels (drawn now; dots go on top via higher zorder) ---
    normal_labels = {n: labels[n] for n in G.nodes if n not in MAIN_STREAM_NODES}
    main_labels   = {n: labels[n] for n in G.nodes if n in MAIN_STREAM_NODES}
    nx.draw_networkx_labels(G, pos, labels=normal_labels, font_size=font_size, ax=ax)
    nx.draw_networkx_labels(G, pos, labels=main_labels,
                            font_size=int(font_size * 1.25), font_weight="bold", ax=ax)

    # --- Colored dots inside nodes ---
    # All geometry is computed in display (pixel) space so dot size and node
    # radius are directly comparable, guaranteeing no overlap.
    # After computing pixel offsets we convert back to data coords for scatter.
    fig.canvas.draw()  # lock in transforms

    trans     = ax.transData
    trans_inv = ax.transData.inverted()

    def node_radius_px(size_pts2):
        """Node radius in pixels from scatter node_size (pts²)."""
        return np.sqrt(size_pts2 / np.pi) * (fig.dpi / 72)

    r_normal_px = node_radius_px(node_size)

    # ── Fixed dot geometry ──────────────────────────────────────────────────
    # Size dots so that the WORST CASE (all 5 benchmarks, 3×2 grid) fits
    # inside the SMALLER normal node.  Every dot is the same size everywhere.
    MAX_DOTS   = len(bench_names)          # 5
    MAX_COLS   = int(np.ceil(np.sqrt(MAX_DOTS)))   # 3
    MAX_ROWS   = int(np.ceil(MAX_DOTS / MAX_COLS)) # 2
    MARGIN     = 0.80                      # fraction of node radius to use
    half_diag  = 0.5 * np.sqrt((MAX_COLS - 1) ** 2 + (MAX_ROWS - 1) ** 2)
    STEP_PX    = (r_normal_px * MARGIN) / half_diag   # grid step in pixels
    DOT_R_PX   = STEP_PX * 0.42           # dot radius — slight gap between dots
    DOT_S      = np.pi * (DOT_R_PX / (fig.dpi / 72)) ** 2  # scatter `s` (pts²)

    def dot_offsets_px(n):
        """
        Return n (dx_px, dy_px) offsets on the fixed grid, centred on (0,0).
        Uses the pre-computed STEP_PX so all dots are the same size and
        guaranteed non-overlapping inside any node (normal or main).
        """
        cols = int(np.ceil(np.sqrt(n)))
        rows = int(np.ceil(n / cols))
        offsets = []
        idx = 0
        for row in range(rows):
            for col in range(cols):
                if idx >= n:
                    break
                dx = (col - (cols - 1) / 2) * STEP_PX
                dy = (row - (rows - 1) / 2) * STEP_PX
                offsets.append((dx, dy))
                idx += 1
        return offsets

    def place_dots(cx_data, cy_data, covering_idx):
        """Draw dots for one node. cx/cy are in data coordinates."""
        n = len(covering_idx)
        if n == 0:
            return
        offsets = dot_offsets_px(n)
        cx_disp, cy_disp = trans.transform((cx_data, cy_data))
        for k, bidx in enumerate(covering_idx):
            dx_px, dy_px = offsets[k]
            dot_data = trans_inv.transform(
                np.array([cx_disp + dx_px, cy_disp + dy_px])
            )
            ax.scatter(
                [dot_data[0]], [dot_data[1]],
                s=DOT_S,
                c=bench_colors[bidx],
                edgecolors="black",
                linewidths=0.4,
                alpha=0.5,
                zorder=5,
            )

    for node in G.nodes:
        cx, cy = pos[node]
        covering_idx = [i for i, b in enumerate(bench_names)
                        if node in benchmark_node_sets[b]]
        place_dots(cx, cy, covering_idx)

    # --- Isolated nodes ---
    if all_isolated:
        max_x = max(x for x, y in pos.values())
        min_y = min(y for x, y in pos.values())
        isolated_y = min_y - 8
        isolated_x_start = max_x - (len(all_isolated) - 1) * 25 / 2

        for i, iso_node in enumerate(all_isolated):
            iso_x = isolated_x_start + i * 25
            ax.scatter([iso_x], [isolated_y], s=node_size,
                       c="white", edgecolors="black", linewidths=2.5, zorder=3)

            covering_idx = [idx for idx, b in enumerate(bench_names)
                            if iso_node in benchmarks[b].get("isolated_nodes", [])]
            place_dots(iso_x, isolated_y, covering_idx)

            wrapped_label = "\n".join(textwrap.wrap(iso_node, width=12))
            ax.text(iso_x, isolated_y, wrapped_label,
                    ha='center', va='center', fontsize=font_size, zorder=6)

    # --- Legend ---
    bench_aliases = {b: f"B{i+1}" for i, b in enumerate(bench_names)}
    alias_lines   = [f"  {v}  =  {k}" for k, v in bench_aliases.items()]
    alias_block   = "\n".join(alias_lines)
    legend_title  = "Benchmark dots\n\n" + alias_block

    legend_handles = [
        mpatches.Patch(facecolor=bench_colors[i], edgecolor="black",
                       linewidth=1, label=bench_aliases[bench_names[i]])
        for i in range(len(bench_names))
    ]
    leg = ax.legend(
        handles=legend_handles,
        loc="upper left",
        fontsize=13,
        framealpha=0.95,
        title=legend_title,
        title_fontsize=11,
        handlelength=2.5,
        handleheight=2.0,
        borderpad=1.2,
        labelspacing=1.0,
        handletextpad=1.0,
    )
    leg.get_title().set_fontweight("bold")

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.axis("off")
    plt.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    plt.savefig(f"{output_dir}/{path_prefix}.png", dpi=600, bbox_inches="tight")
    plt.savefig(f"{output_dir}/{path_prefix}.svg", bbox_inches="tight")
    plt.close()


def generate_latex_table(
    H,
    benchmarks,
    benchmark_node_sets,
    output_dir="plots",
    filename="benchmark_coverage_table.tex",
):
    """
    Generate a LaTeX longtable showing which benchmarks cover each taxonomy node.

    Rows follow the Hasse DAG structure: a DFS pre-order traversal starting
    from every root (node with no predecessors), with depth-based indentation.
    Each node appears exactly once; the first time it is reached in DFS wins.
    Benchmark coverage is marked with $\\checkmark$.
    """
    import textwrap as tw

    bench_names  = list(benchmarks.keys())

    # Short column headers (abbreviated to keep table narrow)
    HEADERS = {
        "NoCode Bench":               r"\rotatebox{60}{NoCo}",
        "SWE Bench Pro Interface":    r"\rotatebox{60}{ProI}",
        "SWE Bench Pro Requirements": r"\rotatebox{60}{ProR}",
        "FEA-Bench Brief":            r"\rotatebox{60}{FeaB}",
        "FEA-Bench Detailed":         r"\rotatebox{60}{FeaD}",
    }

    # ── DFS traversal to get ordered rows with depth ────────────────────────
    roots = [n for n in H.nodes if H.in_degree(n) == 0]
    # Sort roots topologically for a stable, deterministic order
    topo  = list(nx.topological_sort(H))
    roots = [n for n in topo if H.in_degree(n) == 0]

    rows    = []   # list of (node, depth)
    visited = set()

    def dfs(node, depth):
        if node in visited:
            return
        visited.add(node)
        rows.append((node, depth))
        # Visit children in topological order (keeps Hasse structure readable)
        children = sorted(H.successors(node), key=lambda c: topo.index(c))
        for child in children:
            dfs(child, depth + 1)

    for root in roots:
        dfs(root, 0)

    # Any nodes not reached (disconnected) appended at depth 0
    for node in topo:
        if node not in visited:
            rows.append((node, 0))

    # ── Build LaTeX ──────────────────────────────────────────────────────────
    n_bench = len(bench_names)

    col_spec = r"@{} l " + " c" * n_bench + r" @{}"

    header_cells = " & ".join(
        HEADERS.get(b, r"\rotatebox{60}{" + b[:6] + r"}") for b in bench_names
    )

    lines = []
    lines.append(r"\begin{longtable}{" + col_spec + r"}")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Taxonomy Node} & " + header_cells + r" \\")
    lines.append(r"\midrule")
    lines.append(r"\endfirsthead")
    lines.append(r"\toprule")
    lines.append(r"\textbf{Taxonomy Node} (cont.) & " + header_cells + r" \\")
    lines.append(r"\midrule")
    lines.append(r"\endhead")
    lines.append(r"\midrule")
    lines.append(r"\multicolumn{" + str(n_bench + 1) + r"}{r}{\textit{continued\ldots}} \\")
    lines.append(r"\endfoot")
    lines.append(r"\bottomrule")
    lines.append(r"\endlastfoot")

    for node, depth in rows:
        node_data  = H.nodes[node]
        label      = node_data.get("label", node)
        # Indent with \hspace, escape any special chars in label
        safe_label = label.replace("&", r"\&").replace("_", r"\_").replace("%", r"\%")
        if depth > 0:
            indent     = r"\hspace{" + str(depth) + r"em}"
            row_label  = indent + r"\small " + safe_label
        else:
            row_label  = r"\textbf{" + safe_label + r"}"

        cells = []
        for b in bench_names:
            if node in benchmark_node_sets[b]:
                cells.append(r"$\checkmark$")
            else:
                cells.append("")

        lines.append(row_label + " & " + " & ".join(cells) + r" \\")

    # ── Isolated nodes section ───────────────────────────────────────────────
    all_isolated = []
    seen = set()
    for b_info in benchmarks.values():
        for iso in b_info.get("isolated_nodes", []):
            if iso not in seen:
                all_isolated.append(iso)
                seen.add(iso)

    if all_isolated:
        lines.append(r"\midrule")
        lines.append(
            r"\multicolumn{" + str(n_bench + 1) + r"}{l}{"
            r"\textit{Additional (not in main taxonomy)}} \\"
        )
        lines.append(r"\midrule")
        for iso in all_isolated:
            safe_iso = iso.replace("&", r"\&").replace("_", r"\_")
            cells = []
            for b in bench_names:
                if iso in benchmarks[b].get("isolated_nodes", []):
                    cells.append(r"$\checkmark$")
                else:
                    cells.append("")
            lines.append(r"\small " + safe_iso + " & " + " & ".join(cells) + r" \\")

    lines.append(r"\end{longtable}")

    # ── Wrap in minimal compilable document preamble comment ────────────────
    preamble = [
        "% Required packages — add these to your document preamble:",
        "% \\usepackage{booktabs}   % \\toprule, \\midrule, \\bottomrule",
        "% \\usepackage{longtable}  % multi-page tables",
        "% \\usepackage{rotating}   % \\rotatebox in column headers",
        "% \\usepackage{amssymb}    % \\checkmark",
        "%",
        "% Paste the longtable block into your document body.",
        "",
    ]

    content = "\n".join(preamble + lines) + "\n"

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)
    with open(out_path, "w") as f:
        f.write(content)

    print(f"  LaTeX table written to: {out_path}")
    return out_path


def main():
    """Generate benchmark coverage diagrams."""
    parser = argparse.ArgumentParser(
        description="Generate benchmark coverage diagrams from YAML config"
    )
    parser.add_argument(
        "config",
        nargs="?",
        default="config/combined.yaml",
        help="Path to YAML config file, default: config/combined.yaml",
    )
    parser.add_argument(
        "--output-dir",
        default="plots/benchmarks",
        help="Output directory for plots, default: plots/benchmarks",
    )

    args = parser.parse_args()

    print(f"Loading configuration from: {args.config}")
    categories, relations = load_config(args.config)

    G = build_relation_graph(categories, relations)
    H = hasse_graph(G)

    # Compute which nodes to color for each benchmark
    benchmark_node_sets = compute_benchmark_colors(H, BENCHMARKS)

    print(f"\nGenerating benchmark coverage diagrams in '{args.output_dir}/' directory...")

    for bench_name, bench_info in BENCHMARKS.items():
        colored_nodes = benchmark_node_sets[bench_name]
        
        print(f"\n{bench_name}:")
        print(f"  Colored nodes: {len(colored_nodes)}")
        print(f"  Isolated nodes: {bench_info.get('isolated_nodes', [])}")
        
        safe_name = bench_name.lower().replace(" ", "_").replace("-", "_")
        
        draw_benchmark_coverage(
            H,
            bench_name,
            bench_info,
            colored_nodes,
            title=f"{bench_name} Coverage",
            output_dir=args.output_dir,
            path_prefix=f"{safe_name}_coverage",
        )

    # Draw combined plot with all benchmarks overlaid (colour-per-combination)
    print("\nAll Benchmarks Combined (color per combination):")
    draw_all_benchmarks_combined(
        H,
        BENCHMARKS,
        benchmark_node_sets,
        title="All Benchmarks Coverage",
        output_dir=args.output_dir,
        path_prefix="all_benchmarks_coverage",
    )

    # Draw combined plot with colored dots inside nodes
    print("\nAll Benchmarks Combined (dots):")
    draw_all_benchmarks_dots(
        H,
        BENCHMARKS,
        benchmark_node_sets,
        title="All Benchmarks Coverage (Dots)",
        output_dir=args.output_dir,
        path_prefix="all_benchmarks_coverage_dots",
    )

    # Generate LaTeX coverage table
    print("\nGenerating LaTeX coverage table...")
    generate_latex_table(
        H,
        BENCHMARKS,
        benchmark_node_sets,
        output_dir=args.output_dir,
        filename="benchmark_coverage_table.tex",
    )

    print(f"\nDiagrams saved to '{args.output_dir}/' directory")
    for bench_name in BENCHMARKS.keys():
        safe_name = bench_name.lower().replace(" ", "_").replace("-", "_")
        print(f"  - {safe_name}_coverage.png/svg")
    print("  - all_benchmarks_coverage.png/svg")
    print("  - all_benchmarks_coverage_dots.png/svg")
    print("  - benchmark_coverage_table.tex")


if __name__ == "__main__":
    main()

# Made with Bob
