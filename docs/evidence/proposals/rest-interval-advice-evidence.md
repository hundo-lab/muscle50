# 제안: 휴식 근거(REST) 수정과 추가 — rest-interval-advice

- 작성일: 2026-11-01. 상태: **제안(사용자 승인 전)**. `docs/evidence/training-nutrition-evidence.md`는 바꾸지 않았다.
  승인되면 그 문서에 반영하고 이 파일은 지운다.
- 계기: `docs/specs/rest-interval-advice.md`를 쓰며 REST-01..08을 원문으로 다시 확인했다(사용자 원칙 2026-10-25).
- 원문 접근: Europe PMC REST API(초록, PMC 본문 XML). ACSM 2009는 대학 강의 사이트의 PDF 사본
  (`https://sfu.ca/~ryand/kin343/ACSMresistance.pdf`)으로 읽었다. Schoenfeld 2015 본문은 유료라 초록만 읽었다.
- 표기: `verified (full text | abstract | PDF copy)` / `unverified` / `(계산)`은 이 문서에서 계산한 값.

## 1. 기존 행 수정 제안

### P1. REST-01 적용 메모: "'충분' 기준 90초", "결정적 규칙 가능" 삭제

- 현재 메모: "`결정적 규칙 가능`: 근비대 목표의 휴식 하한 **60초**, "충분" 기준 **90초**."
- 원문(Singer 2024, PMC11349676, full text):
  - 초록: "our analysis did not detect appreciable differences in hypertrophy when resting >90 s between sets".
  - 결론: "The current evidence remains equivocal as to whether resting more than 90 s between sets further enhances
    hypertrophic adaptations. Our analysis casts doubt as to any beneficial effects in this regard. However, given the
    uncertainty of evidence, additional studies are needed".
  - 분석 범주는 short ≤ 60 s / intermediate 60 < d < 120 s / long 120 ≤ d < 180 s / very long ≥ 180 s다. **90 s는 범주가 아니다.**
  - network 추정(short 대비): 팔 intermediate 0.22 [−0.31, 0.74], long −0.02 [−0.43, 0.37], very long 0.18 [−0.36, 0.70];
    허벅지 intermediate 0.13 [−0.31, 0.58], long 0.01 [−0.39, 0.41], very long 0.32 [−0.10, 0.68]. 모두 0을 포함한다.
- 제안 메모: "`조언만`: 60 s는 Singer의 범주 경계이고 > 60 s의 작은 이득은 불확실하다(CrI가 0 포함). > 90 s의 추가 이득은
  저자 표현으로 'equivocal'이며 이득이 멈추는 값으로 쓰지 않는다. 휴식 판정이나 자동 규칙에 쓰지 않는다."
- 조건 칸에 추가: "9편 중 8편 18–35세, 1편 > 65세. 훈련자만의 하위분석은 자료 부족으로 못 함('Insufficient data were
  available to subanalyze results in trained individuals')."
- 이유: 사용자 원칙("이득이 어떤 값에서 멈춘다고 쓰지 않는다")과 맞추기. "충돌" 메모의 "근비대 결과(Singer)는 90초"도
  "Singer는 > 90 s를 equivocal로 봄"으로 고친다.

### P2. REST-02 적용 메모: 쓰는 범위 좁히기

- 현재 메모: "다관절 종목에서 '1분보다 2–3분' 안내의 근거로 쓴다."
- 원문(PMID 26605807, abstract): 1분 vs **3분**만 비교했다. 주 3회 전신 7종목(Singer 표: 스쿼트, 레그프레스, **레그 익스텐션**,
  벤치, 밀리터리 프레스, 랫 풀다운, 그리고 추출본에서 잘린 일곱째 "plate-loaded seat..."로 시티드 로우로 보임)이고 종목별로 휴식을 다르게 하지 않았다. 근두께 차이는 대퇴 전면만 유의,
  삼두 p = 0.06, 팔꿈치 굴곡근은 차이가 보고되지 않았다(초록).
- 제안 메모: "조언 근거. '3분이 1분보다 큰 증가(전신 루틴, 젊은 훈련자 21명)'로만 쓴다. '다관절 종목은 ≥ 2분' 또는
  '2–3분'의 근거로 쓰지 않는다(2분은 비교되지 않았고 종목 종류별 비교가 아님)."

### P3. REST-07 보강

- 확인(PDF copy): 근력 "rest periods of at least 2-3 min be used for core exercises using heavier loads (those exercises
  included specifically to improve maximal strength such as the squat and bench press)"(category B), 보조 종목 "a shorter
  rest period length of 1-2 min may suffice"(category C). 근비대 category C 문장도 근거 문서와 같다.
