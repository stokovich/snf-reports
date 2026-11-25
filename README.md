# SNF reports

Reports for the SNF group in Prosperous Universe, built from FIO.

- `fio_report.py` - the daily in/out of every member of the group (production lines and workforce) per material and per base: surplus and deficit.
- `tools/fio_dump.py` - downloads the raw FIO data of the group, to study its structure.

The FIO API key comes from the environment (`FIO_KEY`), never from the code.

## The hourly rebuild

GitHub runs the `schedule` of `.github/workflows/build.yml` late or not at all (25.11.2026: one run in five hours),
so the hourly rebuild is started from outside: cron-job.org, job "SNF reports - hourly build", every hour at :17
(Europe/Sofia), `POST https://api.github.com/repos/stokovich/snf-reports/actions/workflows/build.yml/dispatches`
with body `{"ref":"main"}`. The token is a fine-grained one, `snf-reports-cron`: this repository only,
Actions read and write, no expiry. The `schedule` in the workflow stays as a backup.
GitHub retires API version `2022-11-28` (the `X-GitHub-Api-Version` header of the job) on 10.03.2028 - change it before then.
