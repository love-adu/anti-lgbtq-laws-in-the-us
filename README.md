# anti-lgbtq-laws-in-the-us

# anti-lgbtq bill text dataset

the full text of the state bills in the aclu's anti-lgbtq legislation tracker (2020 through 2026), plus the scripts.

--

the charts and database built from this are here: {{loveitzeladu.com/}}

this guide is split into four parts:

1. **what's in the repo/site**: the files
2. **how it was made**
3. **run it yourself**
4. **things to know**

## contents

- [what's in here](#whats-in-here)
- [where the data comes from](#where-the-data-comes-from)
- [how it was made](#how-it-was-made)
- [how to cite this](#how-to-cite-this)
- [credits and terms](#credits-and-terms)

---

# part 1: what's in here

## what's in here

| file | what it is |
|---|---|
| `{{folder with the aclu csvs}}` | the raw tracker csvs from the aclu (seperated by year) |
| `billtextdeclassed/text/` | the bill text files, one per bill version, named `billis_STATE_BILL_ID_version.txt`. also available as one zip in repo |
| `billtextdeclassed/billstofindcleaned.csv` | the cleaned bill list (no text) |
| `billtextdeclassed/resultsfromanalysisforantitranslegdata.csv` | what happened to every bill: found, not found, or no text, more relevant if you are using the scripts |
| `billtextfinderforantitranslegtext.py` | the script that cleans the csvs and downloads the text |
| `billsponsorfinderforantitranslegtext.py` | the script that finds who introduced each bill (optional, see below) |
| `billtextdeclassed/sponsorsfromanalysisforantitranslegdata.csv` | lists sponsors for each bill |
| `billtextdeclassed/introducersbybillforantitranslegdata.csv` | the results of 'billsponsorfinderforantitranslegtext'|

the file names look like this:

```
billis_WA_HB1233_222_introduced.txt
```

the key is: the state (`WA`), the bill (`HB1233`), the legiscan bill id (`222`), and which version it is (`introduced` or `latest`).

## where the data comes from

- **the bill list, issue categories, and statuses**: the aclu's legislation tracker, [mapping attacks on lgbtq rights in u.s. state legislatures](https://www.aclu.org/legislative-attacks-on-lgbtq-rights). i downloaded the csv for each tracker year, 2020 through 2026. (with the exception of 202 to 2022, all have the same 2023 file name in the repo fyi, sorry!!)
- **the bill text and sponsors**: [legiscan](https://legiscan.com), through its api.
---

# part 2: how it was made

code is linked on the site. Too lazy to repeat it here lol.

## how to cite this

if you use the dataset, the scripts, or the charts, and want to cite it, see below. github also puts a "cite this repository" button on the right side of the repo page, that comes from the `CITATION.cff` file.

**apa**

```
Adu, L. (2026). Anti-LGBTQ bill text dataset [Data set]. GitHub. https://github.com/love-adu/anti-lgbtq-laws-in-the-us
```

**mla**

```
Adu, Love. Anti-LGBTQ Bill Text Dataset. 2026. GitHub, https://github.com/love-adu/anti-lgbtq-laws-in-the-us.
```

**bibtex**

```
@misc{adu2026antilgbtq,
  author = {Adu, Love},
  title = {Anti-{LGBTQ} Bill Text Dataset},
  year = {2026},
  publisher = {GitHub},
  url = {https://github.com/love-adu/anti-lgbtq-laws-in-the-us}
}
```

please cite where the data came from too:

- the bill list, issue categories, and statuses: American Civil Liberties Union. (2026). *Mapping attacks on LGBTQ rights in U.S. state legislatures*. https://www.aclu.org/legislative-attacks-on-lgbtq-rights. 
- the bill text and sponsor records: LegiScan. *LegiScan API*. https://legiscan.com. accessed {{month and year you ran the download}}. check their terms for how they want to be credited, I'm not eentirely sure.

## credits and terms

- bill list and issue categories: the aclu's [legislation tracker](https://www.aclu.org/legislative-attacks-on-lgbtq-rights)
- bill text and sponsor records: [legiscan](https://legiscan.com), through its api
- this project isn't affiliated with the aclu or legiscan
- both of them have their own terms of use. check them before you reuse or redistribute anything from here
- questions or fixes: {{loveadu@berkeley.edu}}
