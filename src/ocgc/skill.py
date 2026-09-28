"""OpenCode Skill definition and installer."""

from pathlib import Path

from rich.console import Console

console = Console()

SKILL_NAME = "ocgc"
SKILL_SOURCE = Path(__file__).resolve().parent / "SKILL.md"


def get_skill_content() -> str:
    """Read the embedded SKILL.md template."""
    if SKILL_SOURCE.exists():
        return SKILL_SOURCE.read_text(encoding="utf-8")
    # Fallback to repository skills path if running in editable checkout
    repo_skill = Path(__file__).resolve().parents[2] / "skills" / "ocgc" / "SKILL.md"
    if repo_skill.exists():
        return repo_skill.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"SKILL.md not found. Searched locations:\n  - {SKILL_SOURCE}\n  - {repo_skill}"
    )


def get_default_skill_dirs(workspace: bool = False) -> list[Path]:
    """Get target OpenCode skill directories."""
    if workspace:
        return [Path(".opencode") / "skills" / SKILL_NAME]

    home = Path.home()
    dirs = [home / ".agents" / "skills" / SKILL_NAME]
    opencode_home = home / ".opencode"
    if opencode_home.exists():
        dirs.append(opencode_home / "skills" / SKILL_NAME)
    return dirs


def install_skill(
    dest: Path | None = None,
    workspace: bool = False,
) -> list[Path]:
    """Install the ocgc OpenCode skill to standard directories or custom destination."""
    content = get_skill_content()

    if dest is not None:
        if dest.name.endswith(".md"):
            target_file = dest
        elif dest.name == SKILL_NAME:
            target_file = dest / "SKILL.md"
        else:
            target_file = dest / SKILL_NAME / "SKILL.md"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(content, encoding="utf-8")
        return [target_file]

    target_dirs = get_default_skill_dirs(workspace=workspace)
    installed_files: list[Path] = []
    for d in target_dirs:
        d.mkdir(parents=True, exist_ok=True)
        target_file = d / "SKILL.md"
        target_file.write_text(content, encoding="utf-8")
        installed_files.append(target_file)

    return installed_files


def run_install_skill(
    dest: str | None = None,
    workspace: bool = False,
) -> None:
    """CLI handler for install-skill."""
    target_path = Path(dest).expanduser() if dest else None
    installed_files = install_skill(target_path, workspace=workspace)

    console.print("[bold green]✓[/] Successfully installed OpenCode skill to:")
    for f in installed_files:
        console.print(f"  • [cyan]{f}[/cyan]")

    console.print("\n[bold]How to use in OpenCode:[/bold]")
    console.print("  Simply ask OpenCode in your chat:")
    console.print('  [dim]• "Check my OpenCode storage status and purge sessions older than 30d"[/dim]')
    console.print('  [dim]• "Strip reasoning tokens from my OpenCode database"[/dim]')
    console.print('  [dim]• "@ocgc analyze top 10 largest sessions"[/dim]')

