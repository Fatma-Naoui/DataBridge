# Quality report

## Records ingested per source

| source | records |
|---|---|
| sql | 402 |
| files | 18 |
| email | 213 |


## Dropped and why

| source | reason | count |
|---|---|---|
| files | pdf_unreadable:PdfStreamError | 1 |
| files | word_lock_file | 1 |
| files | near_duplicate | 1 |
| email | exact_duplicate | 40 |
| email | near_duplicate | 10 |
| email | empty_after_cleaning | 6 |
| email | unpaired_thread | 2 |


## Duplicates removed

| type | count |
|---|---|
| exact | 40 |
| near | 11 |


## PII replaced

| type | count |
|---|---|
| ADDRESS | 52 |
| EMAIL | 95 |
| IBAN | 41 |
| NATIONAL_ID | 30 |
| PERSON | 258 |
| PHONE | 71 |


## Language distribution

| language | examples | share |
|---|---|---|
| nl | 68 | 58% |
| fr | 41 | 35% |
| en | 8 | 7% |


## Domain distribution

| domain | examples | share |
|---|---|---|
| policies | 40 | 34% |
| claims | 32 | 27% |
| general | 31 | 26% |
| billing | 14 | 12% |


## Train / eval split

| file | examples | share |
|---|---|---|
| train | 99 | 85% |
| eval | 18 | 15% |


## Validation: passed

0 error(s), 0 warning(s).

