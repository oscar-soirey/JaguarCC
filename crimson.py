#!/usr/bin/env python3
"""
Crimson - standalone package manager.

Crimson is independent from the Jaguar language. It only understands:
- GitHub repositories named "jaguar-<package>"
- a .crimson TOML manifest at the repository root
- GitHub Releases/tags

Example:
    crimson install myapi
    crimson install myapi -v 0.3.4
    crimson update myapi
    crimson remove myapi
    crimson list
    crimson search myapi
    crimson info myapi
    crimson --version

Environment:
    CRIMSON_GITHUB_TOKEN
        Optional GitHub token. It increases GitHub API rate limits.

Dependencies:
    requests
    packaging
"""

from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import requests
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

CRIMSON_VERSION = "1.0.0"
GITHUB_API = "https://api.github.com"
REPO_PREFIX = "jaguar-"
MANIFEST_NAME = ".crimson"
PACKAGES_DIR_NAME = "packages"
REQUEST_TIMEOUT = 30


class CrimsonError(Exception):
    """Expected Crimson error shown without a Python traceback."""


class Crimson:
    def __init__(self, script_path: Path | None = None) -> None:
        self.script_path = (script_path or Path(__file__)).resolve()
        self.root_dir = self.script_path.parent
        self.packages_dir = self.root_dir / PACKAGES_DIR_NAME
        self.packages_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": f"Crimson/{CRIMSON_VERSION}",
            }
        )

        token = os.environ.get("CRIMSON_GITHUB_TOKEN")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    # ------------------------------------------------------------------
    # GitHub
    # ------------------------------------------------------------------

    def github_get(self, endpoint: str, **params: Any) -> Any:
        url = endpoint if endpoint.startswith("http") else GITHUB_API + endpoint

        try:
            response = self.session.get(
                url,
                params=params or None,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise CrimsonError(f"GitHub connection failed: {exc}") from exc

        if response.status_code == 403:
            remaining = response.headers.get("X-RateLimit-Remaining")
            if remaining == "0":
                raise CrimsonError(
                    "GitHub API rate limit reached. "
                    "Set CRIMSON_GITHUB_TOKEN to use an authenticated API request."
                )

        if response.status_code == 404:
            raise CrimsonError(f"GitHub resource not found: {url}")

        if not response.ok:
            try:
                message = response.json().get("message", response.text)
            except ValueError:
                message = response.text
            raise CrimsonError(
                f"GitHub API error ({response.status_code}): {message}"
            )

        return response.json()

    def search_repositories(self, package_name: str) -> list[dict[str, Any]]:
        package_name = normalize_package_name(package_name)
        full_name = REPO_PREFIX + package_name

        data = self.github_get(
            "/search/repositories",
            q=f"{full_name} in:name",
            per_page=100,
        )

        items = data.get("items", [])
        exact = [
            repo
            for repo in items
            if repo.get("name", "").lower() == full_name.lower()
        ]

        # Exact repository name is preferred. If none exists, return the
        # matching search results so the user can choose a repository.
        return exact or items

    def select_repository(
        self,
        package_name: str,
        *,
        interactive: bool = True,
    ) -> dict[str, Any]:
        repos = self.search_repositories(package_name)

        if not repos:
            raise CrimsonError(
                f"No GitHub repository matching '{REPO_PREFIX}{package_name}' was found."
            )

        exact_name = REPO_PREFIX + normalize_package_name(package_name)
        exact = [
            repo
            for repo in repos
            if repo.get("name", "").lower() == exact_name.lower()
        ]

        if len(exact) == 1:
            return exact[0]

        if len(repos) == 1:
            return repos[0]

        if not interactive:
            names = ", ".join(repo.get("full_name", "?") for repo in repos[:10])
            raise CrimsonError(
                f"Several repositories match '{package_name}': {names}. "
                "Run 'crimson search <package>' to choose one."
            )

        print(f"Repositories matching {package_name}:")
        for index, repo in enumerate(repos, 1):
            print(
                f"  [{index}] {repo.get('full_name', '?')}"
                f" - {repo.get('description') or 'No description'}"
            )

        while True:
            answer = input("Choose a repository (q to cancel): ").strip()
            if answer.lower() == "q":
                raise CrimsonError("Cancelled.")
            try:
                choice = int(answer)
            except ValueError:
                print("Please enter a number.")
                continue

            if 1 <= choice <= len(repos):
                return repos[choice - 1]

            print("Invalid choice.")

    # ------------------------------------------------------------------
    # Manifest / versions
    # ------------------------------------------------------------------

    def read_manifest(self, directory: Path) -> dict[str, Any]:
        manifest = directory / MANIFEST_NAME

        if not manifest.is_file():
            raise CrimsonError(
                f"Missing {MANIFEST_NAME} in repository: {directory}"
            )

        try:
            import tomllib

            with manifest.open("rb") as file:
                data = tomllib.load(file)
        except ModuleNotFoundError:
            try:
                import tomli
            except ModuleNotFoundError as exc:
                raise CrimsonError(
                    "Python < 3.11 requires the 'tomli' package. "
                    "Install it with: pip install tomli"
                ) from exc

            try:
                with manifest.open("rb") as file:
                    data = tomli.load(file)
            except Exception as exc:
                raise CrimsonError(
                    f"Invalid {MANIFEST_NAME}: {exc}"
                ) from exc
        except Exception as exc:
            raise CrimsonError(f"Invalid {MANIFEST_NAME}: {exc}") from exc

        package = data.get("package")
        if not isinstance(package, dict):
            raise CrimsonError(f"{MANIFEST_NAME}: [package] section is missing.")

        name = package.get("friendly-name")
        version = package.get("version")

        if not isinstance(name, str) or not name.strip():
            raise CrimsonError(
                f"{MANIFEST_NAME}: package.friendly-name must be a string."
            )

        if not isinstance(version, str) or not version.strip():
            raise CrimsonError(
                f"{MANIFEST_NAME}: package.version must be a string."
            )

        dependencies = data.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise CrimsonError(
                f"{MANIFEST_NAME}: [dependencies] must be a table."
            )

        return data

    @staticmethod
    def package_version(manifest: dict[str, Any]) -> Version:
        raw = str(manifest["package"]["version"])
        try:
            return Version(raw)
        except InvalidVersion as exc:
            raise CrimsonError(
                f"Invalid package version in {MANIFEST_NAME}: {raw}"
            ) from exc

    @staticmethod
    def dependency_specifier(raw: str) -> SpecifierSet:
        """
        Supports normal PEP 440 specifiers plus Crimson's '^' shorthand.

        Examples:
            >=1.0.0
            ==1.2.0
            ^2.1.0
            ^0.3.4
            ~1.4.0
        """
        value = str(raw).strip()

        if value.startswith("^"):
            version_text = value[1:].strip()
            version = Version(version_text)

            if version.major > 0:
                upper = f"<{version.major + 1}.0.0"
            elif version.minor > 0:
                upper = f"<0.{version.minor + 1}.0"
            else:
                upper = f"<0.0.{version.micro + 1}"

            return SpecifierSet(f">={version},{upper}")

        if value.startswith("~"):
            version_text = value[1:].strip()
            version = Version(version_text)
            upper = f"<{version.major}.{version.minor + 1}.0"
            return SpecifierSet(f">={version},{upper}")

        # A bare version means an exact version.
        if re.fullmatch(r"v?\d+(?:\.\d+){1,3}(?:[-+][0-9A-Za-z.-]+)?", value):
            return SpecifierSet(f"=={value.lstrip('v')}")

        try:
            return SpecifierSet(value)
        except Exception as exc:
            raise CrimsonError(
                f"Invalid dependency version constraint: {raw}"
            ) from exc

    # ------------------------------------------------------------------
    # Releases / downloading
    # ------------------------------------------------------------------

    def get_release(
        self,
        repo: dict[str, Any],
        version: str,
    ) -> dict[str, Any]:
        owner = repo.get("owner", {}).get("login")
        name = repo.get("name")

        if not owner or not name:
            full_name = repo.get("full_name")
            if not full_name or "/" not in full_name:
                raise CrimsonError("GitHub repository information is incomplete.")
            owner, name = full_name.split("/", 1)

        # Crimson accepts both GitHub tag conventions:
        #   v1.0.0
        #   1.0.0
        # The requested semantic version is what matters.
        requested = str(version).strip().lstrip("v")

        # First try the conventional Crimson tag directly.
        for tag in (f"v{requested}", requested):
            try:
                release = self.github_get(
                    f"/repos/{owner}/{name}/releases/tags/{tag}"
                )
                if not release.get("draft"):
                    if release.get("prerelease"):
                        print(f"Warning: {tag} is marked as a GitHub prerelease.")
                    return release
            except CrimsonError:
                pass

        # Fallback: list releases and compare normalized versions. This also
        # handles tags with harmless differences such as a leading 'v'.
        releases = self.github_get(
            f"/repos/{owner}/{name}/releases",
            per_page=100,
        )

        try:
            requested_version = Version(requested)
        except InvalidVersion as exc:
            raise CrimsonError(
                f"Invalid requested package version: {version}"
            ) from exc

        for release in releases:
            if release.get("draft"):
                continue

            tag = str(release.get("tag_name", "")).strip().lstrip("v")
            try:
                release_version = Version(tag)
            except InvalidVersion:
                continue

            if release_version == requested_version:
                if release.get("prerelease"):
                    print(
                        f"Warning: {release.get('tag_name')} "
                        "is marked as a GitHub prerelease."
                    )
                return release

        raise CrimsonError(
            f"Release for version {requested_version} was not found for "
            f"{owner}/{name}. Checked tags 'v{requested}' and '{requested}'."
        )

    def get_latest_release(
        self,
        repo: dict[str, Any],
    ) -> dict[str, Any]:
        owner = repo.get("owner", {}).get("login")
        name = repo.get("name")

        if not owner or not name:
            full_name = repo.get("full_name")
            if not full_name or "/" not in full_name:
                raise CrimsonError("GitHub repository information is incomplete.")
            owner, name = full_name.split("/", 1)

        releases = self.github_get(
            f"/repos/{owner}/{name}/releases",
            per_page=100,
        )

        valid: list[tuple[Version, dict[str, Any]]] = []

        for release in releases:
            if release.get("draft") or release.get("prerelease"):
                continue

            tag = str(release.get("tag_name", "")).lstrip("v")
            try:
                version = Version(tag)
            except InvalidVersion:
                continue

            valid.append((version, release))

        if not valid:
            raise CrimsonError(
                f"No stable, semver-compatible GitHub release was found for "
                f"{owner}/{name}."
            )

        valid.sort(key=lambda item: item[0], reverse=True)
        return valid[0][1]

    def download_release(
        self,
        release: dict[str, Any],
        destination: Path,
    ) -> None:
        """
        Download the contents of the requested GitHub release.

        Crimson uses a release asset when the release provides one. If there
        is no package asset, it uses GitHub's generated source archive for
        the release tag. This is the exact tagged release snapshot, not the
        repository's current/default branch.
        """
        assets = release.get("assets", [])
        asset = None

        for candidate in assets:
            name = str(candidate.get("name", "")).lower()
            if name.endswith((".zip", ".tar", ".tar.gz", ".tgz")):
                asset = candidate
                break

        if asset:
            url = asset.get("browser_download_url")
            filename = str(asset.get("name") or "release.zip")
            source_description = f"release asset '{filename}'"
        else:
            # A GitHub Release always has generated source archives for its
            # tag, even when the author did not upload a custom asset.
            #
            # IMPORTANT: tarball_url belongs to THIS release object and is
            # generated from release['tag_name']. It is therefore a snapshot
            # of the requested release/tag, NOT the repository's current
            # default branch. Never fall back to /archive/refs/heads/main,
            # /archive/refs/heads/master, or any repository URL here.
            url = release.get("tarball_url")
            filename = "release.tar.gz"
            source_description = (
                f"GitHub release source archive for tag "
                f"'{release.get('tag_name', '?')}'"
            )

        if not url:
            raise CrimsonError(
                "The requested GitHub release has no downloadable contents "
                "(missing release asset and GitHub release source archive)."
            )

        print(f"Downloading {source_description}...")

        try:
            response = self.session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CrimsonError(f"Could not download release: {exc}") from exc

        destination.mkdir(parents=True, exist_ok=True)
        archive = destination / filename

        try:
            archive.write_bytes(response.content)
            self.extract_archive(archive, destination)
        finally:
            archive.unlink(missing_ok=True)

    @staticmethod
    def _safe_extract_path(base: Path, member_name: str) -> Path:
        target = (base / member_name).resolve()
        base_resolved = base.resolve()

        try:
            target.relative_to(base_resolved)
        except ValueError as exc:
            raise CrimsonError(
                f"Unsafe archive entry rejected: {member_name}"
            ) from exc

        return target

    def extract_archive(self, archive: Path, destination: Path) -> None:
        name = archive.name.lower()

        if name.endswith(".zip"):
            try:
                with zipfile.ZipFile(archive) as zf:
                    for info in zf.infolist():
                        target = self._safe_extract_path(
                            destination,
                            info.filename,
                        )

                        if info.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                            continue

                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as source, target.open("wb") as out:
                            shutil.copyfileobj(source, out)
            except zipfile.BadZipFile as exc:
                raise CrimsonError("Downloaded ZIP archive is invalid.") from exc
            return

        try:
            with tarfile.open(archive, mode="r:*") as tf:
                for member in tf.getmembers():
                    self._safe_extract_path(destination, member.name)

                # Python 3.12+ supports extraction filters. Keep compatibility
                # with older Python versions after our own path validation.
                tf.extractall(destination)
        except (tarfile.TarError, OSError) as exc:
            raise CrimsonError("Downloaded TAR archive is invalid.") from exc

    @staticmethod
    def find_source_root(directory: Path) -> Path:
        """
        Locate the payload root of a downloaded release archive.

        Unlike find_manifest_root(), this deliberately does not require a
        .crimson file: release archives are payloads and .crimson is owned by
        the repository root.
        """
        entries = list(directory.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            return entries[0]
        return directory

    @staticmethod
    def find_manifest_root(directory: Path) -> Path:
        """
        Legacy helper for callers that explicitly need a release manifest.

        Installation does not use this function: release archives are not
        authoritative for package metadata or dependencies.
        """
        direct = directory / MANIFEST_NAME
        if direct.is_file():
            return directory

        candidates = [
            path
            for path in directory.iterdir()
            if path.is_dir() and (path / MANIFEST_NAME).is_file()
        ]

        if len(candidates) == 1:
            return candidates[0]

        if not candidates:
            raise CrimsonError(
                f"Downloaded release does not contain {MANIFEST_NAME}."
            )

        raise CrimsonError(
            f"Downloaded release contains multiple possible {MANIFEST_NAME} files."
        )

    # ------------------------------------------------------------------
    # Local packages
    # ------------------------------------------------------------------

    def installed_package_dir(self, package_name: str) -> Path:
        return self.packages_dir / normalize_package_name(package_name)

    def installed_version(self, package_name: str) -> Version | None:
        directory = self.installed_package_dir(package_name)
        if not directory.is_dir():
            return None

        try:
            manifest = self.read_manifest(directory)
            return self.package_version(manifest)
        except CrimsonError:
            return None

    def install(
        self,
        package_name: str,
        requested_version: str | None = None,
        *,
        dependency_stack: tuple[str, ...] = (),
    ) -> None:
        package_name = normalize_package_name(package_name)

        if package_name in dependency_stack:
            chain = " -> ".join((*dependency_stack, package_name))
            raise CrimsonError(f"Circular dependency detected: {chain}")

        print(f"Searching GitHub for {REPO_PREFIX}{package_name}...")
        repo = self.select_repository(package_name)

        if requested_version is None:
            # The repository's .crimson manifest determines the default version.
            # To know it, download the default branch first.
            print("Reading package manifest to determine default version...")
            manifest = self.download_repository_manifest(repo)
            requested_version = str(manifest["package"]["version"])

        requested_version = requested_version.lstrip("v")

        release = self.get_release(repo, requested_version)
        release_tag = str(release.get("tag_name", requested_version))
        release_version = Version(release_tag.lstrip("v"))

        print(
            f"Installing {repo.get('full_name', repo.get('name', package_name))} "
            f"{release_version} ({release_tag})..."
        )

        temp_parent = Path(tempfile.mkdtemp(prefix="crimson-"))
        extracted = temp_parent / "package"

        try:
            self.download_release(release, extracted)

            # IMPORTANT: .crimson is always read from the repository root.
            # A release archive is only the package payload and must not
            # define, add, or override dependencies.
            #
            # download_repository_manifest() reads the .crimson at the
            # repository's default branch/root. This is intentionally done
            # even when an explicit release version was requested.
            repository_manifest = self.download_repository_manifest(repo)

            # The release tag is authoritative for the version being
            # installed. The repository-root manifest supplies metadata and
            # dependencies, but its version is not compared to the tag.
            declared_version = self.package_version(repository_manifest)

            friendly_name = str(
                repository_manifest["package"]["friendly-name"]
            ).strip()
            if not friendly_name:
                raise CrimsonError(
                    f"{MANIFEST_NAME}: package.friendly-name cannot be empty."
                )

            self.install_dependencies(
                repository_manifest.get("dependencies", {}),
                dependency_stack=(*dependency_stack, package_name),
            )

            source_root = self.find_source_root(extracted)

            target = self.installed_package_dir(package_name)
            staging = self.packages_dir / (
                f".{package_name}.installing-{os.getpid()}"
            )

            if staging.exists():
                shutil.rmtree(staging)

            shutil.copytree(source_root, staging)

            if target.exists():
                shutil.rmtree(target)

            staging.rename(target)

            print(f"Installed {package_name} {release_version} -> {target}")
        finally:
            shutil.rmtree(temp_parent, ignore_errors=True)

    def download_repository_manifest(
        self,
        repo: dict[str, Any],
    ) -> dict[str, Any]:
        owner = repo.get("owner", {}).get("login")
        name = repo.get("name")

        if not owner or not name:
            full_name = repo.get("full_name")
            if not full_name or "/" not in full_name:
                raise CrimsonError("GitHub repository information is incomplete.")
            owner, name = full_name.split("/", 1)

        # Read the repository's default branch through the Contents API.
        # Read the root .crimson file directly from the repository's
        # default branch. Using the raw URL avoids treating .crimson as a
        # directory and also works reliably with hidden dot-files.
        repo_data = self.github_get(f"/repos/{owner}/{name}")
        branch = repo_data.get("default_branch", "main")

        raw_url = (
            f"https://raw.githubusercontent.com/"
            f"{owner}/{name}/{branch}/{MANIFEST_NAME}"
        )

        try:
            response = self.session.get(
                raw_url,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise CrimsonError(
                f"Could not download {MANIFEST_NAME}: {exc}"
            ) from exc

        if response.status_code == 404:
            raise CrimsonError(
                f"{MANIFEST_NAME} was not found at the repository root "
                f"of {owner}/{name} on branch '{branch}'."
            )

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CrimsonError(
                f"Could not download {MANIFEST_NAME}: {exc}"
            ) from exc

        temp_parent = Path(tempfile.mkdtemp(prefix="crimson-manifest-"))
        try:
            path = temp_parent / MANIFEST_NAME
            path.write_text(response.text, encoding="utf-8")
            return self.read_manifest(temp_parent)
        finally:
            shutil.rmtree(temp_parent, ignore_errors=True)

    def install_dependencies(
        self,
        dependencies: dict[str, Any],
        *,
        dependency_stack: tuple[str, ...],
    ) -> None:
        for dependency, raw_constraint in dependencies.items():
            dependency = normalize_package_name(str(dependency))
            specifier = self.dependency_specifier(str(raw_constraint))

            installed = self.installed_version(dependency)

            if installed is not None and installed in specifier:
                print(
                    f"Dependency {dependency} {installed} "
                    f"satisfies {raw_constraint}."
                )
                continue

            if installed is not None:
                print(
                    f"Dependency {dependency} {installed} does not satisfy "
                    f"{raw_constraint}; installing a compatible version."
                )
            else:
                print(
                    f"Dependency {dependency} is not installed; "
                    f"installing a compatible version."
                )

            repo = self.select_repository(dependency)

            # Find the newest stable release satisfying the constraint.
            release = self.find_release_satisfying(repo, specifier)
            version = str(release["tag_name"]).lstrip("v")

            self.install(
                dependency,
                version,
                dependency_stack=dependency_stack,
            )

    def find_release_satisfying(
        self,
        repo: dict[str, Any],
        specifier: SpecifierSet,
    ) -> dict[str, Any]:
        owner = repo.get("owner", {}).get("login")
        name = repo.get("name")

        if not owner or not name:
            full_name = repo.get("full_name")
            if not full_name or "/" not in full_name:
                raise CrimsonError("GitHub repository information is incomplete.")
            owner, name = full_name.split("/", 1)

        releases = self.github_get(
            f"/repos/{owner}/{name}/releases",
            per_page=100,
        )

        candidates: list[tuple[Version, dict[str, Any]]] = []

        for release in releases:
            if release.get("draft") or release.get("prerelease"):
                continue

            tag = str(release.get("tag_name", "")).lstrip("v")
            try:
                version = Version(tag)
            except InvalidVersion:
                continue

            if version in specifier:
                candidates.append((version, release))

        if not candidates:
            raise CrimsonError(
                f"No release of {owner}/{name} satisfies '{specifier}'."
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def update(self, package_name: str) -> None:
        package_name = normalize_package_name(package_name)
        installed = self.installed_version(package_name)

        if installed is None:
            raise CrimsonError(
                f"Package '{package_name}' is not installed in {self.packages_dir}."
            )

        print(f"{package_name} {installed} is installed.")

        repo = self.select_repository(package_name, interactive=False)
        latest_release = self.get_latest_release(repo)
        latest = Version(str(latest_release["tag_name"]).lstrip("v"))

        if latest == installed:
            print(f"{package_name} is already up to date ({installed}).")
            return

        print(f"Latest release: {latest}")
        self.install(package_name, str(latest))

    def remove(self, package_name: str) -> None:
        package_name = normalize_package_name(package_name)
        target = self.installed_package_dir(package_name)

        if not target.is_dir():
            raise CrimsonError(
                f"Package '{package_name}' is not installed."
            )

        shutil.rmtree(target)
        print(f"Removed {package_name}.")

    def list_installed(self) -> None:
        entries = sorted(
            path
            for path in self.packages_dir.iterdir()
            if path.is_dir() and not path.name.startswith(".")
        )

        if not entries:
            print("No packages installed.")
            return

        print(f"Packages in {self.packages_dir}:")
        for path in entries:
            version = self.installed_version(path.name)
            version_text = str(version) if version else "unknown"
            print(f"  {path.name} {version_text}")

    def search(self, package_name: str) -> None:
        repos = self.search_repositories(package_name)

        if not repos:
            print(f"No repositories found for '{package_name}'.")
            return

        for repo in repos:
            print(repo.get("full_name", repo.get("name", "?")))
            description = repo.get("description")
            if description:
                print(f"  {description}")
            print(f"  {repo.get('html_url', '')}")

    def find(self, package_name: str, *, path_only: bool = False) -> None:
        """Find a local package directory and optionally print its path.

        Crimson looks for a directory named after the requested package in
        the current working directory, in Crimson's packages directory, and
        alongside the Crimson executable/script. The package directory must
        contain a JBS project file at its root.
        """
        package_name = normalize_package_name(package_name)

        candidates = [
            Path.cwd() / package_name,
            self.packages_dir / package_name,
            self.root_dir / package_name,
        ]

        package_dir: Path | None = None
        for candidate in candidates:
            if not candidate.is_dir():
                continue

            preferred = candidate / f"{package_name}.jbs"
            generic = candidate / ".jbs"

            if preferred.is_file() or generic.is_file():
                package_dir = candidate
                break

            jbs_files = sorted(candidate.glob("*.jbs"))
            if len(jbs_files) == 1:
                package_dir = candidate
                break

        if package_dir is None:
            searched = ", ".join(str(path) for path in candidates)
            raise CrimsonError(
                f"Could not find local package '{package_name}' containing a root JBS file. "
                f"Searched: {searched}"
            )

        jbs_files = []
        preferred = package_dir / f"{package_name}.jbs"
        generic = package_dir / ".jbs"

        if preferred.is_file():
            jbs_files.append(preferred)
        if generic.is_file() and generic not in jbs_files:
            jbs_files.append(generic)
        if not jbs_files:
            jbs_files = sorted(package_dir.glob("*.jbs"))

        if not jbs_files:
            raise CrimsonError(
                f"Package '{package_name}' was found at {package_dir}, but no root JBS file exists."
            )

        jbs_file = jbs_files[0]

        if path_only:
            print(package_dir.resolve())
            return

        print(f"Package : {package_name}")
        print(f"Path    : {package_dir.resolve()}")
        print(f"JBS     : {jbs_file.resolve()}")
        print()
        print(jbs_file.read_text(encoding="utf-8"))

    def info(self, package_name: str) -> None:
        package_name = normalize_package_name(package_name)
        repo = self.select_repository(package_name, interactive=False)

        manifest = self.download_repository_manifest(repo)
        package = manifest["package"]

        print(f"Repository : {repo.get('full_name', '?')}")
        print(f"Name       : {package.get('friendly-name')}")
        print(f"Version    : {package.get('version')}")

        dependencies = manifest.get("dependencies", {})
        if dependencies:
            print("Dependencies:")
            for dependency, constraint in dependencies.items():
                print(f"  {dependency} {constraint}")
        else:
            print("Dependencies: none")


def normalize_package_name(name: str) -> str:
    name = name.strip()

    if name.startswith(REPO_PREFIX):
        name = name[len(REPO_PREFIX):]

    # Package names are intentionally restricted because they become
    # directory names under packages/.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise CrimsonError(
            f"Invalid package name '{name}'. "
            "Use letters, numbers, '.', '_' and '-'."
        )

    return name.lower()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crimson",
        description="Standalone GitHub package manager for Crimson packages.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"Crimson {CRIMSON_VERSION}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    install = subparsers.add_parser(
        "install",
        help="Install a package and its dependencies.",
    )
    install.add_argument("package")
    install.add_argument(
        "-v",
        "--version",
        dest="package_version",
        help="Override the version from .crimson.",
    )

    update = subparsers.add_parser(
        "update",
        help="Update an installed package to its latest stable release.",
    )
    update.add_argument("package")

    remove = subparsers.add_parser(
        "remove",
        aliases=["uninstall"],
        help="Remove an installed package.",
    )
    remove.add_argument("package")

    subparsers.add_parser(
        "list",
        aliases=["ls"],
        help="List installed packages.",
    )

    search = subparsers.add_parser(
        "search",
        help="Search GitHub for jaguar-<package> repositories.",
    )
    search.add_argument("package")

    info = subparsers.add_parser(
        "info",
        help="Show package metadata from GitHub.",
    )
    info.add_argument("package")

    find = subparsers.add_parser(
        "find",
        help="Find a local package and its root JBS file.",
    )
    find.add_argument("package")
    find.add_argument(
        "--path",
        action="store_true",
        help="Print only the package directory.",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    crimson = Crimson()

    try:
        if args.command == "install":
            crimson.install(
                args.package,
                args.package_version,
            )

        elif args.command == "update":
            crimson.update(args.package)

        elif args.command in {"remove", "uninstall"}:
            crimson.remove(args.package)

        elif args.command in {"list", "ls"}:
            crimson.list_installed()

        elif args.command == "search":
            crimson.search(args.package)

        elif args.command == "info":
            crimson.info(args.package)

        elif args.command == "find":
            crimson.find(args.package, path_only=args.path)

        else:
            parser.error(f"Unknown command: {args.command}")

        return 0

    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130

    except CrimsonError as exc:
        print(f"Crimson error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
