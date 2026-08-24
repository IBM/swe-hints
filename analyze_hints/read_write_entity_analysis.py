"""
Prototype for Read/Write Entity Analysis

This script analyzes code and test patches to identify entities that are:
- Written in code and read in tests (forward hints)
- Read in code and written in tests (backward hints)

The key insight is that entities can be classified as either read or write operations,
and we can compute intersections based on these access patterns.
"""

import ast
from typing import Set, Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum


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


class EntityAnalyzer(ast.NodeVisitor):
    """
    AST visitor that identifies entities and classifies them as read or write.
    
    Write operations:
    - Function/class definitions
    - Assignment targets
    - Augmented assignments (+=, -=, etc.)
    - For loop variables
    
    Read operations:
    - Function/class references (not definitions)
    - Variable usage in expressions
    - Attribute access (reading)
    """
    
    def __init__(self):
        self.entities: Set[Entity] = set()
        self.in_assignment_target = False
        self.defined_names: Set[str] = set()  # Track definitions
    
    def visit_FunctionDef(self, node):
        """Function definition is a WRITE operation"""
        self.entities.add(Entity(
            name=node.name,
            access_type=AccessType.WRITE,
            entity_type='function'
        ))
        self.defined_names.add(node.name)
        self.generic_visit(node)
    
    def visit_AsyncFunctionDef(self, node):
        """Async function definition is a WRITE operation"""
        self.entities.add(Entity(
            name=node.name,
            access_type=AccessType.WRITE,
            entity_type='function'
        ))
        self.defined_names.add(node.name)
        self.generic_visit(node)
    
    def visit_ClassDef(self, node):
        """Class definition is a WRITE operation"""
        self.entities.add(Entity(
            name=node.name,
            access_type=AccessType.WRITE,
            entity_type='class'
        ))
        self.defined_names.add(node.name)
        self.generic_visit(node)
    
    def visit_Assign(self, node):
        """Assignment: targets are WRITE, value is READ"""
        # Visit targets as WRITE
        old_in_assignment = self.in_assignment_target
        self.in_assignment_target = True
        for target in node.targets:
            self.visit(target)
        self.in_assignment_target = old_in_assignment
        
        # Visit value as READ
        self.visit(node.value)
    
    def visit_AugAssign(self, node):
        """Augmented assignment: target is both READ and WRITE"""
        # Target is read first, then written
        self.visit(node.target)  # READ
        old_in_assignment = self.in_assignment_target
        self.in_assignment_target = True
        self.visit(node.target)  # WRITE
        self.in_assignment_target = old_in_assignment
        self.visit(node.value)  # READ
    
    def visit_AnnAssign(self, node):
        """Annotated assignment"""
        if node.value:
            old_in_assignment = self.in_assignment_target
            self.in_assignment_target = True
            self.visit(node.target)
            self.in_assignment_target = old_in_assignment
            self.visit(node.value)
    
    def visit_For(self, node):
        """For loop: target is WRITE, iter is READ"""
        old_in_assignment = self.in_assignment_target
        self.in_assignment_target = True
        self.visit(node.target)
        self.in_assignment_target = old_in_assignment
        
        self.visit(node.iter)
        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)
    
    def visit_Name(self, node):
        """Name reference - context determines if READ or WRITE"""
        if self.in_assignment_target:
            self.entities.add(Entity(
                name=node.id,
                access_type=AccessType.WRITE,
                entity_type='variable'
            ))
            self.defined_names.add(node.id)
        else:
            # Only add as READ if it's not a builtin and not just defined
            if node.id not in dir(__builtins__):
                self.entities.add(Entity(
                    name=node.id,
                    access_type=AccessType.READ,
                    entity_type='variable'
                ))
        self.generic_visit(node)
    
    def visit_Attribute(self, node):
        """Attribute access"""
        # The attribute itself
        if self.in_assignment_target:
            self.entities.add(Entity(
                name=node.attr,
                access_type=AccessType.WRITE,
                entity_type='attribute'
            ))
        else:
            self.entities.add(Entity(
                name=node.attr,
                access_type=AccessType.READ,
                entity_type='attribute'
            ))
        
        # Visit the value (object being accessed)
        self.visit(node.value)
    
    def visit_Call(self, node):
        """Function call - the function name is READ"""
        # The called function/method is READ
        if isinstance(node.func, ast.Name):
            self.entities.add(Entity(
                name=node.func.id,
                access_type=AccessType.READ,
                entity_type='function'
            ))
        elif isinstance(node.func, ast.Attribute):
            self.entities.add(Entity(
                name=node.func.attr,
                access_type=AccessType.READ,
                entity_type='function'
            ))
        
        self.generic_visit(node)


def extract_entities_from_code(code: str) -> Set[Entity]:
    """
    Extract entities from Python code with read/write classification.
    
    Args:
        code: Python source code as string
        
    Returns:
        Set of Entity objects with access type information
    """
    try:
        tree = ast.parse(code)
        analyzer = EntityAnalyzer()
        analyzer.visit(tree)
        return analyzer.entities
    except SyntaxError:
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
    print("ENTITY ANALYSIS RESULTS")
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
    print("\n✅ Analysis complete!")

# Made with Bob
