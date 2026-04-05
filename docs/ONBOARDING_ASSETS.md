# Onboarding assets (documentation only)

The Web UI and first-run wizard stay **clean-room**: no bundled third-party art packs. Operators who want extra visuals or sounds can fetch **licensed** assets themselves.

**Ideas (verify license before use)**

- **SVG / icons:** CC0 sets on OpenClipart-style archives, Phosphor / Heroicons (check each license).
- **Pixel style:** Liberated Pixel Cup (LPC) guidelines and community bases (per-asset license).
- **UI sounds:** freesound.org (filter by license), or record your own.
- **Fonts:** Google Fonts / OFL families already common on the web; self-host if you ship offline.

**Policy**

- Prefer **local paths** in `runtime_config.json` for any optional binary paths.
- Do not commit large binaries without an explicit licensing decision in the repo.
