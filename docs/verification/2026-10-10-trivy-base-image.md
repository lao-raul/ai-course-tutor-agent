# CI Trivy image-scan repair — 2026-10-10

The [TASK-20 pull-request CI run](https://github.com/lao-raul/ai-course-tutor-agent/actions/runs/38018240900/job/114113445470)
failed at `Scan Agent image`; source scanning and the other prerequisite jobs passed.
The image report showed Debian 12.12 packages with available security fixes, including
`perl-base` (CVE-2026-13221) and OpenSSL. The Python Dockerfiles still used the
older `python:3.12.11-slim-bookworm` base. Subsequent image scans were skipped by CI.

All four Python Dockerfiles now use the same multi-platform digest of the official
Python 3.12.15 slim Bookworm image, served through the Docker Official Images mirror
at `public.ecr.aws/docker/library/python`. The digest is
`sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258`.
Keeping a digest rather than a floating tag makes the build reproducible.

Local verification:

| Check | Result |
|---|---|
| `docker buildx bake --check` | 5 targets valid |
| CI-style `docker buildx bake --load` | 5 images built |
| Trivy 0.69.3, `HIGH,CRITICAL`, `--ignore-unfixed`, `--exit-code 1` | 0 fixable findings in Agent, Practice, ingestion worker, Web and fake-LLM images |
| Python image entrypoint imports | Agent, Practice and ingestion worker passed; fake-LLM uses Python 3.12.15 |

This verifies the local build and scan, not the hosted GitHub Actions result. The
updated branch must be pushed and its CI rerun before declaring the remote gate green.
