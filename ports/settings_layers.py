"""Resolve the settings two services start with.

Each setting comes from the first layer that has it: the environment,
then the config file, then the defaults. A layer that lacks a key is
not an error; a setting no layer has is. An empty value is a value:
the environment sets prefix to "" to switch the default off.
"""
from dataclasses import dataclass, field

class Missing(Exception): ...

@dataclass
class Layer:
    name: str
    values: dict[str, str]
    hits: int = 0

    def get(self, key: str) -> str | None:
        value = self.values.get(key)
        if value is not None:
            self.hits += 1
        return value

@dataclass
class Journal:
    entries: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        self.entries.append(text)

def find(key: str, layers: list[Layer]) -> tuple[str, str] | None:
    for layer in layers:
        value = layer.get(key)
        if value is not None:
            return value, layer.name
    return None

def resolve(key: str, layers: list[Layer], journal: Journal) -> str:
    found = find(key, layers)
    if found is None:
        raise Missing(key)
    value, source = found
    journal.note(f"{key} = {value!r} ({source})")
    return value

def address(layers: list[Layer], journal: Journal) -> str:
    host = resolve("host", layers, journal)
    port = resolve("port", layers, journal)
    prefix = find("prefix", layers)
    if prefix is None or prefix[0] == "":
        return f"{host}:{port}"
    return f"{host}:{port}{prefix[0]}"

def main() -> None:
    env = Layer("env", {"port": "9000", "prefix": ""})
    file = Layer("file", {"host": "db.internal", "user": "app"})
    defaults = Layer("defaults", {"host": "localhost", "port": "8080",
                                  "prefix": "/api"})
    layers = [env, file, defaults]
    journal = Journal()
    print("web at", address(layers, journal))
    print("web at", address([file, defaults], journal), "without env")
    for key in ["user", "password"]:
        try:
            print(key, "is", resolve(key, layers, journal))
        except Missing as e:
            print("no setting for", e)
    timeout = find("timeout", layers)
    print("timeout", "unset" if timeout is None else timeout[0])
    for layer in layers:
        print(layer.name, "answered", layer.hits)
    for entry in journal.entries:
        print(entry)

main()
