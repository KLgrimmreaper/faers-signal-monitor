# faers-signal-monitor

counts drug and reaction combos in the FDA adverse event reports and ranks the pairs that
look worth a human reviewing.

the counting is the easy part. the interesting bit is working out which pairs get
reported more often than you'd expect by chance, then checking that ranking against
published reference signals.

## where it is

milestones 1 to 5 are done. `run.py` counts reports from the openFDA api, `ingest.py`
loads a date range into postgres, `signals.py` does PRR and ROR, `report.py` writes the
ranking to markdown, and `evaluate.py` scores it against the EU-ADR reference set.

a full day of reports, 2024-01-01, loaded as 1508 reports and 26032 rows, and running
the same ingest again added 0 rows.

the numbers the report and the evaluation print are not usable yet. see the statistics
and evaluation sections.

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

`report.py` ranks them into markdown. that file isn't committed because the numbers move
with the data.

```
python report.py
python report.py --top 100 --min-reports 5 --out report.md
```

the report starts with what it was computed from, the report count and the date range.
right now it says the table holds a single day.

**the numbers from one day are not usable as signals.** 1508 reports and 1401 distinct
reactions means a four report pair can hit a PRR in the hundreds. the top value right
now, anakinra with therapy partial responder, comes from four reports. this needs the
whole population, which is milestone 6.

most of the top of that table is confounding anyway. a reaction that's also the drug's
indication ranks high because the report is describing the condition being treated, not
a side effect. vedolizumab with colitis ulcerative and dupixent with dermatitis atopic
are both that, same as the device reactions against drugs delivered by those devices.
nothing here filters that out, but it's worth knowing when reading the table.

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
on the current single day:

```
reference pairs: 93
  43 positive, 50 negative
coverage: 47 of 93 pairs scored, 46 missing
AUC: 0.571
```

that AUC is barely above chance and 46 of the 93 pairs can't be scored at all. both are
what one day gives you, a drug withdrawn in 2004 isn't in a day of 2024, so rofecoxib
with myocardial infarction is one of the 46. these are the numbers the harness produces,
not the numbers the method earns, and they shouldn't be quoted as a result until the
bulk files are in.

the reference outcomes are named as OMOP cohorts rather than MedDRA terms, so
`evaluate.py` maps each of the 10 to the reaction terms that stand for it, `HOI Upper GI
#3` to gastrointestinal haemorrhage, melaena and gastric ulcer for example. a pair takes
its highest matching term. cardiac valve fibrosis and stevens-johnson syndrome matched
nothing in the loaded day.

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

milestone 6 loads the bulk quarterly FAERS files, which is what the statistics and the
evaluation need before they mean anything.
