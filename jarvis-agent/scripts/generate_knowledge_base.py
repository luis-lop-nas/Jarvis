#!/usr/bin/env python3
"""
Genera base de conocimiento completa con ~5,000 documentos.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.knowledge.knowledge_base import KnowledgeBase


# Contenido de documentos organizados por categoría
PYTHON_DOCS = {
    "OOP - Clases y Objetos": """
# Python - Programación Orientada a Objetos

## Clases básicas
```python
class Person:
    def __init__(self, name, age):
        self.name = name
        self.age = age
    
    def greet(self):
        return f"Hola, soy {self.name}"

person = Person("Juan", 30)
print(person.greet())
```

## Herencia
```python
class Employee(Person):
    def __init__(self, name, age, salary):
        super().__init__(name, age)
        self.salary = salary
    
    def work(self):
        return f"{self.name} está trabajando"
```

## Métodos especiales
```python
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
    
    def __str__(self):
        return f"Point({self.x}, {self.y})"
    
    def __add__(self, other):
        return Point(self.x + other.x, self.y + other.y)
```

## Properties
```python
class Temperature:
    def __init__(self, celsius):
        self._celsius = celsius
    
    @property
    def fahrenheit(self):
        return self._celsius * 9/5 + 32
    
    @fahrenheit.setter
    def fahrenheit(self, value):
        self._celsius = (value - 32) * 5/9
```

## Class methods y Static methods
```python
class MyClass:
    count = 0
    
    def __init__(self):
        MyClass.count += 1
    
    @classmethod
    def get_count(cls):
        return cls.count
    
    @staticmethod
    def helper():
        return "Helper method"
```
""",

    "Type Hints": """
# Python - Type Hints

## Tipos básicos
```python
def greet(name: str) -> str:
    return f"Hello {name}"

age: int = 25
price: float = 19.99
is_active: bool = True
```

## Listas y Diccionarios
```python
from typing import List, Dict, Tuple, Set

names: List[str] = ["Alice", "Bob"]
scores: Dict[str, int] = {"Alice": 100, "Bob": 95}
point: Tuple[int, int] = (10, 20)
tags: Set[str] = {"python", "typing"}
```

## Optional
```python
from typing import Optional

def find_user(user_id: int) -> Optional[str]:
    if user_id == 1:
        return "Alice"
    return None
```

## Union
```python
from typing import Union

def process(value: Union[int, str]) -> str:
    return str(value)
```

## Callable
```python
from typing import Callable

def apply(func: Callable[[int, int], int], x: int, y: int) -> int:
    return func(x, y)

def add(a: int, b: int) -> int:
    return a + b

result = apply(add, 5, 3)
```

## Generic Types
```python
from typing import TypeVar, Generic

T = TypeVar('T')

class Stack(Generic[T]):
    def __init__(self):
        self.items: List[T] = []
    
    def push(self, item: T) -> None:
        self.items.append(item)
    
    def pop(self) -> T:
        return self.items.pop()
```
""",

    "Testing con Pytest": """
# Python - Testing con Pytest

## Instalación
```bash
pip install pytest
```

## Test básico
```python
# test_calculator.py
def add(a, b):
    return a + b

def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
```

## Fixtures
```python
import pytest

@pytest.fixture
def sample_data():
    return [1, 2, 3, 4, 5]

def test_sum(sample_data):
    assert sum(sample_data) == 15
```

## Parametrize
```python
@pytest.mark.parametrize("input,expected", [
    (2, 4),
    (3, 9),
    (4, 16),
])
def test_square(input, expected):
    assert input ** 2 == expected
```

## Testing exceptions
```python
def test_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        result = 1 / 0
```

## Mocking
```python
from unittest.mock import Mock, patch

def test_with_mock():
    mock_func = Mock(return_value=42)
    assert mock_func() == 42
    mock_func.assert_called_once()

@patch('module.function')
def test_with_patch(mock_function):
    mock_function.return_value = "mocked"
    # Test code
```

## Ejecutar tests
```bash
pytest                    # Todos los tests
pytest test_file.py      # Archivo específico
pytest -v                # Verbose
pytest -k "test_add"     # Tests que matchean
pytest --cov             # Coverage
```
""",
}

# Voy a crear el script completo en el siguiente mensaje...
# Para no hacer este mensaje demasiado largo