- 추가 제안(조건 칸): 고령자 권고 "1-3 min of rest in between sets"는 category A **권고 묶음**(다관절·단관절, 느린–중간 속도,
  1–3세트, 60–80 % 1RM, 8–12회, 주 2–3회)의 일부다. 휴식 하나의 등급이 아니다. "older adults"의 나이 정의는 확인 못 함.
- 적용 메모 추가: "'core exercise'는 squat·bench 같은 고중량 근력 종목이다. muscle50의 `COMPOUND_PATTERNS`(로우, 풀업, 런지
  포함)를 core로 보는 것은 `[design]`이다. '다관절 120–180초'라는 범위는 원문 표현('at least 2-3 min')과 다르다."
- 근거 문서 메모 "다관절 120–180초, 단관절 60–120초"는 원문의 "최소 2–3분", "1–2분이면 될 수 있다"를 범위로 바꾼 것이라
  "(해석)" 표시를 붙인다.

### P4. REST-08 보강

- 확인(PMC12965823, full text) 그대로: 근력 "✖ 2 reviews; n = 982 QoE = 63%", 근비대 "? 4 reviews; n = 265 QoE = 44%".
- 추가: "포함 리뷰를 나이로 나누지 않았다('younger and older than the cutoff of 55-yr old ... recommendations are
  evidence-based across all ages')."
- 주의 추가: 본문의 "2–3 min rest between sets"는 2002/2009 이전 지침을 요약한 문장이며 2026 권고가 아니다.
- 반복 속도 관련(TEMPO-01 제안과 연결): 근력은 "fast (<2 s) versus moderate-slow (>2 s) contractions"에 영향 없음,
  근비대는 "fast (0.5 s) versus slow (8 s) repetitions"에 영향 없음.

### P5. REST-04 조건 칸

- Longo 2022의 참가자는 **비훈련 남녀 28명**(Singer 표 "28 young, untrained men and women"; 초록 "Twenty-eight subjects").
  조건 칸에 "비훈련 남녀"를 더한다.

### P6. 문서 머리말의 대상 나이

- 머리말 "대상: 34세 남성"과 이번 요청의 "사용자 약 50세"가 다르다. 어느 쪽이 맞는지 사용자 확인이 필요하다. 나이에 따라
  아래 REST-09의 해석(적용 가능성)이 달라진다.

## 2. 새 행 제안

### REST-09(제안): 고령자(> 65세)의 세트 사이 휴식

| 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | 적용 메모 |
|---|---|---|---|---|
| 고령 남성, 4주 근비대 훈련 뒤 8주 근력 훈련(4–6회) | 60 s 휴식 군이 4분 군보다 제지방(LBM, p = 0.001), 머신 벤치·레그프레스 1RM(p < 0.001), 랫 풀다운(p < 0.01) 증가가 컸다. 두 군 평균 나이 65.6 vs 70.3세 | RCT, n = 22, 확실성 낮음(판단) | Villanueva MG, Lane CJ, Schroeder ET. 2015. Short rest interval lengths between sets optimally enhance body composition and performance with 8 weeks of strength resistance training in older men. *Eur J Appl Physiol* 115(2):295-308. doi:10.1007/s00421-014-3014-7 · PMID 25294666 (verified, abstract) | 조언만. "고령자에서 긴 휴식이 더 낫다"는 근거가 없음을 보이는 반대 방향 자료 |
| 훈련된 고령 여성(66.4 ± 4.4세), 레그프레스 3×15, 8주 | 1분 vs 3분: 동적·등척 근력, 근활성에서 집단 간 차이 없음(15RM 증가는 3분 군만 유의, 3.6 %) | RCT, n = 21, 확실성 낮음(판단) | Jambassi Filho JC, Gurjão ALD, Ceccato M, Prado AKG, Gallo LH, Gobbi S. 2017. Chronic Effects of Different Rest Intervals Between Sets on Dynamic and Isometric Muscle Strength and Muscle Activity in Trained Older Women. *Am J Phys Med Rehabil* 96(9):627-633. doi:10.1097/PHM.0000000000000701 · PMID 28145919 (verified, abstract) | 조언만 |
| 급성: 비훈련 젊은(24.2세) vs 고령(66.9세) 남성, 등속성 무릎 신전 3×10 | 고령 남성은 2분 휴식에서 최대 토크가 줄지 않았고, 젊은 남성은 1·2분 모두 줄었다. 3세트째 토크·일은 두 나이 모두 2분 > 1분 | EXP(교차), n = 37 | Bottaro M, Ernesto C, Celes R, Farinatti PT, Brown LE, Oliveira RJ. 2010. Effects of age and rest interval on strength recovery. *Int J Sports Med* 31(1):22-25. doi:10.1055/s-0029-1239497 · PMID 19885775 (verified, abstract) | 조언만. 장기 결과가 아님 |
| 급성: 훈련된 고령 여성(68.0세), 레그프레스 15RM 3세트 실패까지 | 3분 세션의 총 볼륨이 1분보다 29.4 % 많았다 | EXP(교차), n = 17 | Jambassi Filho JC, Gobbi LT, Gurjão AL, Gonçalves R, Prado AK, Gobbi S. 2013. Effect of different rest intervals, between sets, on muscle performance during leg press exercise, in trained older women. *J Sports Sci Med* 12(1):138-143. PMID 24149737, PMC3761766 (verified, abstract) | 조언만 |

