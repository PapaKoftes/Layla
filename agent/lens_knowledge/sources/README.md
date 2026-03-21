# Lens knowledge sources

Curated reference material for lens refresh. Place one `.md` file per lens:

- carpenter.md
- assembly_lens.md
- devops.md
- geometry.md
- product.md
- strategist.md

`POST /refresh_lens_knowledge` (or the scheduled job when `enable_lens_refresh` and `lens_refresh_interval_days` are set) reads these files, truncates each to 800 words, and overwrites the corresponding file in `lens_knowledge/`. No external crawling.
