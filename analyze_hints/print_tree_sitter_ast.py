"""
Utility to print and visualize tree-sitter AST

This script helps you understand the tree-sitter parse tree structure,
which is useful for debugging and understanding how to identify READ/WRITE contexts.
"""

from tree_sitter_languages import get_parser


parser = get_parser('python')


def print_tree(node, indent=0, show_text=True, max_text_len=50):
    """
    Recursively print the tree-sitter AST in a readable format.
    
    Args:
        node: Tree-sitter node to print
        indent: Current indentation level
        show_text: Whether to show the text content of nodes
        max_text_len: Maximum length of text to display
    """
    indent_str = "  " * indent
    
    # Get node info
    node_type = node.type
    is_named = node.is_named
    
    # Get text if requested
    text_str = ""
    if show_text and node.text:
        text = node.text.decode('utf-8', errors='ignore')
        if len(text) > max_text_len:
            text = text[:max_text_len] + "..."
        # Escape newlines for display
        text = text.replace('\n', '\\n').replace('\r', '\\r')
        text_str = f' "{text}"'
    
    # Print node info
    named_marker = "●" if is_named else "○"
    print(f"{indent_str}{named_marker} {node_type}{text_str}")
    
    # Print field names if available
    if node.children:
        for child in node.children:
            # Check if this child has a field name
            field_name = None
            for field in node.type:
                try:
                    field_child = node.child_by_field_name(field)
                    if field_child == child:
                        field_name = field
                        break
                except:
                    pass
            
            if field_name:
                print(f"{indent_str}  [{field_name}]:")
            
            print_tree(child, indent + 1, show_text, max_text_len)


def print_tree_with_parent_info(node, indent=0, parent_type=None):
    """
    Print tree with parent information, useful for understanding context.
    """
    indent_str = "  " * indent
    
    node_type = node.type
    text = node.text.decode('utf-8', errors='ignore')[:30].replace('\n', '\\n')
    
    parent_info = f" (parent: {parent_type})" if parent_type else ""
    print(f"{indent_str}{node_type}{parent_info}: {text}")
    
    for child in node.named_children:
        print_tree_with_parent_info(child, indent + 1, node_type)


def print_all_nodes(node, indent=0):
    """
    Print ALL nodes (both named and unnamed) without any filtering.
    This shows the complete raw tree structure.
    """
    indent_str = "  " * indent
    
    node_type = node.type
    is_named = "●" if node.is_named else "○"
    text = node.text.decode('utf-8', errors='ignore')[:40].replace('\n', '\\n')
    
    # Show parent info
    parent_type = node.parent.type if node.parent else "None"
    
    print(f"{indent_str}{is_named} {node_type} (parent: {parent_type}): '{text}'")
    
    # Print ALL children (not just named_children)
    for child in node.children:
        print_all_nodes(child, indent + 1)


def analyze_identifiers(code):
    """
    Print all identifiers with their parent context.
    """
    tree = parser.parse(code.encode('utf-8'))
    root = tree.root_node
    
    print("\n" + "=" * 60)
    print("IDENTIFIER ANALYSIS")
    print("=" * 60)
    
    def find_identifiers(node, path=""):
        if node.type == 'identifier':
            text = node.text.decode('utf-8', errors='ignore')
            parent_type = node.parent.type if node.parent else "None"
            
            # Get field name if available
            field_name = "unknown"
            if node.parent:
                for field in ['name', 'left', 'right', 'function', 'object', 
                             'attribute', 'alias', 'value']:
                    try:
                        if node.parent.child_by_field_name(field) == node:
                            field_name = field
                            break
                    except:
                        pass
            
            print(f"\nIdentifier: '{text}'")
            print(f"  Parent type: {parent_type}")
            print(f"  Field name: {field_name}")
            print(f"  Path: {path}")
            
            # Show grandparent for more context
            if node.parent and node.parent.parent:
                print(f"  Grandparent: {node.parent.parent.type}")
        
        for i, child in enumerate(node.named_children):
            find_identifiers(child, f"{path}/{node.type}[{i}]")
    
    find_identifiers(root)


def print_ast_simple(code, max_depth=None):
    """
    Simple AST printer with optional depth limit.
    """
    tree = parser.parse(code.encode('utf-8'))
    
    def print_node(node, depth=0):
        if max_depth is not None and depth > max_depth:
            return
        
        indent = "  " * depth
        text = node.text.decode('utf-8', errors='ignore')[:40].replace('\n', '\\n')
        print(f"{indent}{node.type}: {text}")
        
        for child in node.named_children:
            print_node(child, depth + 1)
    
    print_node(tree.root_node)


# Example usage
if __name__ == '__main__':
    # Example code to analyze
    example_code = """
def calculate_total(items):
    total = 0
    for item in items:
        total += item
    return total

result = calculate_total([1, 2, 3])
"""

    print("=" * 60)
    print("COMPLETE UNFILTERED TREE (ALL NODES)")
    print("=" * 60)
    tree = parser.parse(example_code.encode('utf-8'))
    print_all_nodes(tree.root_node)
    
    print("\n" + "=" * 60)
    print("FULL TREE-SITTER AST (NAMED NODES ONLY)")
    print("=" * 60)
    print_tree(tree.root_node, show_text=True)
    
    print("\n" + "=" * 60)
    print("SIMPLE AST VIEW (depth limited)")
    print("=" * 60)
    print_ast_simple(example_code, max_depth=4)
    
    print("\n" + "=" * 60)
    print("IDENTIFIER ANALYSIS")
    print("=" * 60)
    analyze_identifiers(example_code)
    
    print("\n" + "=" * 60)
    print("\nTo use this script with your own code:")
    print("  1. Import: from print_tree_sitter_ast import print_all_nodes, print_tree, analyze_identifiers")
    print("  2. Parse your code: tree = parser.parse(code.encode('utf-8'))")
    print("  3. Print complete tree: print_all_nodes(tree.root_node)")
    print("  4. Or print named nodes only: print_tree(tree.root_node)")
    print("  5. Or analyze identifiers: analyze_identifiers(your_code_string)")

# Made with Bob
