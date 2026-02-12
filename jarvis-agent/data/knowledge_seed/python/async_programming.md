# Python - Programación Asíncrona

## Async/Await Basics
```python
import asyncio

async def fetch_data():
    await asyncio.sleep(1)
    return "Data fetched"

async def main():
    result = await fetch_data()
    print(result)

asyncio.run(main())
```

## Coroutines
```python
async def coroutine_example():
    print("Start")
    await asyncio.sleep(1)
    print("End")
    return "Result"

# Ejecutar
result = asyncio.run(coroutine_example())
```

## Gather - Ejecutar múltiples coroutines
```python
async def task1():
    await asyncio.sleep(1)
    return "Task 1"

async def task2():
    await asyncio.sleep(2)
    return "Task 2"

async def main():
    results = await asyncio.gather(task1(), task2())
    print(results)  # ['Task 1', 'Task 2']

asyncio.run(main())
```

## Create Task
```python
async def background_task():
    while True:
        print("Running...")
        await asyncio.sleep(1)

async def main():
    task = asyncio.create_task(background_task())
    await asyncio.sleep(5)
    task.cancel()

asyncio.run(main())
```

## Async Context Managers
```python
class AsyncResource:
    async def __aenter__(self):
        print("Acquiring resource")
        await asyncio.sleep(1)
        return self
    
    async def __aexit__(self, *args):
        print("Releasing resource")
        await asyncio.sleep(1)

async def main():
    async with AsyncResource() as resource:
        print("Using resource")

asyncio.run(main())
```

## Async Generators
```python
async def async_generator():
    for i in range(5):
        await asyncio.sleep(1)
        yield i

async def main():
    async for value in async_generator():
        print(value)

asyncio.run(main())
```

## aiohttp - HTTP Requests Async
```python
import aiohttp
import asyncio

async def fetch(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.text()

async def main():
    html = await fetch('https://example.com')
    print(html[:100])

asyncio.run(main())
```

## Semaphore - Limitar concurrencia
```python
async def worker(semaphore, n):
    async with semaphore:
        print(f"Worker {n} starting")
        await asyncio.sleep(2)
        print(f"Worker {n} done")

async def main():
    semaphore = asyncio.Semaphore(3)  # Max 3 concurrent
    
    tasks = [worker(semaphore, i) for i in range(10)]
    await asyncio.gather(*tasks)

asyncio.run(main())
```

## Queue - Comunicación entre coroutines
```python
async def producer(queue):
    for i in range(5):
        await queue.put(i)
        print(f"Produced {i}")
        await asyncio.sleep(1)

async def consumer(queue):
    while True:
        item = await queue.get()
        print(f"Consumed {item}")
        queue.task_done()

async def main():
    queue = asyncio.Queue()
    
    prod = asyncio.create_task(producer(queue))
    cons = asyncio.create_task(consumer(queue))
    
    await prod
    await queue.join()
    cons.cancel()

asyncio.run(main())
```
