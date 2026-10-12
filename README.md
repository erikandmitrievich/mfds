# mfds

Personal study repository for the Mathematical Foundations of Data Science BSc, University of Vienna. Emacs org-mode throughout, with Python and Julia for tooling and coursework.

The notes are written for one reader and are not designed as a study resource. The structure around them may be of interest.

## Design

- **The layout is a spec, not a habit.** [`STRUCTURE.org`](STRUCTURE.org) states the directory contract; [`validate_structure.py`](00_global/scripts/validate_structure.py) is its executable form and runs as a pre-commit hook.
- **So is the history.** [`.gitmessage`](.gitmessage) states the commit convention and is git's commit template; [`validate_commits.py`](00_global/scripts/validate_commits.py) enforces it in the commit-msg and pre-push hooks. Type and scope follow from the paths a commit touches, so the hooks prefill them.
- **Sources and products are never conflated.** `rm -rf 01_extracted/` must be obviously safe. Anything whose deletion loses information belongs in `00_resources/`.
- **LLMs handle volume, and their text is marked.** Extraction from high-volume source material, answers to my questions on it, and synthesis of exam plans across a large problem set pile are delegated; solutions and proofs are not. Code stamps each model-written item and answer with an `LLM` property naming the model ([`STRUCTURE.org`](STRUCTURE.org), Scope); older notes predate the stamp. Help on a problem set stays in a local chat beside it. Prompts live in [`00_global/prompts/`](00_global/prompts/).

## Use

```sh
just git-setup # once per clone: hooks and commit template
just           # validation, transcription, aggregation, stats
just validate
```

## License

Code: MIT. Prose: CC BY-NC-SA 4.0. See [`LICENSE`](LICENSE). 
