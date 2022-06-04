import asyncio
import re

import aiohttp


class RetryException(RuntimeError):
    pass


def traverse_object(obj, key_path: str):
    int_re = re.compile("^\\[\\d+]$")
    try:
        for key in key_path.split(">"):
            if int_re.match(key):  # index
                i = int(key[1:-1])
                obj = obj[i]
            else:
                obj = obj[key]
        return obj
    except KeyError:
        return None


class Api:
    def __init__(self,
                 endpoint: str,
                 headers: dict = None,
                 max_connections: int = 10):
        self.endpoint = endpoint
        self.headers = headers or {}
        self.headers.setdefault("Cache-Control", "no-cache")
        self.session = aiohttp.ClientSession(headers=self.headers)
        self.semaphore = asyncio.Semaphore(max_connections)

    async def _query(self, script_name: str, **kwargs):
        print(f"Fetching {script_name}")

        query = open(f"./graphql/{script_name}.graphql", "r").read()

        for key, value in kwargs.items():  # replace kwarg variables
            query = query.replace(f"${key}", value)

        async with self.semaphore:
            r = await self.session.post(self.endpoint, json={"query": query})

        if r.status == 204 or r.status == 202:
            raise RetryException()

        result = await r.json()
        if result is None:
            raise RetryException()

        return result

    async def query(self, script_name: str, **kwargs):
        for _ in range(25):
            try:
                return await self._query(script_name, **kwargs)
            except RetryException:
                print(f"[{script_name}] Retrying...")

    async def paginated_query(self, script_name: str, nodes_key: str, next_key: str, use_first: bool = False, **kwargs):
        res = await self.query(f'{script_name}{use_first and ".first" or ""}', cursor="null")
        next_cursor = traverse_object(res, next_key)
        nodes = traverse_object(res, nodes_key)
        while next_cursor:  # if has next page, fetch it and append nodes
            res = await self.query(script_name, cursor=f'"{next_cursor}"', **kwargs)
            nodes += traverse_object(res, nodes_key) or []
            next_cursor = traverse_object(res, next_key)
        return nodes
