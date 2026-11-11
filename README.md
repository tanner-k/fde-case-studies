# Forward-deployed case studies

Each case study takes a real company's customer problem and builds a working,
tested model of the decision from public data. The aim is to show how fast a
defensible answer can be reached, and to say plainly what the evidence does
and does not support.

| Case study | Question | Headline |
|---|---|---|
| [Deere Farm ROI Copilot](case-studies/john-deere-roi-copilot/README.md) | Which customer should own a precision-ag machine: the farm or a custom operator? | A 2,400-acre Iowa farm should not own a $650,000 sprayer; the general rule held for 5 of 8 machines at best |

Independent work. Not affiliated with or endorsed by any company named here.

## Run it

```bash
uv sync --all-packages --all-extras --all-groups
```

```bash
uv run pytest
```

Each case study is its own package under `case-studies/`, with its own
dependencies, tests and write-up.
