import docker
import docker.errors
import config

_client: docker.DockerClient | None = None


def _get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.DockerClient(base_url=config.DOCKER_PROXY_URL)
    return _client


def get_container(name: str) -> docker.models.containers.Container:
    return _get_client().containers.get(name)


def start_container(name: str) -> None:
    get_container(name).start()


def stop_container(name: str) -> None:
    try:
        get_container(name).stop()
    except docker.errors.NotFound:
        pass


def container_status(name: str) -> str:
    try:
        return get_container(name).status
    except docker.errors.NotFound:
        return "not found"
