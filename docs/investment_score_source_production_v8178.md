# V8.17.8 controlled production source-cache apply

- Promotes the exact V8.17.7 288-row staged source candidate.
- Production source cache: 227 -> 288 rows.
- Blockers: 906 -> 543 (-363).
- READY/LIMITED remains 14/143.
- 61 direct rows and exactly 3 preferred-share inheritance rows change.
- Unexpected drift 0; lost READY 0.
- Source timestamp now follows financial timestamp, so scheduled V8.5.4 gate is synchronized.
- Financial run log metadata is marked source-synchronized; financial cache itself is unchanged.
- Rollback restores source cache/source log/financial log on failure.
- API, score and scoring policy are unchanged.

Next: POST_SOURCE_APPLY_DYNAMIC_BLOCKER_REAUDIT_V8179
