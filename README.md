# faers-signal-monitor

counts drug and reaction combos in the FDA adverse event reports and ranks the pairs that
look worth a human reviewing.

the counting is the easy part. the interesting bit is working out which pairs get
reported more often than you'd expect by chance, then checking that ranking against
published reference signals.

## where it is

milestones 1 to 6 are done. `run.py` counts reports from the openFDA api, `ingest.py`
loads a date range from the api, `bulk_ingest.py` loads the quarterly extract files,
`signals.py` does PRR and ROR, `report.py` writes the ranking to markdown, and
`evaluate.py` scores it against the EU-ADR reference set.

the full 2024 Q1 extract, 406,184 reports, loaded as 10,308,028 rows in 218 seconds, for
522,047 pairs with at least three reports. loading the same quarter twice adds nothing,
because the primary key rejects rows that are already there.

the marginals are materialized, which takes the pair query from 1699 ms to 8.9 ms,
measured with EXPLAIN ANALYZE.

the evaluation now scores 91 of the 93 reference pairs, at an AUC of 0.687. both numbers
were 47 of 93 and 0.571 when only a day of api data was loaded, which is the point of
having the bulk files at all.

## what this is not

adverse event reports are voluntary and biased. a widely prescribed or publicised drug
gets more reports regardless of actual risk. a high count is not evidence that a drug
causes a reaction, and nothing here finds a new safety signal. a signal means worth a
human looking at. none of this is medical advice.

## running it

python 3.10 or newer.

```
python -m pip install -r requirements.txt
```

one count, no database needed:

```
python run.py IBUPROFEN NAUSEA
python run.py IBUPROFEN
```

```
reports with IBUPROFEN and NAUSEA:
  14,519
```

run from the repo root, `run.py` imports `fetch.py` from the same folder.

## loading reports into postgres

`ingest.py` makes its own tables, so nothing needs loading by hand. a single day is the
useful unit since it's small enough to load whole.

```
docker compose up -d
python ingest.py --since 20240101 --until 20240101
```

```
1,508 reports for 20240101 to 20240101
26,032 event rows
0 rows in events before, 26,032 after, 26,032 new
```

running it again ends with `26,032 after, 0 new`. the primary key on `events` rejects
rows that are already there, so a repeat insert does nothing and there's no separate
bookkeeping of what's been loaded.

`--dry-run` fetches and builds the rows without writing.

connection settings come from the standard `PG*` env vars and default to the
`docker-compose.yml` service. `OPENFDA_API_KEY` is optional and raises the rate limit.
without a key openFDA won't return more than 100 records per request.

### how much one run covers

`--limit` caps how many reports get fetched. if the range holds more, `ingest.py` says
so:

```
300 reports for 20240101 to 20240107
warning: 21,468 reports exist in this range but only 300 were ingested. openFDA returns
records in a fixed order, so this is the start of the range, not a sample of it.
```

openFDA pages by offset and there's no way to ask for a random sample, so a capped run
returns the first records it holds. with `--limit 300` over a week all 300 came from
2024-01-01 and the other six days had none. counts off a truncated load are skewed by
whatever that day contained, so either narrow the dates or raise the limit.

a year of reports is way past what paging this api can reach, it refuses `skip` above
25000. milestone 6 reads the bulk quarterly files instead.

the table holds one day of 2024, so a drug withdrawn before then has no rows. rofecoxib
is one of those.

## loading the quarterly files

the api is fine for a day and useless for a population. `bulk_ingest.py` reads the
quarterly ASCII extract the fda publishes, which is a zip of dollar delimited files with
a header row.

```
python bulk_ingest.py --quarter 2024q1
python bulk_ingest.py --quarter 2024q1 --limit 20000
python bulk_ingest.py --quarter 2024q1 --replace
```

it downloads the zip to `data/` if it is not there, streams DEMO, DRUG and REAC into
staging tables through COPY, and lets postgres do the join, because the join is tens of
millions of rows and would not fit in python.

`--replace` clears the events table first, which is what you want when switching between
the api and the bulk files: they use different report ids, so the two do not merge
meaningfully.

the detail files are filtered against the staged report ids as they stream. doing it
afterwards with a `DELETE ... WHERE primaryid NOT IN (...)` against a few hundred
thousand ids is a nested scan that will not finish, which is worth knowing before
writing it the obvious way.

## how the data is treated

each report becomes one row per drug and reaction combo. openFDA says a report lists its
drugs and its reactions but not which drug goes with which reaction, so every combo in a
report counts as co-reported. the statistics are built on that cross product, which is
an assumption and not something the data states.

names are stored upper case because the same term comes back with inconsistent casing,
and the original is kept in `drug_raw` so that can be checked. a report often lists the
same drug twice, once per indication, and those collapse into one row, which is right
because PRR counts reports rather than mentions.

## the statistics

each pair gets four counts:

```
a  reports with the drug and the reaction
b  reports with the drug but not the reaction
c  reports with the reaction but not the drug
d  reports with neither

prr = (a / (a + b)) / (c / (c + d))
ror = (a * d) / (b * c)
```

