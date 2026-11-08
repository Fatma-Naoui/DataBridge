# Quality report

## Records ingested per source

| source | records |
|---|---|
| sql | 402 |
| files | 21 |
| email | 213 |


## Dropped and why

| source | reason | count |
|---|---|---|
| files | pdf_unreadable:PdfStreamError | 1 |
| files | word_lock_file | 1 |
| files | near_duplicate | 1 |
| email | exact_duplicate | 42 |
| email | near_duplicate | 7 |
| email | empty_after_cleaning | 6 |
| email | unpaired_thread | 2 |


## Duplicates removed

| type | count |
|---|---|
| exact | 42 |
| near | 8 |


## PII replaced

| type | count |
|---|---|
| ADDRESS | 56 |
| EMAIL | 99 |
| IBAN | 42 |
| NATIONAL_ID | 15 |
| ORGANIZATION | 140 |
| PERSON | 264 |
| PHONE | 77 |


## Language distribution

| language | examples | share |
|---|---|---|
| nl | 68 | 58% |
| fr | 42 | 36% |
| en | 8 | 7% |


## Domain distribution

| domain | examples | share |
|---|---|---|
| general | 39 | 33% |
| policies | 33 | 28% |
| claims | 32 | 27% |
| billing | 14 | 12% |


## Train / eval split

| file | examples | share |
|---|---|---|
| train | 100 | 85% |
| eval | 18 | 15% |


## Validation: passed

0 error(s), 0 warning(s).

