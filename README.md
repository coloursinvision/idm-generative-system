# Discord_Deck — warianty PL pod wklejenie na Discord

Wszystkie warianty: **technical Polish** (terminy techniczne EN inline), zoptymalizowane pod Discord
(tabele → listy, checkboxy → ✓/⬜, podział na posty ≤ **2000 znaków** — bez Nitro). Metryki realne (D-PIPE-05).

## Co jest czym + kolejność wklejania

**Status / portfolio:**

| Plik | Forma | Jak użyć |
|---|---|---|
| `A_status-post.PL.discord.md` | tekst, **3 posty** | Główny post statusowy. Wklejaj sekcje między znacznikami `POST 1/3 … 3/3` jako osobne wiadomości. |
| `B1_pipeline-spec.PL.diagram.png` | **diagram ikonograficzny** (1650×5354) | **REKOMENDOWANY** wariant spec na Discord: pionowy flow L1→L6 z ikonami, węzeł LEAKAGE z wykresem before/after, pętla MLOps. Mało tekstu, czytelny at-a-glance. Źródło: `_render_spec_diagram.py`. |
| `B1_pipeline-spec.PL.poster.png` | grafika tekstowa (1650×4315) | Alternatywa: gęstszy poster tekstowy (pełniejsza treść, mniej wizualny). Źródło: `_render_spec_poster.py`. |
| `B2_notebook-intro.PL.discord.md` | tekst, **1 post** | Wklej + dołącz plik `01_pipeline_walkthrough.ipynb` jako załącznik. |
| `D_addendum.PL.discord.md` | tekst, **2 posty** | Errata do decka/briefu (opcjonalne — bardziej wewnętrzne). |

**Specyfikacja techniczna:**

| Plik | Forma | Jak użyć |
|---|---|---|
| `initial_specs.md` | tekst, **1 post** | Podstawowe komponenty: Streamlit (auxiliary panel) · Qdrant (vector DB) · Langfuse (LLM monitoring). |
| `v2_specs.md` | tekst, **3 posty** | Resume specyfikacji V2 + moduł TUNING (idea, przepływ describe→review→compute, kontrakt API). |
| `appendix_offline-vs-web.md` | tekst, **2 posty** | Różnice: lokalnie (`develop`, pełne fixy) vs web (`main`/droplet, stara wersja) — blokada release INF-T. |

**Skrypty (źródła grafik):**

| Plik | Forma | Jak użyć |
|---|---|---|
| `_render_spec_diagram.py` | skrypt | Źródło diagramu ikonograficznego (env `idm`); edycja treści → `python _render_spec_diagram.py`. |
| `_render_spec_poster.py` | skrypt | Źródło postera tekstowego (env `idm`); edycja treści → `python _render_spec_poster.py`. |

## Uwagi

- **Znaczniki `═══ POST n/m ═══`** są tylko separatorami — NIE wklejaj samych linii ze znacznikami.
- **Notebook `.ipynb`** leży w `app-review/idm-pipeline/mlops-interview/` — dołącz go jako załącznik (Discord nie renderuje notebooków inline; GitHub renderuje ładnie).
- **Limit obrazu** na Discordzie (bez Nitro): 10 MB — poster ma ~1 MB, OK. Discord może go skompresować w podglądzie; pełna jakość po kliknięciu.
- **Linki `[text](url)`** renderują się tylko w embedach, nie w zwykłych wiadomościach — w tych materiałach nie ma linków, więc to nie problem.
- Pełne (nie-Discord) wersje źródłowe: `app-review/idm-pipeline/` (status post EN, PIPELINE_SPEC.md, notebook, ADDENDUM).
