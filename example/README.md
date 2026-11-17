# Example (historical: v0.1.0-mern)

> **This example belongs to the MERN version of the framework (tag `v0.1.0-mern`), not to the current PERN one.** It was produced
> before the relational data model, the acceptance gate, ESLint/SonarJS, Knip, OSV, the ASCMM density and the weight sensitivity
> existed, so its data model point talks about Mongoose schemas and its report lacks most of the sections the current `report.md`
> has. Use it only to get an idea of the general shape of a report. Replace it with the `results/report.md` of the first PERN run.

`example-report.md` is the real output of `python cli.py evaluate --model claude-sonnet-5-5` on three e-commerce applications
(N1, N2 and N3) generated with the MERN specifications of that version, on 2026-10-13.

It was never a result to cite:

- The ranges are still open (the manual review had not been completed).
- The generator model (`claude-sonnet-5-5`) was assumed to be the same as the session's; it was not verified.
- A single run per level, and the applications were not run against MongoDB (there was no acceptance gate).
- The report was produced before the framework's identifiers were translated to English; its content was translated by hand.

See [../docs/limitations.md](../docs/limitations.md).
