"""
Tree-sitter based Read/Write Entity Analysis

This script uses tree-sitter (like NoCode-bench) to analyze code and test patches
to identify entities that are:
- Written in code and read in tests (forward hints)
- Read in code and written in tests (backward hints)

Key difference from AST-based approach: Uses tree-sitter for parsing, which is
more robust and consistent with NoCode-bench's approach.
"""

from typing import Set, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum
from tree_sitter_languages import get_parser


parser = get_parser('python')


class AccessType(Enum):
    READ = "read"
    WRITE = "write"


@dataclass
class Entity:
    """Represents an entity (identifier) with its access type"""
    name: str
    access_type: AccessType
    entity_type: str  # 'function', 'class', 'variable', 'attribute'
    
    def __hash__(self):
        return hash((self.name, self.access_type, self.entity_type))
    
    def __eq__(self, other):
        return (self.name == other.name and 
                self.access_type == other.access_type and
                self.entity_type == other.entity_type)
    
    def __repr__(self):
        return f"Entity({self.name}, {self.access_type.value}, {self.entity_type})"


def is_write_context(node) -> bool:
    """
    Determine if an identifier node is in a WRITE context.
    
    WRITE contexts:
    - Left side of assignment (assignment target)
    - Function/class definition names
    - For loop variables
    - With statement variables
    - Import names (being defined)
    - Parameter names in function definitions
    """
    if node.parent is None:
        return False
    
    parent = node.parent
    parent_type = parent.type
    
    # Function and class definitions are WRITE
    if parent_type in ['function_definition', 'class_definition']:
        # The identifier is the name being defined
        if node == parent.child_by_field_name('name'):
            return True
    
    # Assignment targets (left side of =)
    if parent_type == 'assignment':
        # Check if this identifier is on the left side
        left = parent.child_by_field_name('left')
        if left and _node_contains(left, node):
            return True
    
    # Augmented assignment (+=, -=, etc.) - target is both READ and WRITE
    # We'll handle this by adding both READ and WRITE entries
    if parent_type == 'augmented_assignment':
        left = parent.child_by_field_name('left')
        if left and _node_contains(left, node):
            return True  # Will also be marked as READ separately
    
    # For statement - loop variable is WRITE
    if parent_type == 'for_statement':
        left = parent.child_by_field_name('left')
        if left and _node_contains(left, node):
            return True
    
    # With statement - as clause variables are WRITE
    if parent_type == 'as_pattern':
        alias = parent.child_by_field_name('alias')
        if alias and _node_contains(alias, node):
            return True
    
    # Parameters in function definitions are WRITE
    if parent_type in ['parameters', 'typed_parameter', 'default_parameter', 
                       'typed_default_parameter', 'list_splat_pattern', 
                       'dictionary_splat_pattern']:
        return True
    
    # Import statements - names being imported are WRITE
    if parent_type in ['dotted_name', 'aliased_import']:
        # Check if we're in an import context
        ancestor = parent
        while ancestor:
            if ancestor.type in ['import_statement', 'import_from_statement']:
                return True
            ancestor = ancestor.parent
    
    return False


def is_read_context(node) -> bool:
    """
    Determine if an identifier node is in a READ context.
    
    READ contexts:
    - Right side of assignment
    - Function/method calls
    - Expressions
    - Return statements
    - Conditionals
    - Arguments to functions
    """
    if node.parent is None:
        return False
    
    parent = node.parent
    parent_type = parent.type
    
    # In a call expression - the function being called is READ
    if parent_type == 'call':
        func = parent.child_by_field_name('function')
        if func and _node_contains(func, node):
            return True
    
    # Right side of assignment is READ
    if parent_type == 'assignment':
        right = parent.child_by_field_name('right')
        if right and _node_contains(right, node):
            return True
    
    # Augmented assignment - right side is READ, left side is both READ and WRITE
    if parent_type == 'augmented_assignment':
        right = parent.child_by_field_name('right')
        if right and _node_contains(right, node):
            return True
        # Left side is also READ (in addition to WRITE)
        left = parent.child_by_field_name('left')
        if left and _node_contains(left, node):
            return True
    
    # Return statement - value is READ
    if parent_type == 'return_statement':
        return True
    
    # Expressions, comparisons, binary operations - all READ
    if parent_type in ['binary_operator', 'comparison_operator', 'boolean_operator',
                       'unary_operator', 'not_operator', 'parenthesized_expression',
                       'list', 'tuple', 'set', 'dictionary', 'list_comprehension',
                       'dictionary_comprehension', 'set_comprehension',
                       'generator_expression', 'subscript', 'slice']:
        return True
    
    # Conditional expressions
    if parent_type in ['if_statement', 'elif_clause', 'while_statement', 
                       'conditional_expression']:
        return True
    
    # Arguments in function calls are READ
    if parent_type in ['argument_list', 'keyword_argument']:
        return True
    
    # For statement - the iterable is READ
    if parent_type == 'for_statement':
        right = parent.child_by_field_name('right')
        if right and _node_contains(right, node):
            return True
    
    # Attribute access - the object is READ
    if parent_type == 'attribute':
        obj = parent.child_by_field_name('object')
        if obj and _node_contains(obj, node):
            return True
    
    return False


