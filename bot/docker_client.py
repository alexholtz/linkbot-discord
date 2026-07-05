import docker
import docker.errors
import config

_client: docker.DockerClient | None = None


def _get_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.DockerClient(base_url=config.DOCKER_PROXY_URL)
    return _client


def get_container() -> docker.models.containers.Container:
    return _get_client().containers.get(config.TARGET_CONTAINER_NAME)


def start_container() -> None:
    get_container().start()


def stop_container() -> None:
    try:
        get_container().stop()
    except docker.errors.NotFound:
        pass


def container_status() -> str:
    try:
        return get_container().status
    except docker.errors.NotFound:
        return "not found"
