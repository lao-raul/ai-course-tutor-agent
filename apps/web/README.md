# Web Application

React + TypeScript application with two learner entry points: **Hiruzen** (ChinaTextbook
catalog, practice, progress/resume, inline and live Agent tutoring) and the existing
Course Tutor chat. Hiruzen is the default entry point; the top switch keeps Course Tutor
available.

## Local development

Run Agent API on port 8000 and Practice API on port 8001, then:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:3000/`. The Vite proxy sends `/v1/practice/**` to Practice
and other `/v1/**` paths directly to Agent. The production Nginx configuration uses
the corresponding `course-tutor-practice:8001` and `course-tutor-agent:8000`
Kubernetes Services. Both requests use the same learner bearer token. Override the
local token with `VITE_LOCAL_AUTH_TOKEN`; do not put production tokens in a Web build.

The Chinese/English/bilingual UI preference defaults to Chinese and is saved in this
browser's local storage. Study progress and resume are server-owned, so the learner
can continue on a different device after authenticating. Inline tutoring sends only
the visible question, never a protected answer, to Agent's SSE endpoint with
`assessment_mode=true` and the Practice-authoritative attempt count/release state.

## Verification

```bash
npm --prefix apps/web test
npm --prefix apps/web run lint
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e
```

The browser tests use generated fixtures and Chrome; they do not call the home NAS or
LM Studio. They cover catalog, generation, attempts, staged release, direct Agent SSE,
citations, reload/resume, language persistence, keyboard focus and axe accessibility.
Real textbook/model acceptance is a separate TASK-23 release gate.
