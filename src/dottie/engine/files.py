"""A dottie's long-term files, kept in PostgreSQL and shown to its agent as a filesystem.

The agent only sees paths: `/wiki/index.md`, `/skills/<name>/SKILL.md`. Behind `/wiki/` are rows of `wiki_pages`, behind
`/skills/` the skills the dottie was given (read-only). Both are mounted next to the sandbox with a CompositeBackend, so
the knowledge outlives any sandbox and the agent edits it with the same tools it uses for every other file.
"""

from datetime import UTC, datetime

from deepagents.backends.protocol import (
    BackendProtocol,
    DeleteResult,
    EditResult,
    FileData,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GlobResult,
    GrepResult,
    LsResult,
    ReadResult,
    WriteResult,
)
from deepagents.backends.utils import (
    _glob_search_files,  # pyright: ignore[reportPrivateUsage]  (the shared glob contract; no public form)
    create_file_data,
    file_data_to_string,
    grep_matches_from_files,
    perform_string_replacement,
    slice_read_response,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from ..models import Dottie, WikiPage

SessionFactory = sessionmaker[Session]


class DictFiles(BackendProtocol):
    """The filesystem tools over a small set of text files held somewhere else.

    Subclasses say where: `load()` returns every file, `store()` and `remove()` persist a change. The set is small
    (a wiki page or a skill is a few kilobytes), so each call just loads it all.
    """

    def load(self) -> dict[str, str]:
        raise NotImplementedError

    def store(self, path: str, content: str) -> None:
        raise NotImplementedError

    def remove(self, path: str) -> None:
        raise NotImplementedError

    read_only: bool = False
    read_only_message = "This area is read-only."

    def _files(self) -> dict[str, FileData]:
        now = datetime.now(UTC).isoformat()
        return {p: create_file_data(c, created_at=now) for p, c in self.load().items()}

    def ls(self, path: str) -> LsResult:
        prefix = path if path.endswith("/") else path + "/"
        entries: list[FileInfo] = []
        directories: set[str] = set()
        for p, data in self._files().items():
            if not p.startswith(prefix):
                continue
            rest = p[len(prefix) :]
            if "/" in rest:
                directories.add(prefix + rest.split("/")[0] + "/")
            else:
                entries.append(
                    {
                        "path": p,
                        "is_dir": False,
                        "size": len(file_data_to_string(data).encode()),
                        "modified_at": data.get("modified_at", ""),
                    }
                )
        entries.extend({"path": d, "is_dir": True, "size": 0, "modified_at": ""} for d in sorted(directories))
        return LsResult(entries=sorted(entries, key=lambda e: e["path"]))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        data = self._files().get(file_path)
        if data is None:
            return ReadResult(error=f"File '{file_path}' not found")
        return slice_read_response(data, offset, limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        if self.read_only:
            return WriteResult(error=self.read_only_message)
        if file_path in self.load():
            return WriteResult(error=f"'{file_path}' already exists. Read it and use edit_file to change it.")
        self.store(file_path, content)
        return WriteResult(path=file_path)

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        if self.read_only:
            return EditResult(error=self.read_only_message)
        current = self.load().get(file_path)
        if current is None:
            return EditResult(error=f"Error: File '{file_path}' not found")
        result = perform_string_replacement(current, old_string, new_string, replace_all)
        if isinstance(result, str):
            return EditResult(error=result)
        content, occurrences = result
        self.store(file_path, content)
        return EditResult(path=file_path, occurrences=int(occurrences))

    def delete(self, file_path: str) -> DeleteResult:
        if self.read_only:
            return DeleteResult(error=self.read_only_message)
        if file_path not in self.load():
            return DeleteResult(error=f"File '{file_path}' not found")
        self.remove(file_path)
        return DeleteResult(path=file_path)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Raw bytes of files: how the memory middleware loads `/wiki/index.md` into the prompt."""
        files = self.load()
        return [
            FileDownloadResponse(path=p, content=files[p].encode())
            if p in files
            else FileDownloadResponse(path=p, error="file_not_found")
            for p in paths
        ]

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results: list[FileUploadResponse] = []
        for path, content in files:
            if self.read_only:
                results.append(FileUploadResponse(path=path, error="permission_denied"))
            else:
                self.store(path, content.decode(errors="replace"))
                results.append(FileUploadResponse(path=path))
        return results

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        files = self._files()
        found = _glob_search_files(files, pattern, path)
        if found == "No files found":
            return GlobResult(matches=[])
        return GlobResult(
            matches=[{"path": p, "is_dir": False, "size": len(self.load()[p].encode())} for p in found.split("\n")]
        )

    def grep(
        self, pattern: str, path: str | None = None, glob: str | None = None, *, max_count: int | None = None
    ) -> GrepResult:
        return grep_matches_from_files(self._files(), pattern, path or "/", glob, max_count=max_count)


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
