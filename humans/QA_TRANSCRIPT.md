# Spec Review Q&A Transcript — 2026-02-19

Full record of questions asked and answers given during the project specification
review session. This exists because the owner does not have chat history enabled.

---

## Round 1: Initial Questions (Claude -> Owner)

### Q1: Model tag `gpt-oss:20b` — what is this?
**A:** "The code is your job." (Agent should figure it out from the codebase.)

### Q2: IQ scoring — where does IQ:100-160 map to difficulty?
**A:** Not directly answered. IQ scoring should be a Robot Framework **tag** on
tests, not a grading mode. Tests are tagged `IQ:100`, `IQ:120`, `IQ:140`, `IQ:160`.

### Q3: Superset vs Grafana — which is the visualization tool?
**A:** Grafana is the primary visualization tool. Superset's role is unclear —
might stay for SQL exploration, might be removed. TRON-themed Grafana dashboards
are the goal.

### Q4: Dashboard deprecation — confirmed?
**A:** "The dashboard is a prototype." Grafana replaces it. Migration path: build
Grafana dashboards first, then remove `dashboard/` entirely.

### Q5: OpenRouter — what's the scope?
**A:** OpenRouter is for cloud-hosted grading (external grader endpoint). Short-term:
`GRADER_ENDPOINT` and `GRADER_MODEL` env vars. Long-term: OpenRouter integration
for cloud-hosted grading when local models aren't accurate enough.

---

## Round 2: Architecture & Packaging

### Q1: Can RFC be used as a library or must it be forked?
**A:** "All of the above, RFC could be pulled in as a library or forked."

### Q2: AI review in CI — how should it work?
**A:** "The CI templates for AI review will use AI Agentic tools to review both
the code and the pipeline results. The AI agent will approve or deny the pull
request with a pass/fail, and then provide a grade of the quality, and a full
report. It would be cool to use robot framework tasks for this, but it maybe
too complicated for CI. Make sure the makefile can do everything that the
pipeline does."

### Q3: Ollama `/api/show` vs Playwright for model metadata?
**A:** "You can use api/show, but i also want robot to use playwright to do
some agentic workflows. RFC could grow in to agentic workflows with tasks."

### Q4: Auto-skip models that won't fit in VRAM?
**A:** "Keep it on the feature list."

### Q5: Dashboard confirmed as prototype?
**A:** "The dashboard is a prototype."

### Q6: Model tag question?
**A:** "I don't know the code is your job."

### Q7: GitLab vs GitHub pipeline relationship?
**A:** "Gitlab CI is running on my home network, GitHub is just checking the code.
The claude-code-staging branch is where your working, while I'm working and
reviewing the main branch and then syncing when i have reviewed and tested.
Both branches run pipelines so i can check for regressions."

---

## Round 3: Grading System

### Q: Is this the right tier layering for grading?
**A:** Owner provided a definitive tier model:

| Tier | Name | Description |
|------|------|-------------|
| 0 | Pure Robot | Deterministic RF asserts only |
| 1 | Robot + Python | RF keywords backed by Python logic |
| 2 | Robot + LLM | Single LLM grader |
| 3 | Robot + LLMs | 3+ grader models, majority vote, WARN on disagreement |
| 4 | Robot + LLMs + Docker | LLM output sandboxed in Docker |
| 5 | Other | External graders, human-in-the-loop |
| 6 | None | Data collection only |

**Key rule:** "All tests are verified by Robot, and build upon that. All tests
need to have robot or python checks."

---

## Round 4: Dashboard & Node Management

### Q: Single leaderboard or per-dimension rankings?
**A:** "I want a dashboard/webpage that i can use to determine the best model."

**Specifics:**
1. Model size should be in GB (can be researched on the web)
2. Pipelines need to discover which nodes are online, then make a list of models
   for each host
3. Owner wants to be able to change which models are loaded on which host via
   config or web interface

---

## Round 5: LLM Consensus Grading

### Q: LLM grading console — what does disagreement look like?
**A:** "I want an LLM console to grade the answers. I want robot warning messages
when the LLM console is not in agreement."

---

## Round 6: Control Panel Priority

### Q: Should we build a control panel for triggering tests?
**A:** "The control panel can do some stuff, but isn't priority. I think we can
stick with make and gitlab ci triggers to run the test."

