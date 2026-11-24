| Version | P@5 | R@20 | nDCG@10 | violations@10 | judged@10 |
|---|---|---|---|---|---|
| vector only | 0.08 (0.04–0.13) | 0.51 (0.26–0.76) | 0.42 (0.28–0.55) | 0.42 | 1.00 |
| vector + filters | 0.13 (0.07–0.20) | 0.77 (0.55–0.95) | 0.56 (0.46–0.67) | 0.13 | 1.00 |
| vector + filters + re-ranking | 0.15 (0.07–0.23) | 0.74 (0.52–0.92) | 0.60 (0.51–0.70) | 0.13 | 1.00 |
| + LLM limit check | 0.15 (0.07–0.23) | 0.61 (0.40–0.83) | 0.64 (0.54–0.73) | 0.05 | 1.00 |

15 personas, 588 labelled postings (31 good matches), labelled by: claude-opus-5-5. Database: 5000 active jobs after refresh run 4. Brackets: 95% bootstrap interval over personas.
