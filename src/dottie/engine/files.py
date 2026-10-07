"""A dottie's long-term files, kept in PostgreSQL and shown to its agent as a filesystem.

The agent only sees paths: `/wiki/index.md`, `/skills/<name>/SKILL.md`. Behind `/wiki/` are rows of `wiki_pages`, behind
`/skills/` the skills the dottie was given (read-only). Both are mounted next to the sandbox with a CompositeBackend, so
the knowledge outlives any sandbox and the agent edits it with the same tools it uses for every other file.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from dottie_runtime.files import DictFiles

from ..models import Dottie, WikiPage

SessionFactory = sessionmaker[Session]


class WikiFiles(DictFiles):
    """`/wiki/`: the pages of one dottie's wiki. `updated_by` records whether the dottie or the user wrote a page."""

    def __init__(self, sessions: SessionFactory, dottie_id: int, author: str = "dottie"):
        self.sessions, self.dottie_id, self.author = sessions, dottie_id, author
        self.written: list[str] = []  # paths changed through this backend: the run reports them as wiki events

    def load(self) -> dict[str, str]:
        with self.sessions() as s:
            rows = s.execute(select(WikiPage.path, WikiPage.content).where(WikiPage.dottie_id == self.dottie_id))
            return {"/" + path: content for path, content in rows}

    def store(self, path: str, content: str) -> None:
        with self.sessions() as s:
            key = path.lstrip("/")
            page = s.scalar(select(WikiPage).where(WikiPage.dottie_id == self.dottie_id, WikiPage.path == key))
            if page is None:
                s.add(WikiPage(dottie_id=self.dottie_id, path=key, content=content, updated_by=self.author))
            else:
                page.content, page.updated_by = content, self.author
            s.commit()
        self.written.append(path.lstrip("/"))

    def remove(self, path: str) -> None:
        with self.sessions() as s:
            s.execute(delete(WikiPage).where(WikiPage.dottie_id == self.dottie_id, WikiPage.path == path.lstrip("/")))
            s.commit()
        self.written.append(path.lstrip("/"))


class SkillFiles(DictFiles):
    """`/skills/`: the skills a dottie was given, each as `<name>/SKILL.md`. Readable by the agent, not changeable."""

    read_only = True
    read_only_message = "Skills are managed by the user and cannot be changed from here."

    def __init__(self, sessions: SessionFactory, dottie_id: int):
        self.sessions, self.dottie_id = sessions, dottie_id

    def load(self) -> dict[str, str]:
        with self.sessions() as s:
            dottie = s.get(Dottie, self.dottie_id)
            skills = dottie.skills if dottie else []
            return {f"/{k.name}/SKILL.md": skill_markdown(k.name, k.description, k.body) for k in skills}


def skill_markdown(name: str, description: str, body: str) -> str:
    """A SKILL.md: the frontmatter Deep Agents reads to list the skill, then its instructions."""
    one_line = " ".join(description.split()).replace('"', "'")
    return f'---\nname: {name}\ndescription: "{one_line}"\n---\n\n{body.strip()}\n'


def seed_wiki(session: Session, dottie: Dottie) -> None:
    """The pages a new dottie starts with. `index.md` is always in the agent's prompt: it is the table of contents."""
    pages = {
        "index.md": (
            f"# {dottie.name}'s wiki\n\n"
            "This is my long-term memory. It is always shown to me when I wake up, so I keep it short and use it as a "
            "table of contents: one line per page, `[[page]]` links to the pages that hold the detail.\n\n"
            "## Pages\n\n"
            "- [[user]]: what I know about the person I work for\n"
            "- [[log]]: what I did and learned, newest last\n"
        ),
        "user.md": "# The user\n\nNothing yet. I write down preferences, people, projects and decisions here.\n",
        "log.md": "# Log\n\nOne line per session: date, what happened, what I learned.\n",
    }
    for path, content in pages.items():
        session.add(WikiPage(dottie_id=dottie.id, path=path, content=content, updated_by="dottie"))
