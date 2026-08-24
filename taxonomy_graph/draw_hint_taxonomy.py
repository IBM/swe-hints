import networkx as nx

categories = {
    "C0": "Noise / generic token",
    "C1": "Repository context",
    "C2": "Localization hint",
    "C3": "Target anchor",
    "C4": "Artifact kind",
    "C5": "Interface contract",
    "C6": "Public API surface",
    "C7": "Structural role",
    "C8": "Weak semantic hint",
    "C9": "Strong behavioral hint",
    "C10": "Algorithmic strategy",
    "C11": "Implementation primitive",
    "C12": "Private implementation surface",
    "C13": "Test-oracle hint",
}

# A -> B means A ⪯ B, i.e. B is more revealing / specific than A.
relations = [
    ("C1", "C2"),
    ("C2", "C3"),
    ("C3", "C4"),
    ("C4", "C5"),

    ("C5", "C6"),
    ("C5", "C7"),

    ("C5", "C8"),
    ("C6", "C8"),
    ("C7", "C8"),

    ("C8", "C9"),
    ("C9", "C10"),
    ("C10", "C11"),
    ("C11", "C12"),
    ("C12", "C13"),

    # Optional redundant edges:
    # These are okay; transitive_reduction will remove them.
    ("C4", "C8"),
    ("C5", "C9"),
    ("C10", "C13"),
]

G = nx.DiGraph()
G.add_nodes_from(categories)
G.add_edges_from(relations)

H = nx.transitive_reduction(G)
nx.write_network_text(graph=H)

# Module Level: File -> Class -> Function

categories_module = {
    "File": "File",
    "Class": "Class",
    "Func": "Function",
}

relation_module = [
    ("File", "Class"),
    ("Class", "Func"),
]

G_module = nx.DiGraph()
G_module.add_nodes_from(categories_module)
G_module.add_edges_from(relation_module)

if not nx.is_directed_acyclic_graph(G_module):
    raise ValueError("The module relation is cyclic, so it is not a valid poset.")

# H = nx.transitive_reduction(G)

# print("Hasse edges:")
# for u, v in G_module.edges():
#     print(f"{u} ({categories_module[u]})  ->  {v} ({categories_module[v]})")

# nx.write_network_text(G_module)