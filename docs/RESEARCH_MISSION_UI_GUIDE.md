# Research Mission — UI Guide

## 1. How to run a 24h research mission from the UI

1. Open the Layla UI (e.g. `http://localhost:8000/ui`).
2. In the sidebar, under **Research Mission Control**:
   - Enter **Workspace path** (e.g. `C:\github\myrepo`). This folder will be copied into the research lab; the mission runs on that copy.
   - Choose **Mission Depth**: **Full** (map → investigation → verification → distillation → synthesis → confidence → consistency → risk → tradeoffs → patterns → actions → agenda → journal → summary).
   - Optionally check **Continue to next stage automatically** if you want the pipeline to extend by one more stage when using Map or Deep.
3. Click **▶ Start Research Mission**.
4. Leave the tab open or close it. The mission runs on the server. It will:
   - Run each stage in order (skipping any already completed if resuming).
   - Stop after 4 hours (hard cap) or when all stages are done, or after 2 consecutive no-progress stages.
   - Write stage outputs to `agent/.research_brain/` and the combined report to `agent/.research_output/last_research.md`.
5. Come back later and open the UI again. The **Research Mission Status** panel (and the 30s auto-refresh) will show current status, last run time, completed stages, and whether the mission is complete, partial, or stopped.

---

## 2. How to resume

1. Open the UI.
2. Set **Workspace path** to the same repo as before (or leave as is if already set).
3. Set **Mission Depth** to the same value you used when you started (e.g. **Full**).
4. Click **⏸ Resume Mission** (or **▶ Start Research Mission** — both POST the same request; the backend skips stages that are already in `mission_state.json` `completed`).
5. The mission will run only the stages that are not yet completed. Progress and status continue to appear in **Research Mission Status** and in the chat when the run finishes.

---

## 3. Where to look to see progress

- **Research Mission Status** panel (right-hand panels):
  - **Status:** complete / partial / stopped / (empty if never run).
  - **Last run:** timestamp of last mission run.
  - **Current stage:** last stage that wrote to mission state.
  - **✔ Completed:** list of stages already completed (resume skips these).
  - **⚠ Mission stopped early — resumable:** shown when status is `partial` or `stopped`.
  - **Mission in progress or resumable:** shown when status is not `complete`.
- Status is refreshed automatically every 30 seconds.
- On disk: `agent/.research_brain/mission_state.json` holds `status`, `completed`, `stage`, `last_run`.

---

## 4. Where to look to see actions produced

- **Research Mission Status** panel → **Actions** tab: loads `agent/.research_brain/actions/action_queue.md` (top 3 high-impact next steps with impact, effort, risk, confidence).
- **Summary** tab: `agent/.research_brain/summaries/24h_summary.md` (what was learned, verified, uncertain, recommended next actions).
- **Patterns** tab: `agent/.research_brain/patterns/patterns.md`.
- **Risks** tab: `agent/.research_brain/risk/risk_model.md`.
- **Last Output** tab: full combined report from `agent/.research_output/last_research.md`.
- Buttons **📄 View Last Summary** and **🧠 View Research Brain** open the Summary and Actions tabs respectively and show the content in the scrollable area below the tabs.
