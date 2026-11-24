# SNF reports

Reports for the SNF group in Prosperous Universe, built from FIO.

- `fio_report.py` - the daily in/out of every member of the group (production lines and workforce) per material and per base: surplus and deficit.
- `tools/fio_dump.py` - downloads the raw FIO data of the group, to study its structure.

The FIO API key comes from the environment (`FIO_KEY`), never from the code.
