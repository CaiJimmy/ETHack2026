# Working rules for this repo

## Authorship
Commits are authored by the repo owner alone. Do not add `Co-Authored-By`, `Claude-Session`, or any
other attribution trailer. This is a judged submission; the git history has to reflect the team.

## Writing
Every piece of text here gets an anti-AI-writing pass before it lands: code comments, docs, slide
copy, website copy, commit messages. Run the `avoid-ai-writing` skill in edit mode over a file before
committing it. Write plainly the first time rather than generating prose and cleaning it afterwards.

## Environment
NixOS. There is no system pip or conda. Get a shell with:

```bash
nix develop            # python312 + uv + duckdb + node + ffmpeg
uv venv && uv pip install -r requirements.txt
```

Python packages come from prebuilt wheels via `uv`, never from nixpkgs source builds. The devshell
puts the C runtime libs those wheels dlopen on `LD_LIBRARY_PATH`.

## Data
`data/raw/` and `data/interim/` are gitignored. Anything under them must be reproducible by a script
in `src/`. Commit the small derived artefacts the site and slides read, not the bulk inputs.

Every field in a published table carries its provenance: source, retrieval date, licence. If a number
cannot be traced to a fetch script, it does not ship.

## Deployment
The site is static. It is served by Caddy on a 2 vCPU / 4 GB / 20 GB VM that already swaps, so the
browser does the work and the server only hands out files. Build locally, rsync the output, never
compute per request.
