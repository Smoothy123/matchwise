# Data

Everything in this folder except this README is gitignored.

## Dataset

**LinkedIn Job Postings (2023 - 2024)**, published on Kaggle by user `arshkon`:
https://www.kaggle.com/datasets/arshkon/linkedin-job-postings
License: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Matchwise does not
redistribute the data; it reads a local copy you download yourself.

## Download (manual, needs a free Kaggle account)

1. Open the dataset page above and click **Download** (about 550 MB once unzipped).
2. Unzip it so this layout exists:

```
data/raw/postings.csv
data/raw/jobs/job_skills.csv
data/raw/jobs/job_industries.csv
data/raw/mappings/skills.csv
data/raw/mappings/industries.csv
data/raw/companies/companies.csv
```

3. Load a sample: `docker compose run --rm app python -m matchwise.ingest`
