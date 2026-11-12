"""Run a build: each task after the tasks it needs, a flaky task
retried up to three times, and a task whose dependency failed
skipped. The clock is simulated, so the report is repeatable."""
from dataclasses import dataclass, field

class Failed(Exception): ...

@dataclass
class Task:
    name: str
    needs: list[str]
    seconds: int
    failures: int = 0  # attempts that fail before one succeeds

@dataclass
class Clock:
    now: int = 0

    def sleep(self, seconds: int) -> None:
        self.now += seconds

@dataclass
class Report:
    lines: list[str] = field(default_factory=list)

    def note(self, text: str) -> None:
        self.lines.append(text)

RETRIES = 3

def attempt(task: Task, tries: dict[str, int], clock: Clock) -> None:
    tries[task.name] = tries.get(task.name, 0) + 1
    clock.sleep(task.seconds)
    if tries[task.name] <= task.failures:
        raise Failed(task.name)

def run(task: Task, tries: dict[str, int], clock: Clock,
        report: Report) -> bool:
    for n in range(1, RETRIES + 1):
        try:
            attempt(task, tries, clock)
        except Failed:
            report.note(f"{task.name}: attempt {n} failed")
            clock.sleep(2 ** n)
            continue
        report.note(f"{task.name}: ok at t={clock.now}")
        return True
    return False

def build(tasks: list[Task], clock: Clock, report: Report) -> dict[str, str]:
    status: dict[str, str] = {}
    tries: dict[str, int] = {}
    for task in tasks:
        blocked = [n for n in task.needs if status.get(n) != "ok"]
        if blocked:
            status[task.name] = "skipped"
            report.note(f"{task.name}: skipped, needs {', '.join(blocked)}")
        elif run(task, tries, clock, report):
            status[task.name] = "ok"
        else:
            status[task.name] = "failed"
    return status

def main() -> None:
    tasks = [
        Task("fetch", [], 3, failures=1),
        Task("compile", ["fetch"], 10),
        Task("lint", ["fetch"], 2, failures=5),
        Task("test", ["compile"], 7, failures=2),
        Task("package", ["test", "lint"], 4),
        Task("docs", [], 1),
    ]
    clock = Clock()
    report = Report()
    status = build(tasks, clock, report)
    for line in report.lines:
        print(line)
    for name, result in status.items():
        print(f"{name:8} {result}")
    counts = {r: list(status.values()).count(r) for r in sorted(set(status.values()))}
    print(counts, f"in {clock.now}s")

main()
