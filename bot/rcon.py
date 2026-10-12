from aiomcrcon import Client as RconClient


async def send_command(host: str, port: int, password: str, command: str) -> str:
    """Open a short-lived RCON connection, send one command, and return the response text."""
    async with RconClient(host, port, password) as rcon:
        response, _ = await rcon.send_cmd(command)
        return response
