import time
from asyncio import create_task, sleep

total_time = 0


def speed_test(func):
    async def wrapper(*args, **kwargs):
        global total_time

        start_time = time.process_time()
        result = await func(*args, **kwargs)
        end_time = time.process_time()

        execution_time = end_time - start_time
        total_time += execution_time
        if execution_time != 0:
            print(f"Час виконання {func.__name__}: {execution_time} секунд")

        create_task(print_total_time())

        return result

    async def print_total_time():
        await sleep(5)
        global total_time

        if total_time != 0:
            print(f"-> Загальний час виконання: {total_time} секунд")
            total_time = 0

    return wrapper
