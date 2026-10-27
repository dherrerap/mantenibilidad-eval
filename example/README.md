# Example

`example-report.md` is the real output of `python cli.py evaluate --model claude-sonnet-5-5` on three e-commerce
applications (N1, N2 and N3) generated with the specifications in `specs/`, on 2026-10-13.

It is useful for seeing the report format, not as a result to cite:

- The ranges are still open (the manual review had not been completed).
- The generator model (`claude-sonnet-5-5`) was assumed to be the same as the session's; it was not verified.
- A single run per level and the applications were not run against MongoDB. See [../docs/limitations.md](../docs/limitations.md).
- The report was produced before the framework's identifiers were translated to English; its content was translated by hand.