---

## Round 7: TRON Theme

### Q: Sci-fi Grafana vibe — Mission Control / Cyberpunk / TRON / Iron Man?
**A:** "TRON - 10000 percent TRON."

---

## Round 8: Miscellaneous Decisions

### Q1: Default model portability?
**A:** "The default model is a best we have for now. The project should be
portable to other models."

### Q2: Cost tracking?
**A:** "Let's add a cost placeholder, which if running locally is just time."

### Q3: Testing the Makefile itself?
**A:** "Add a make command to test all make commands."

### Q4: TPU priority?
**A:** "This is very near term and high-priority but also high-complexity. The
database is currently the highest priority but keep reminding me that i want to
also use the TPU."

### Q5: Distribution options beyond PyPI?
**A:** "What other options besides PYPI are there?" (Agent researched and
provided 7 options including git+https, Docker, conda, GitHub Releases, etc.)

### Q8: What questions did the owner miss?
**A:** "What questions did I miss?" (Agent identified 12 missing questions —
see Round 9.)

---

## Round 9: The Questions the Owner Missed

Agent identified 12 gaps. Owner's answers:

### Q1: Reproducibility — temperature and seed?
**A:** "Yes you're right, i want temp, seed, i don't know if top_p, and top_k
matter that much, but sure if you think they matter then add them."

### Q2: Test suite versioning?
**A:** "The database should track the Git Version, but yeah it could be better
to use the project version and have some linkages back to the source code. A
version would be great. Adding a pipeline rule that auto-bumps the version when
merged to main would be ideal. If we could also make a changelog.rst from the
commits and use semver that would be ideal."

### Q3: Data retention?
**A:** "Rolling window lets go for 90 days for now."

### Q4: Multi-user access?
**A:** "I want a public view of the results. And internal tools. Everything TRON."

### Q5: Model versioning — SHA256 digests?
**A:** "Yes use the SHA256 in the database, but use a slug name."

### Q6: Alerting?
**A:** "Gitlab pipeline failure is good enough. We could also add discord."

### Q7: Secrets management?
**A:** ".env is where they be."

### Q8: What makes a good LLM test?
**A:** "Right now the prompts are very short, but i want to also extend to
tool-calls, and long term chats. Add a feature to measure the LLMs ability
to tell jokes, and then tell stories, and then roll-play."

### Q9: Failure modes?
**A:** "There should be warnings for stuff that isn't due to the LLM failing.
Robot should be resilient to failures with allowed retries when services are down."

### Q10: Best model for what?
**A:** "The grafana database would show different perspectives on what is best."

### Q11: Ollama security on home network?
**A:** "No." (No network segmentation. Acknowledged.)

### Q12: TPU reminder?
**A:** "Yes. That sounds good. I expect the TPU will just be another endpoint
but is out of scope for this repo right now."

---

## Post-Round 9: Personality & Documentation

### Q: Agent personality?
**A:** "I want claude to be funny, but also ask me lots of questions, make the
ai/AGENT.md capture this too."

### Q: Chat history?
**A:** "I don't have chat history on so everything we talked about needs to be
in the repo."

---

## Open Questions (Not Yet Asked or Answered)

These were identified during the review but not yet discussed with the owner:

1. **Prompt engineering guidelines** — what makes a "well-designed test case" vs
   a vague one? Is there a rubric for test quality?
2. **Multi-turn conversation testing** — how many turns? Fixed scripts or
   dynamic conversation trees?
3. **A/B comparison methodology** — do all models run the identical test suite?
   Same prompts, same order, same parameters?
4. **Grafana provisioning** — Infrastructure as Code for Grafana dashboards, or
   manual setup through the UI?
5. **Database migration strategy** — when schema changes, how do existing records
   get migrated? Alembic? Manual scripts?
6. **Superset keep or kill** — firm decision needed. Running both Superset and
   Grafana is maintenance overhead.
7. **OpenRouter budget/limits** — when cloud grading is added, is there a
   cost ceiling?
8. **Role-play evaluation criteria** — what does "good role-play" look like?
   Character consistency? Creativity? Staying in character under pressure?

---

*This transcript ensures no context is lost between sessions. All decisions
captured here are also reflected in `ai/CLAUDE.md` and `humans/TODO.md`.*
