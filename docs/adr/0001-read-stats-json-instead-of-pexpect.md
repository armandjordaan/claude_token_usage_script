# Read stats-cache.json directly instead of scraping the /usage TUI

Despite the repo name (`pexpect_claude`), we do **not** drive Claude Code with pexpect. The `/usage` → Stats tab is rendered from `~/.claude/stats-cache.json`; reading it directly yields exact integers (the TUI only shows a rounded `"13.6m"`), needs no terminal emulation, and doesn't break when the TUI layout changes between Claude Code versions. The pexpect/TUI-scraping path was prototyped and rejected as brittle — the screen positions text by cursor-move escape codes, so naive ANSI stripping mashes words together and would require a full terminal emulator (e.g. `pyte`) to reconstruct.

**Trade-off:** the file is a cache (`lastComputedDate`), so the current month can lag until `/usage` is next opened in Claude Code.
