# mfds

Personal study repository for the Mathematical Foundations of Data Science BSc, University of Vienna. Emacs org-mode throughout, with Python and Julia for tooling and coursework.

The notes are written for one reader and are not designed as a study resource. The structure around them may be of interest.

## Design

- **The layout is a spec, not a habit.** [`STRUCTURE.org`](STRUCTURE.org) states the directory contract; [`validate_structure.py`](00_global/scripts/validate_structure.py) is its executable form and runs as a pre-commit hook.
- **Sources and products are never conflated.** `rm -rf 01_extracted/` must be obviously safe. Anything whose deletion loses information belongs in `00_resources/`.
- **LLMs handle volume; they never produce mathematics.** Extraction from high-volume source material and synthesis of exam plans across a large problem set pile are delegated; solutions and proofs are not. Prompts live in [`00_global/prompts/`](00_global/prompts/).

## Use

```sh
just           # validation, transcription, aggregation, stats
just validate
```

## License

Code: MIT. Prose: CC BY-NC-SA 4.0. See [`LICENSE`](LICENSE). 