def _node_contains(parent, child) -> bool:
    """Check if parent node contains child node in its subtree"""
    if parent == child:
        return True
    for c in parent.children:
        if _node_contains(c, child):
            return True
    return False


def get_all_identifiers_with_access(root) -> List[Entity]:
    """
    Extract all identifiers from tree-sitter parse tree with READ/WRITE classification.
    
    This is similar to NoCode-bench's get_all_identifiers but adds access type info.
    """
    results = []
    
    def traverse(node):
        if node.type == 'identifier':
            name = node.text.decode('utf-8', errors='ignore')
            
            # Determine entity type based on parent
            entity_type = 'variable'
            if node.parent and node.parent.type == 'function_definition':
                if node == node.parent.child_by_field_name('name'):
                    entity_type = 'function'
            elif node.parent and node.parent.type == 'class_definition':
                if node == node.parent.child_by_field_name('name'):
                    entity_type = 'class'
            elif node.parent and node.parent.type == 'attribute':
                if node == node.parent.child_by_field_name('attribute'):
                    entity_type = 'attribute'
            
            # Determine if READ or WRITE (or both)
            is_write = is_write_context(node)
            is_read = is_read_context(node)
            
            # Add appropriate Entity objects
            if is_write:
                results.append(Entity(
                    name=name,
                    access_type=AccessType.WRITE,
                    entity_type=entity_type
                ))
            
            if is_read:
                results.append(Entity(
                    name=name,
                    access_type=AccessType.READ,
                    entity_type=entity_type
                ))
            
            # If neither (shouldn't happen often), default to READ
            if not is_write and not is_read:
                results.append(Entity(
                    name=name,
                    access_type=AccessType.READ,
                    entity_type=entity_type
                ))
        
        # Recursively traverse children
        for child in node.named_children:
            traverse(child)
    
    traverse(root)
    return results


def extract_entities_from_code(code: str) -> Set[Entity]:
    """
    Extract entities from Python code with read/write classification using tree-sitter.
    
    Args:
        code: Python source code as string
        
    Returns:
        Set of Entity objects with access type information
    """
    try:
        tree = parser.parse(code.encode('utf-8', errors='ignore'))
        entities = get_all_identifiers_with_access(tree.root_node)
        return set(entities)
    except Exception:
        return set()


def filter_entities_by_access(entities: Set[Entity], access_type: AccessType) -> Set[str]:
    """
    Filter entities by access type and return just the names.
    
    Args:
        entities: Set of Entity objects
        access_type: AccessType.READ or AccessType.WRITE
        
    Returns:
        Set of entity names
    """
    return {e.name for e in entities if e.access_type == access_type}


def augment_identifiers(
    code_entities: Set[Entity],
    test_entities: Set[Entity],
    code_access: AccessType,
    test_access: AccessType
) -> Set[str]:
    """
    Generic function to compute intersection of entities based on access patterns.
    
    This is the core function that can be used for both forward and backward hints.
    
    Args:
        code_entities: Entities extracted from code patch
        test_entities: Entities extracted from test patch
        code_access: Access type to filter in code (READ or WRITE)
        test_access: Access type to filter in test (READ or WRITE)
        
    Returns:
        Set of entity names that match the access pattern
    """
    code_filtered = filter_entities_by_access(code_entities, code_access)
    test_filtered = filter_entities_by_access(test_entities, test_access)
    
    # Return intersection
    return code_filtered & test_filtered


