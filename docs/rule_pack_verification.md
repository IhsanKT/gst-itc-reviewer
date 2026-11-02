# Rule pack verification checklist

Rule pack version **2026.11.0** (`rules/cgst_17_5.yaml`, `rules/cgst_16.yaml`). Every entry ships with
`verified: false`. Check each one against the official Act, then set `verified: true` on that entry yourself.
The code never flips this flag.

**Official sources to check against**
- CBIC consolidated Act: <https://taxinformation.cbic.gov.in> (Acts → CGST Act → s.16, s.17)
- India Code: <https://www.indiacode.nic.in> (CGST Act, 2017, with amendment footnotes)
- Finance Acts 2021, 2022, 2023, 2024, 2025 (Gazette: <https://egazette.gov.in>) and the CGST notifications that
  brought each amendment into force.

**How the base text was obtained.** I downloaded CBIC's official consolidated PDF
(<https://cbic-gst.gov.in/pdf/CGST-Act-Updated-30092020.pdf>, updated 30.09.2020) and checked every entry
marked `VERBATIM` with a script: after normalising whitespace and dashes, each one is an exact substring of
that PDF's text. Two entries are split by a page break in the PDF (the plant-and-machinery Explanation and
§16(2)(c)), so I checked those two by eye. The PDF predates every amendment from 2021 onward. Those entries
are marked `DRAFT` and are the main risk.

## A. DRAFT text: highest priority (not from an official text)

| # | Entry | What to check |
|---|-------|---------------|
| 1 | `S17_5_D` | Exact Finance Act 2025 wording (s.124?) substituting "plant and machinery" for "plant or machinery"; that it is deemed effective **01.07.2017**; the commencement notification (reported as 16/2025-CT, 17.09.2025). |
| 2 | `S17_EXPL_PLANT_AND_MACHINERY` | FA 2025 renumbers this Explanation as **Explanation 1** and inserts an **Explanation 2**. Explanation 2's text is **missing from the pack**: add it verbatim. |
| 3 | `S17_5_FA` (CSR) | Exact wording; that it was inserted by FA 2023 (section number?); that it took effect **01.10.2023**. |
| 4 | `S17_5_I` (3 versions) | (i) Did FA 2023 drop "129 and 130" w.e.f. 01.10.2023, leaving "section 74"? (ii) The FA 2024 wording w.e.f. 01.11.2024: is it "section 74 in respect of any period up to Financial Year 2023-24"? Does it also mention s.74A? (iii) Are the date boundaries in `effective_from`/`effective_to` right? |
| 5 | `S16_2_AA` | FA 2021 wording and the 01.01.2022 effective date. |
| 6 | `S16_2_PROVISO_180` | The FA 2022 wording of the second proviso ("shall be paid by him along with interest payable under section 50"), w.e.f. 01.10.2022. The third proviso is verbatim from 2020; confirm it is unchanged. |
| 7 | `S16_4` | FA 2022 wording ("thirtieth day of November following the end of financial year ... or furnishing of the relevant annual return, whichever is earlier"), w.e.f. 01.10.2022. |
| 8 | Comment above `S17_5_B_I_FOOD` | My reading that the employer-obligation proviso applies to **all of clause (b)**, citing CBIC Circular 172/04/2022-GST (06.07.2022). Confirm the circular number and that it says this. |

## B. VERBATIM text: confirm it is still current (no amendment since 30.09.2020)

| # | Entry | What to check |
|---|-------|---------------|
| 9 | `S17_5_A` + 3 exceptions | Unchanged since 01.02.2019. |
| 10 | `S17_5_AA` + 4 exceptions | Unchanged. |
| 11 | `S17_5_AB` + 3 exceptions | Unchanged. |
| 12 | `S17_5_B_I_*` (4 entries) | Unchanged. The split into food / beauty-health / vehicle-hire / insurance is mine: confirm the grouping is sensible. |
| 13 | `S17_5_B_II`, `S17_5_B_III` | Unchanged. |
| 14 | `S17_5_C` | Unchanged; the "(other than plant and machinery)" wording in (c) was always "and". |
| 15 | `S17_5_E`, `S17_5_F`, `S17_5_G`, `S17_5_H` | Unchanged. |
| 16 | `S17_EXPL_CONSTRUCTION` | Unchanged. |
| 17 | `S16_2_A`, `S16_2_B`, `S16_2_C` | Unchanged (16(2)(c) was amended in 2022 to refer only to s.41; confirm the current words). |

## C. Judgement calls I made (these drive routing, so they change the review rate)

| # | Field | My setting | Why it matters |
|---|-------|-----------|----------------|
| 18 | `ambiguity` | high: C, D, G · medium: A, AB, B(i)×4, FA, H · low: AA, B(ii), B(iii), E, F, I | `high` always routes the line to the CA. |
| 19 | `needs_business_profile` | true: A, AA, AB, B(i)×4, C, F | `true` always routes to the CA. This is the biggest driver of the review rate. |
| 20 | Exception `condition` text | Plain-English paraphrases (mine, not statute) | The LLM reads these. Check that none widens an exception beyond the statute. |
| 21 | Clause (f) | Added although it wasn't in the original list | Remove it if you want the pack limited to your list. |
| 22 | `covers_from` | 17(5): 2019-02-01; 16: 2022-10-01 | Earlier periods are refused rather than assessed with the wrong text. |

**Change these before the evaluation run, not after.** Rows 18 and 19 are pre-registered settings. Changing
them after seeing results counts as tuning on the eval set and must be logged.
