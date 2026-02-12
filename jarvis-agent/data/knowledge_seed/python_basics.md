# Python - Conceptos Básicos

## Tipos de datos
- `str`: Cadenas de texto
- `int`: Números enteros
- `float`: Números decimales
- `bool`: Verdadero/Falso
- `list`: Listas mutables [1, 2, 3]
- `tuple`: Tuplas inmutables (1, 2, 3)
- `dict`: Diccionarios {key: value}
- `set`: Conjuntos {1, 2, 3}

## Estructuras de control

### Condicionales
```python
if condition:
    # código
elif other_condition:
    # código
else:
    # código
```

### Bucles
```python
# For loop
for item in iterable:
    print(item)

# While loop
while condition:
    # código
```

## Funciones
```python
def nombre_funcion(param1, param2="default"):
    """Docstring explicativo"""
    return resultado
```

## List comprehensions
```python
# Crear lista
numeros = [x**2 for x in range(10)]

# Con filtro
pares = [x for x in range(10) if x % 2 == 0]
```

## Manejo de errores
```python
try:
    # código que puede fallar
    resultado = funcion()
except ValueError as e:
    # manejar error específico
    print(f"Error: {e}")
except Exception as e:
    # manejar cualquier error
    print(f"Error inesperado: {e}")
finally:
    # siempre se ejecuta
    cleanup()
```

## Decoradores
```python
def mi_decorador(func):
    def wrapper(*args, **kwargs):
        print("Antes")
        result = func(*args, **kwargs)
        print("Después")
        return result
    return wrapper

@mi_decorador
def funcion():
    print("Función ejecutándose")
```

## Context managers
```python
with open('archivo.txt', 'r') as f:
    contenido = f.read()
```

## Generadores
```python
def contador(n):
    i = 0
    while i < n:
        yield i
        i += 1
```