def augment_ident_forward(code_entities: Set[Entity], test_entities: Set[Entity]) -> Set[str]:
    """
    Forward hints: entities WRITTEN in code and READ in tests.
    
    These are new entities (functions, classes, variables) that are:
    - Defined/created in the implementation code
    - Used/referenced in the test code
    
    Args:
        code_entities: Entities from code patch
        test_entities: Entities from test patch
        
    Returns:
        Set of entity names for forward hints
    """
    return augment_identifiers(
        code_entities=code_entities,
        test_entities=test_entities,
        code_access=AccessType.WRITE,
        test_access=AccessType.READ
    )


def augment_ident_backward(code_entities: Set[Entity], test_entities: Set[Entity]) -> Set[str]:
    """
    Backward hints: entities READ in code and WRITTEN in tests.
    
    These are entities that are:
    - Used/referenced in the implementation code
    - Defined/created in the test code (e.g., test fixtures, mock objects)
    
    Args:
        code_entities: Entities from code patch
        test_entities: Entities from test patch
        
    Returns:
        Set of entity names for backward hints
    """
    return augment_identifiers(
        code_entities=code_entities,
        test_entities=test_entities,
        code_access=AccessType.READ,
        test_access=AccessType.WRITE
    )


def analyze_patches(code_patch: str, test_patch: str) -> Dict:
    """
    Analyze code and test patches to extract forward and backward hints.
    
    Args:
        code_patch: Python code from feature/implementation patch
        test_patch: Python code from test patch
        
    Returns:
        Dictionary with:
        - 'forward': Set[str] - forward hints
        - 'backward': Set[str] - backward hints
        - 'code_entities': Set[Entity] - all code entities
        - 'test_entities': Set[Entity] - all test entities
    """
    code_entities = extract_entities_from_code(code_patch)
    test_entities = extract_entities_from_code(test_patch)
    
    return {
        'forward': augment_ident_forward(code_entities, test_entities),
        'backward': augment_ident_backward(code_entities, test_entities),
        'code_entities': code_entities,
        'test_entities': test_entities
    }


# Example usage and demonstration
if __name__ == '__main__':
    # Example code patch (implementation)
    code_patch = """
def calculate_total(items):
    '''Calculate total with markup'''
    return sum(item * 1.1 for item in items)

class PriceCalculator:
    def __init__(self):
        self.markup = 1.1
    
    def calculate(self, price):
        return price * self.markup
"""

    # Example test patch
    test_patch = """
def test_calculate_total():
    items = [10, 20, 30]
    result = calculate_total(items)
    assert result == 66.0

def test_price_calculator():
    calculator = PriceCalculator()
    result = calculator.calculate(100)
    assert result == 110.0
    
def setup_test_data():
    '''Create test fixtures'''
    test_items = [1, 2, 3]
    return test_items
"""

    # Analyze patches
    results = analyze_patches(code_patch, test_patch)
    
    print("=" * 60)
    print("TREE-SITTER ENTITY ANALYSIS RESULTS")
    print("=" * 60)
    
    print("\n📝 Code Entities:")
    for entity in sorted(results['code_entities'], key=lambda e: (e.name, e.access_type.value)):
        print(f"  {entity}")
    
    print("\n🧪 Test Entities:")
    for entity in sorted(results['test_entities'], key=lambda e: (e.name, e.access_type.value)):
        print(f"  {entity}")
    
    print("\n" + "=" * 60)
    print("AUGMENTATION HINTS")
    print("=" * 60)
    
    print("\n➡️  Forward Hints (code[WRITE] ∩ test[READ]):")
    print("   (Entities defined in code and used in tests)")
    for name in sorted(results['forward']):
        print(f"  - {name}")
    
    print("\n⬅️  Backward Hints (code[READ] ∩ test[WRITE]):")
    print("   (Entities used in code and defined in tests)")
    for name in sorted(results['backward']):
        print(f"  - {name}")
    
    print("\n" + "=" * 60)
    print("\n✅ Tree-sitter analysis complete!")

# Made with Bob