- 충돌: 젊은 훈련자(REST-02)는 3분 > 1분, 고령 남성(Villanueva)은 60 s > 4분, 훈련된 고령 여성(Jambassi 2017)은 차이 없음.
- **40–60세 훈련자 대상 장기 시험은 찾지 못했다**(Europe PMC 제목 검색, 웹 검색, 2026-11-01). 약 50세 사용자에게는 직접 근거가 없다.

### TEMPO-01(제안): 반복 시간(반복 1회 전체 시간)

| 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | 적용 메모 |
|---|---|---|---|---|
| 근비대, 실패 지점까지 훈련, 6주 이상 | 반복 시간(단축 + 신장 + 등척의 합) **0.5–8 s**에서 근비대가 비슷했다. 의도적으로 매우 느린 반복(> 10 s)은 불리해 보였다(통제 연구 부족) | MA, 8편 | Schoenfeld BJ, Ogborn DI, Krieger JW. 2015. Effect of repetition duration during resistance training on muscle hypertrophy: a systematic review and meta-analysis. *Sports Med* 45(4):577-585. doi:10.1007/s40279-015-0304-0 · PMID 25601394 (verified, abstract) | 조언만. 0.5 s가 어느 포함 연구의 처방값인지 측정값인지 unverified(본문 유료) |
| 학회 권고(신판) | 근비대는 "fast (0.5 s) versus slow (8 s) repetitions"에 영향받지 않았다. 근력은 "fast (<2 s) versus moderate-slow (>2 s) contractions"에 영향받지 않았다 | PS(overview of reviews) | Currier 2026(REST-08과 같음) (verified, full text) | 조언만 |
| 스스로 고른 속도, 비훈련 남성 레그 익스텐션, 실패 지점까지 | 세트 시간(스톱워치) ÷ 반복 수 = **1.8 ± 0.3 s**(SELF), **1.7 ± 0.4 s**(SELF-EV), 통제 2 s : 2 s = 4.0 s. 8주 근비대·근력은 세 조건 모두 비슷 | RCT(개체 내), n = 20 | Chaves TS, Pires de Campos Biazon TM, Marcelino Eder dos Santos L, Libardi CA. 2020. Effects of resistance training with controlled versus self-selected repetition duration on muscle mass and strength in untrained men. *PeerJ* 8:e8697. doi:10.7717/peerj.8697 · PMC7061915 (verified, full text) | muscle50의 s/rep과 **같은 계산**이다. 1.0 s/rep은 이 평균보다 낮지만, 개별 세트 분포는 보고되지 않아 몇 %가 1.0 s 아래인지는 알 수 없다 |
| 학회 권고(구판) 속도 | 중급 이상 "moderate contraction velocity (1-2 s CON; 1-2 s ECC)"; 빠른 속도 예 "fast (1:1)" | PS, category A–C | ACSM 2009(REST-07과 같음) (verified, PDF copy) | 조언만 |

- strength-set-timing에 주는 결과: **1.0 s/rep을 "불가능한 최소값"으로 볼 근거는 없다.** 연구 프로토콜에 0.5 s 반복이 있었다.
  상수는 `[design]` 그대로 두고, Known issues의 "빠른 반복의 오탐 가능"을 이 근거로 구체화한다. 기준을 바꾸거나 사용자 설정으로
  하는 것은 set-timing의 후속 기능으로 따로 정한다.

## 3. "확인 못 한 것"에 더할 항목

1. Schoenfeld 2015 본문: 0.5 s를 쓴 포함 연구, 처방값/측정값 여부, 포함 연구 목록.
2. Schoenfeld 2016의 효과 크기와 최종 분석 수(기존 항목 3 그대로, 이번에도 확인 못 함).
3. Yamazaki 2025는 이번에 다시 읽지 않았다.
4. 40–60세 훈련자의 휴식 장기 시험(찾지 못함), 에너지 결핍(cut) 중 휴식 길이를 비교한 시험(찾지 않음).
5. ACSM 2009 "older adults"의 나이 정의.
6. NSCA의 근비대 휴식 권고(30–90 s)는 Singer 2024의 인용으로만 봤다(원문 확인 못 함).