if b, c or d is zero the ratio has no finite value, so it returns `None` instead of
infinity. pairs under three reports are skipped, since one or two say nothing.

```
python signals.py
python signals.py --min-reports 5
```

the drug and reaction marginals are materialized views, refreshed at the end of every
load. computing them per row instead turns a pair lookup into a full aggregate over ten
million rows: the same query goes from 8.9 ms to 1699 ms, which is the difference
between a lookup and 17 bitmap scans reading 252,254 buffers.

`report.py` ranks them into markdown. that file isn't committed because the numbers move
with the data.

```
python report.py
python report.py --top 100 --min-reports 5 --out report.md
```

the report starts with what it was computed from, the report count and the date range.

**ranking on raw PRR puts junk at the top.** the highest value in the quarter is
ajmaline with gammopathy at 355,404, which is arithmetically correct: 7 of the 8 reports
mentioning ajmaline also mention gammopathy. it is useless as a signal because a is 7,
and PRR is unstable when the counts are small. of 522,047 pairs, the ones with the
largest ratios are the ones with the smallest numerators. a seriousness filter or a
higher floor would help and neither is here yet.

most of the rest of the top is confounding. a reaction that's also the drug's indication
ranks high because the report is describing the condition being treated, not a side
effect. vedolizumab with colitis ulcerative and dupixent with dermatitis atopic are both
that, same as the device reactions against drugs delivered by those devices. nothing here
filters that out, but it's worth knowing when reading the table.

## evaluation against EU-ADR

the reference set is 43 positive controls, pairs where the drug is believed to cause the
outcome, and 50 negative controls where it isn't, across 10 outcomes. it comes from the
OHDSI `MethodEvaluation` package, published from Coloma et al, Drug Safety 2013. there
were 44 positives originally, nimesulide got dropped because it isn't in RxNorm.

with positives and negatives this is a labelled problem, so four things get reported:
recall on the positives, specificity on the negatives, AUC sweeping the threshold, and
precision at K. a threshold is a convention, which is what the AUC is for.

```
python evaluate.py
```

the set is only published as an R data file, so `make_reference_set.py` converts it once
into `fixtures/euadr_reference_set.csv`, which is committed. the evaluation reads the csv
and needs neither R nor the network.

coverage prints before any metric. a pair the loaded data can't support counts as missing
rather than as a negative, because calling it a negative would flatter the specificity.
on the full 2024 Q1 quarter:

```
reference pairs: 93
  43 positive, 50 negative
coverage: 91 of 93 pairs scored, 2 missing
AUC: 0.687

threshold   recall   specificity   precision   hits   false alarms
     1.00     0.81          0.33        0.51     34             33
     2.00     0.79          0.39        0.52     33             30
     3.00     0.79          0.57        0.61     33             21
     5.00     0.57          0.76        0.67     24             12
```

42 of the 43 positives are scoreable and 0.687 is above chance, which is what the bulk
load was for. the two that are not are the outcomes with no matching reaction term, not
pairs the data refused.

the threshold table is the honest part. at a PRR of 1 the method catches 81 percent of
the known positives and also flags 33 of the 49 negatives, which is not a usable screen.
pushing the threshold to 5 fixes most of the false alarms but loses a third of the true
ones. that trade is the whole problem, and it is why the AUC is reported rather than a
single threshold.

the reference outcomes are named as OMOP cohorts rather than MedDRA terms, so
`evaluate.py` maps each of the 10 to the reaction terms that stand for it, `HOI Upper GI
#3` to gastrointestinal haemorrhage, melaena and gastric ulcer for example. a pair takes
its highest matching term.

one caveat that goes with any number here. EU-ADR was built for electronic health record
and claims databases, not a spontaneous reporting system. FAERS is voluntary, duplicated
across follow ups, and biased by how widely a drug is prescribed. a low score doesn't by
itself mean the method is poor, and using a reference standard built for spontaneous
reporting would need saying too.

## data source notes

- field names came from the live api, not from memory. the reaction field is
  `patient.reaction.reactionmeddrapt`, meddra has two d's.
- the api ids a report by `safetyreportid`. bulk FAERS files use `primaryid` for the same
  thing and the api returns no `primaryid` at all, so the column is `report_id`.
- openFDA returns 404 when a search matches nothing, which is treated as a count of zero.
  a misspelled drug and a genuinely rare reaction both come back as 0 and can't be told
  apart.
- a date range needs spaces around `TO`. the `+TO+` form in some of openFDA's own
  examples returns 500.
- requests retry on 429 and 5xx with backoff of 3, 6 then 12 seconds, four attempts. the
  rate limit resets per minute so a shorter retry is often too soon.
- an apostrophe in a meddra term arrives as a caret, so the table holds `STILL^S DISEASE`
  rather than `STILL'S DISEASE`. stored as received, and `report.py` swaps it back when
  writing the table. five terms in a day used a caret and none used a real apostrophe, so
  nothing is split across two spellings.

## next

milestone 7 is the failure handling: the `runs` table, halting on a partial ingest, and
`run.py --status` so a job that quietly stopped is visible.
