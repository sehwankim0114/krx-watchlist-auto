# V8.9.3 복구 XBRL context 재감사

- 대상: `002450` 삼익악기
- 복구 접수번호: `20260814002549`
- 기준 연도: `2025`
- 기존 V8.8.7 로직 재사용: `2026-09-15-v8.8.7-xbrl-cfs-ofs-selection-audit`

## 원칙

- V8.8.7과 동일한 CFS/OFS 선택, 연간 330~370일, context/member, unit, 값 유일성 규칙을 그대로 재사용한다.
- 한화에어로스페이스와 에쓰씨엔지니어링은 두 승인 exact fact가 모두 복구되지 않았으므로 대상에서 제외한다.
- 이 단계에서는 V8.8.8 source layer나 production score를 변경하지 않는다.

## 판정

- selection: `MATCHED_FS_MEMBER_BOTH_FACTS_UNIQUE`
- both unique: `True`
- promotion candidate: `True`

## 다음 단계

`EXTEND_SOURCE_ONLY_DA_LAYER_WITH_V893_VALIDATED_TICKER_AND_RERUN_DRY_RUN`
