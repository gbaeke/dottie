"""A small set of text files held somewhere else, shown to the agent as a filesystem.

Used in two places: the app (wiki pages and skills in PostgreSQL) and the agent runtime in the sandbox (the same files,
reached over HTTP). One implementation, so both behave the same.
"""

import time
from datetime import UTC, datetime

import httpx
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


class RemoteFiles(DictFiles):
    """Files kept by the app, read and written through its run-scoped API (`/internal/<area>`).

    The files arrive with the run's context and are served from memory for `FRESH_SECONDS` (our own writes keep the
    copy current): reading the wiki costs no round trip to the app each time. After that they are fetched again, so an
    edit the user makes in the UI during a long run is seen.
    """

    FRESH_SECONDS = 30.0

    def __init__(
        self, client: httpx.Client, area: str, *, read_only: bool = False, preload: list[dict[str, str]] | None = None
    ):
        self.client, self.area, self.read_only = client, area, read_only
        self._cache: dict[str, str] | None = None
        self._fetched = 0.0
        if preload is not None:
            self._cache, self._fetched = {item["path"]: item["content"] for item in preload}, time.monotonic()

    def load(self) -> dict[str, str]:
        if self._cache is None or time.monotonic() - self._fetched > self.FRESH_SECONDS:
            found = self.client.get(f"/{self.area}")
            found.raise_for_status()
            self._cache = {item["path"]: item["content"] for item in found.json()}
            self._fetched = time.monotonic()
        return dict(self._cache)

    def store(self, path: str, content: str) -> None:
        self.client.put(f"/{self.area}{path}", json={"content": content}).raise_for_status()
        self.load()  # make sure there is a copy to update
        if self._cache is not None:
            self._cache[path] = content

    def remove(self, path: str) -> None:
        self.client.delete(f"/{self.area}{path}").raise_for_status()
        if self._cache is not None:
            self._cache.pop(path, None)
