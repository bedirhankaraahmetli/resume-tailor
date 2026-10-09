"""Make both languages exactly one page, deterministically, with no extra LLM call.

Fitting is joint: Turkish runs longer than English, but both PDFs must carry the same
selection, so every drop applies to both and the loop stops only when both fit.

Never shrinks fonts, margins or spacing. Order of removal (PROMPT.md §5.5):
  1. the lowest-priority bullet (each experience and project keeps at least one);
  2. the lowest-ranked project, while more than `min_projects` remain;
  3. trailing certificates, then trailing courses (beyond `min_courses`);
  4. otherwise fail with a clear message.
If both pages are more than `fill_threshold` empty, reserve bullets are added in order
while both still fit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from .build import PdfInfo
from .models import Bullet, Tailoring

Compiler = Callable[[str, Tailoring], PdfInfo]


class FitError(RuntimeError):
    pass


@dataclass
class FitResult:
    tailoring: Tailoring
    info: dict[str, PdfInfo]
    log: list[str] = field(default_factory=list)


def _drop_one(t: Tailoring, min_projects: int, min_courses: int, log: list[str]) -> bool:
    # (priority, is_project, project_rank, bullet_index) – the max is dropped first, so a
    # higher priority number goes first, projects before experience, lower ranks first.
    holders: list[tuple[int, int, str, list[Bullet]]] = [
        (0, -1, e.id, e.bullets) for e in t.experience
    ] + [(1, rank, p.id, p.bullets) for rank, p in enumerate(t.projects)]
    best: tuple[tuple[int, int, int, int], str, list[Bullet], int] | None = None
    for is_project, rank, owner, bullets in holders:
        if len(bullets) > 1:
            for i, b in enumerate(bullets):
                key = (b.priority, is_project, rank, i)
                if best is None or key > best[0]:
                    best = (key, owner, bullets, i)
    if best is not None:
        _, owner, bullets, i = best
        removed = bullets.pop(i)
        log.append(f"dropped bullet {i + 1} of {owner} (priority {removed.priority})")
        return True
    if len(t.projects) > min_projects:
        p = t.projects.pop()
        t.reserve = [r for r in t.reserve if r.parent != p.id]
        log.append(f"dropped project {p.id}")
        return True
    if len(t.certificates) > 1:
        log.append(f"dropped certificate {t.certificates.pop()}")
        return True
    if t.education and len(t.education[0].courses) > min_courses:
        log.append(f"dropped course {t.education[0].courses.pop()}")
        return True
    return False


def fit(t: Tailoring, compile_fn: Compiler, *, min_projects: int, min_courses: int,
        fill_threshold: float, max_steps: int = 80) -> FitResult:
    t = t.model_copy(deep=True)
    log: list[str] = []
    info: dict[str, PdfInfo] = {}
    for _ in range(max_steps):
        info = {lang: compile_fn(lang, t) for lang in ("en", "tr")}
        # Width first: a heading row wider than the page loses its least relevant stack
        # item (the list is ranked), in both languages, before anything else is judged.
        wide = list(dict.fromkeys(p for i in info.values() for p in i.overflow_projects))
        if wide:
            for pid in wide:
                proj = next(p for p in t.projects if p.id == pid)
                if len(proj.stack) <= 1:
                    raise FitError(f"the heading of {pid} is wider than the page even with one "
                                   "stack item; shorten its title")
                log.append(f"heading of {pid} too wide: dropped stack item '{proj.stack.pop()}'")
            continue
        if all(i.pages == 1 for i in info.values()):
            break
        if not _drop_one(t, min_projects, min_courses, log):
            pages = ", ".join(f"{k}: {v.pages} pages" for k, v in info.items())
            raise FitError(
                f"cannot fit on one page ({pages}) without dropping experience, going below "
                f"{min_projects} projects or {min_courses} courses, or touching the layout. "
                "Shorten bullets in the inventory or lower resume.min_projects."
            )
    else:
        raise FitError("fit loop did not converge")

    while t.reserve and all(i.empty_fraction > fill_threshold for i in info.values()):
        r = t.reserve.pop(0)
        holders = {x.id: x.bullets for x in t.experience} | {x.id: x.bullets for x in t.projects}
        target = holders.get(r.parent)
        if target is None:
            continue
        target.append(r.bullet)
        trial = {lang: compile_fn(lang, t) for lang in ("en", "tr")}
        if any(i.pages != 1 for i in trial.values()):
            target.pop()
            log.append(f"reserve bullet for {r.parent} did not fit; stopped filling")
            break
        info = trial
        log.append(f"added reserve bullet to {r.parent}")
    return FitResult(t, info, log)
