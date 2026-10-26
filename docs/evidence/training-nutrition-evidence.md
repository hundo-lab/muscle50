# muscle50 근거 규칙집: 근력 훈련·영양·지질·간 수치·손목 심박

- 작성일: 2026-10-23 (2026-10-25: 10–12절 수면, 동시 훈련 간섭, 유지·감량기 훈련 추가)
- 상태: **사용자 승인 (2026-10-25)**. 규칙을 고치거나 더할 때는 다시 원문으로 확인하고 승인받는다.
- 목적: muscle50의 결정적 규칙(휴식 시간 조언, 주당 set, 증량, 단백질 목표, LDL 식단 안내, 세트 시작 시각 보정)을 만들 때
  기댈 숫자와 그 출처를 한곳에 모은다. 규칙 하나하나를 출처 원문(초록 또는 본문)과 대조했다. 대조하지 못한 주장은 표에 넣지 않고
  맨 끝 "확인 못 한 것"에 적었다.
- 대상: 34세 남성, 근력 약 주 3회, 달리기·수영 병행, 목표는 근비대와 전반적 건강. 최근 검사: LDL-C 157 mg/dL, 총콜레스테롤
  227 mg/dL, BMI 26.1, AST 91 / ALT 39 IU/L, 음주 약 월 1회. 그 밖의 개인 정보는 적지 않는다.
- **이 문서는 진단이 아니다.** 지질과 간 수치 항목은 "조언만"이며 실제 판단은 의사 상담과 재검으로 한다. muscle50은 이 항목들로
  자동 판정이나 경고 등급을 만들지 않는다.

## 읽는 법

### 근거 강도 표기

| 표기 | 뜻 |
|---|---|
| MA | 체계적 문헌고찰 + 메타분석(메타회귀, 네트워크 MA, Bayesian MA 포함) |
| SR | 체계적 문헌고찰(통합 수치 없음) |
| RCT | 무작위 대조 시험(개체 내 설계 포함) |
| EXP | 소규모 실험·급성(한 번 측정) 연구, 사례 연구 |
| GL | 임상 진료지침. 확인된 경우 권고 등급(COR/Class)과 근거 수준(LOE)을 붙인다 |
| PS | 학회 position stand / consensus statement |
| NR | 서술적 리뷰, 전문가 의견 |
| CONF | 학회 초록(동료 심사 약함) |

확실성은 출처가 GRADE 등으로 밝힌 경우 그대로 적고(예: "GRADE 중간"), 출처가 밝히지 않으면 `(판단)`을 붙여 이 문서가 매긴
값임을 표시한다: 높음 / 중간 / 낮음.

### 적용 메모 표기

- `결정적 규칙 가능`: 숫자가 깔끔한 기준이나 범위여서 muscle50 코드의 상수로 쓸 수 있다(그래도 상수 옆에 이 문서 ID를 적는다).
- `조언만`: 문구 안내로만 쓴다. 자동 판단, 점수, 경고 등급의 입력으로 쓰지 않는다.
- muscle50 데이터 원칙(결측은 0이 아님, 추측 금지)이 그대로 적용된다. 예: RIR은 기록되지 않으므로 RIR 규칙은 조언만이다.

### 출처 접근 방식에 대한 주의

- PubMed 웹 페이지가 막혀 초록은 대부분 NCBI E-utilities 또는 Europe PMC REST API로 받았다. 모든 DOI는 Crossref에서 제목,
  제1저자, 연도를 대조했다(연도 차이는 온라인 선공개와 권호 연도 차이뿐이었다).
- Pelland(주당 volume·frequency)의 세부 수치는 **2024년 9월 SportRxiv preprint**에서 읽었다. 2025/2026 Sports Medicine 정식판은
  초록만 읽었고, 정식판 수치는 다를 수 있다.
- Robinson 2024의 기울기 수치도 2023년 11월 preprint에서 읽었다(결론은 정식판 초록과 같다).
- ESC/EAS 2019·2025 인용은 웹 추출기를 통해 읽었고, 권고 등급(Class/Level)은 이미지로만 있어 확인하지 못했다.
- KSoLA 2022는 학회가 낸 15쪽 영문 요약본(pocket guideline)을 읽었다. DOI와 권고 등급이 없다.
- 2026 ACC/AHA 이상지질혈증 지침 전문은 제3자 사이트에 올라온 PDF로 읽었다(DOI는 Crossref에서 확인).
- Mensink 2016(WHO 보고서)은 원문 접근이 막혀 미국 영양사협회(Academy of Nutrition and Dietetics) Evidence Analysis Library 표의
  재인용 수치를 썼다.
- 단위 환산(mmol/L × 38.67 = mg/dL, µkat/L × 60 ≈ U/L)은 이 문서에서 직접 계산한 값이며 `(환산)`으로 표시한다.

---

## 1. 세트 사이 휴식 (REST)

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| REST-01 | 근비대 목표, 건강한 성인, 부위 무관 | 세트 사이 휴식 **> 60초**에서 근비대에 작은 이득이 있다. **> 90초부터는 더 늘려도 차이를 찾지 못했다.** 효과 크기는 작고 불확실하다(대조 SMD: 팔 0.13 [95% CrI −0.27~0.51], 허벅지 0.17 [−0.13~0.43], 전신 −0.08; 모두 0을 포함). 저자들은 이득이 volume load 감소를 통해 매개될 수 있다고 본다. (이전 SR: 짧은 ≤ 60초·긴 > 60초 휴식 모두 근비대를 만들고, 민감한 측정을 쓴 훈련자 연구에서는 긴 휴식이 "유리할 수 있다", 6편.) | MA(Bayesian), RCT 9편·19개 측정, 확실성 낮음~중간(판단) / SR 6편(통합 없음) | Singer A, Wolf M, Generoso L, et al. 2024. Give it a rest: a systematic review with Bayesian meta-analysis on the effect of inter-set rest interval duration on muscle hypertrophy. *Front Sports Act Living* 6:1429789. doi:10.3389/fspor.2024.1429789 · Grgic J, Lazinica B, Mikulic P, Krieger JW, Schoenfeld BJ. 2017. The effects of short versus long inter-set rest intervals in resistance training on measures of muscle hypertrophy: A systematic review. *Eur J Sport Sci* 17(8):983-993. doi:10.1080/17461391.2017.1340524 | `결정적 규칙 가능`: 근비대 목표의 휴식 하한 **60초**, "충분" 기준 **90초**. 실제 휴식이 60초 미만이면 "짧음" 안내. 단, 보정된 휴식(strength-set-timing)이 있을 때만 판정한다. |
| REST-02 | 근비대·근력, **훈련 경험자** 남성, 다관절 위주 전신 루틴(3세트 8–12RM) | **3분 휴식 > 1분 휴식**: 8주 후 스쿼트·벤치 1RM과 대퇴 전면 근두께 증가가 3분 군에서 더 컸다. 삼두는 경향(p=0.06). 근지구력은 차이 없음. | RCT, n=21, 확실성 낮음(판단, 소표본 단일 연구) | Schoenfeld BJ, Pope ZK, Benik FM, et al. 2016. Longer Interset Rest Periods Enhance Muscle Strength and Hypertrophy in Resistance-Trained Men. *J Strength Cond Res* 30(7):1805-1812. doi:10.1519/JSC.0000000000001272 | 조언 근거. 다관절 종목에서 "1분보다 2–3분" 안내의 근거로 쓴다. REST-01과 함께 쓴다. |
| REST-03 | 근력 목표, 훈련 경험자 / 비훈련자 | **훈련자**: 최대 근력 향상을 위해 **> 2분** 휴식이 필요하다. 짧은 휴식(< 60초)도 근력은 "상당히" 늘지만 최대화하지는 못한다. **비훈련자**: 짧거나 중간 휴식(**60–120초**)으로 충분하다. | SR(통합 없음), 23편·491명, 질 "good~moderate"(modified Downs and Black) | Grgic J, Schoenfeld BJ, Skrepnik M, Davies TB, Mikulic P. 2018. Effects of Rest Interval Duration in Resistance Training on Measures of Muscular Strength: A Systematic Review. *Sports Med* 48(1):137-151. doi:10.1007/s40279-017-0788-x | `결정적 규칙 가능`: 근력(저반복·고중량) 세트의 휴식 하한 **120초**(사용자는 훈련 경험자). 현재 목표가 근비대라 보조 규칙. |
| REST-04 | 근비대, 휴식과 volume load의 관계(무릎 신전, 80% 1RM, 10주) | 근비대는 휴식 길이보다 **총 volume load**가 결정했다. 3분 휴식 13.1%, 1분 휴식이지만 3분 군 volume load에 맞춘 경우 12.9% vs 1분 휴식 6.8%, 3분 휴식이지만 1분 군 volume load에 맞춘 경우 6.6%(대퇴사두 CSA). 1RM은 모든 조건이 26.5–31.2%로 차이 없음. | RCT(개체 내), n=28, 확실성 낮음(판단) | Longo AR, Silva-Batista C, Pedroso K, et al. 2022. Volume Load Rather Than Resting Interval Influences Muscle Hypertrophy During High-Intensity Resistance Training. *J Strength Cond Res* 36(6):1554-1559. doi:10.1519/JSC.0000000000003668 | 조언 근거: "휴식을 짧게 했다면 같은 volume을 채우려면 세트가 더 필요하다." 휴식 규칙을 세트 수 규칙과 분리해 두는 근거. |
| REST-05 | 급성: 다음 세트에서 유지되는 반복 수(하체 1/2/3분; 고중량 85% 1RM 벤치 2–8분) | 반복 수 감소는 **1분 vs 2–3분 사이**에서 가장 컸고, **2분 vs 3분 차이는 사소**했다. 다관절(스쿼트)이 단관절보다 젖산·불편감이 컸다. 고중량(85% 1RM) 벤치프레스 훈련자에서는 4세트 동안 반복 수를 **완전히 유지한 것이 8분 휴식뿐**이었고(2·5분은 감소), 5세트 실패까지 한 다른 연구에서도 8분 volume load가 4분보다 컸다(약 2,164 vs 1,668 kg). | EXP(교차) 3편(n 미기재 / n=15 / n=13), 확실성 낮음(판단) | Rosa A, Coleman M, Haun C, Grgic J, Schoenfeld BJ. 2023. Repetition Performance, Rating of Perceived Discomfort, and Blood Lactate Responses to Different Rest Interval Lengths in Single-Joint and Multijoint Lower-Body Exercise. *J Strength Cond Res* 37(7):1350-1357. doi:10.1519/JSC.0000000000004508 · Hernandez DJ, Healy S, Giacomini ML, Kwon YS. 2021. Effect of Rest Interval Duration on the Volume Completed During a High-Intensity Bench Press Exercise. *J Strength Cond Res* 35(11):2981-2987. doi:10.1519/JSC.0000000000003477 · Yamazaki Y, Shimamori K, Takizawa K, Yamaguchi T, Shibata K. 2025. Effects of Rest Interval Configuration Between Sets on Volume Load During Five Sets of Bench Press and Back Squat Exercise. *J Strength Cond Res* 39(11):1123-1128. doi:10.1519/JSC.0000000000005202 | `결정적 규칙 가능`(보조): 반복 수 유지 관점의 "충분" 기준 **120초**. REST-01의 90초와 다르다(아래 충돌 참고). 고중량 세트에서는 긴 휴식에도 반복 수가 떨어지는 것이 정상이므로 반복 감소 자체를 "피로 경고"로 쓰지 않는다. |
| REST-06 | 자율 휴식 vs 고정 휴식(75초), 훈련자 남성, 상체 4종목, 8주 | 자율 휴식이 반복 수는 더 많았지만(예: 체스트 프레스 26.1 vs 21.5회) 근력 향상은 같았다(6.8% vs 7.4%). 고정 휴식이 시간 효율이 37% 더 좋았다. | RCT, n=33, 확실성 낮음(판단) | Simão R, Polito M, Freitas de Salles B, et al. 2022. Acute and Long-Term Comparison of Fixed vs. Self-Selected Rest Interval Between Sets on Upper-Body Strength. *J Strength Cond Res* 36(2):540-544. doi:10.1519/JSC.0000000000003606 | 조언만: 고정 시간을 강요하지 않고 "최소 기준만 넘기면 됨" 형태로 안내하는 근거. |
| REST-07 | 학회 권고(구판): 건강한 성인 | 근력: 고중량 **핵심 다관절 종목(스쿼트·벤치) 최소 2–3분**(근거 B), 보조 종목 **1–2분**(근거 C), 1–6RM 고중량은 3–5분. 근비대: 초·중급 **1–2분**(근거 C), 상급은 고중량 핵심 종목 2–3분, 나머지 1–2분. | PS, 근거 범주 B/C | American College of Sports Medicine. 2009. Progression models in resistance training for healthy adults. *Med Sci Sports Exerc* 41(3):687-708. doi:10.1249/MSS.0b013e3181915670 | `결정적 규칙 가능`: compound/isolation 구분 기본값(다관절 120–180초, 단관절 60–120초)의 출처. 단 REST-08이 이 처방을 철회했다. |
| REST-08 | 학회 권고(신판, 2009 대체): 건강한 성인, 무작위 시험 ≥ 6주 | **구체적 휴식 처방이 없다.** 근력은 짧은(< 1분)·긴(> 1분) 휴식에 영향받지 않았다(리뷰 2편, n=982, 근거 질 63%). 근비대는 휴식 영향을 "판단할 자료 부족"(리뷰 4편, n=265, 근거 질 44%). | PS(overview of reviews: SR 137편, 30,000명 이상) | Currier BS, D'Souza AC, Singh MAF, et al. 2026. American College of Sports Medicine Position Stand. Resistance Training Prescription for Muscle Function, Hypertrophy, and Physical Performance in Healthy Adults: An Overview of Reviews. *Med Sci Sports Exerc* 58(4):851-872. doi:10.1249/MSS.0000000000003897 | 조언 문구에 "최신 ACSM은 휴식 시간을 정하지 않는다"를 함께 적는 근거. 휴식 규칙은 강한 권고가 아니라 "권장 범위"로 표시한다. |

**충돌**

- 근비대 휴식: ACSM 2009는 초·중급 1–2분(약한 근거 C), Schoenfeld 2016은 훈련자에서 3분 > 1분, Singer 2024는 > 60초에서 작은
  이득·> 90초 이후 차이 없음, ACSM 2026은 판단 불가. Longo 2022와 Singer 2024는 효과가 주로 volume load를 통해 나온다고 본다.
- 근력 휴식: ACSM 2026은 "1분 기준으로 차이 없음", Grgic 2018은 훈련자에서 > 2분 권장, ACSM 2009는 핵심 종목 2–3분. 기준점이
  1분과 2–3분으로 달라 정면 충돌이라기보다 비교 구간이 다르다.
- "충분한 휴식" 기준: 근비대 결과(Singer)는 90초, 반복 수 유지(Rosa)는 120초, 고중량 반복 유지(Hernandez)는 8분. 무엇을 기준으로
  보느냐(근비대 결과 vs 같은 세션 내 반복 유지)에 따라 다르다.
- compound vs isolation을 직접 비교한 장기(근비대) 시험은 찾지 못했다. 다관절 종목에 더 긴 휴식을 주는 근거는 ACSM 2009(B/C)와
  급성 연구(Rosa 2023)뿐이다.

---

## 2. 근육별 주당 세트 수 (VOL)

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| VOL-01 | 근비대, 주당 세트 수 용량-반응 | 주당 세트가 1개 늘 때마다 효과 크기 +0.023(근비대 증가율 +0.37%). 고용량이 저용량보다 ES 0.241(+3.9%p) 컸다. 3구간(< 5, 5–9, ≥ 10세트) 비교는 경향만(p=0.074). | MA(메타회귀), 15편·34개 처치군 | Schoenfeld BJ, Ogborn D, Krieger JW. 2017. Dose-response relationship between weekly resistance training volume and increases in muscle mass: A systematic review and meta-analysis. *J Sports Sci* 35(11):1073-1082. doi:10.1080/02640414.2016.1210197 | 조언 근거: "세트가 많을수록 대체로 더 자란다." 구간 경계(5, 10)는 통계적으로 확정되지 않았다. |
| VOL-02 | 세트 세는 법(직접/간접) | 간접 자극 세트(예: 벤치프레스의 삼두)를 **0.5세트로 세는 "fractional" 방식**이 근비대·근력 모두에서 가장 잘 맞았다(간접을 1로 세는 total, 0으로 세는 direct와 비교). | MA(다층 메타회귀), 67편·2,058명(남 79.1%), 훈련 기간·훈련 상태 보정 | Pelland JC, Remmert JF, Robinson ZP, Hinson SR, Zourdos MC. 2026(온라인 2025-12-04). The Resistance Training Dose Response: Meta-Regressions Exploring the Effects of Weekly Volume and Frequency on Muscle Hypertrophy and Strength Gains. *Sports Med* 56(2):481-505. doi:10.1007/s40279-025-02344-w | `결정적 규칙 가능`: 근육별 주당 set 집계에서 primary 근육 1.0, secondary 근육 0.5. 현재 taxonomy(`docs/exercise-taxonomy.md`)에 primary(1개)와 `secondary_muscles`가 있어 바로 적용할 수 있다. |
| VOL-03 | 근비대·근력, 주당 fractional 세트 | 세트가 늘수록 근비대가 계속 늘지만 수확 체감(제곱근 모양)이다. 기울기 세트당 0.24%(95% CrI 0.15–0.33). **최소 유효량 약 4 fractional 세트/주.** 효율 구간: 5–10, 11–18, 19–29, 30–42세트, 43 이상은 불명확. **뚜렷한 상한은 없었지만** 약 25세트 이상을 다룬 연구는 적다. 검출 가능한 최소 효과는 근비대 2.05%. **근력**은 수확 체감이 더 강하다(역수 모양, 기울기 세트당 0.21%, 95% CrI 0.16–0.26): 최소 유효량 **1세트**, 검출 가능한 최소 효과(3.96%)를 넘는 추가 이득은 약 **4세트** 이후 사라진다. | MA(메타회귀), 근비대 모델 35편·1,032명, 근력 모델 66편·2,020명. **preprint(2024-09) 수치** | Pelland JC, et al. 2024. SportRxiv preprint. doi:10.51224/SRXIV.460 (정식판은 VOL-02) | `결정적 규칙 가능`(범위 표시용): 주당 fractional set < 4는 "부족", 10–20은 일반 권장 범위(VOL-04와 함께), > 30은 "자료 적음". 정식판 수치 확인 전까지 경계값은 잠정. |
| VOL-04 | 근비대, **훈련자 남성(18–35세, ≥ 1년)** | 주당 세트를 low < 12, moderate 12–20, high > 20으로 나눴을 때 moderate와 high는 대퇴사두(p=0.19)·이두(p=0.59)에서 차이 없음. 삼두만 high가 유리(p=0.01). 저자 결론: **12–20세트/주/근육**이 일반 권장으로 적당. ACSM 2026: 근비대는 **주당 ≥ 10세트**에서 향상된다. | MA, RCT 7편(MA 6편) + PS(ACSM 2026) | Baz-Valle E, Balsalobre-Fernández C, Alix-Fages C, Santos-Concejero J. 2022. A Systematic Review of The Effects of Different Resistance Training Volumes on Muscle Hypertrophy. *J Hum Kinet* 81:199-210. doi:10.2478/hukin-2022-0017 · Currier 2026 ACSM(REST-08) | `결정적 규칙 가능`: 근육별 주당 목표 범위 **12–20** set(하한 10은 ACSM 2026). 현재 region 모델(region당 주 1–2회)이면 근육당 세션당 약 6–10 set(주 2회) 또는 12–20 set(주 1회, FREQ-01의 나누기 권고에 걸림)(계산값). |

**충돌**

- 상한: Pelland preprint는 근비대에 뚜렷한 상한이 없다(약 30–42세트까지 수확 체감)고 보고, Baz-Valle는 12–20을 넘는 이득을 대퇴사두·이두에서
  찾지 못했다(삼두만 > 20 유리). 고용량 연구가 적어서 상한은 열려 있다.
- 세트 세는 법이 연구마다 다르다. Schoenfeld 2017과 Baz-Valle는 대체로 직접 세트 기준이라 Pelland의 fractional 숫자와 1:1로 비교할 수 없다.

---

## 3. 반복 범위·부하·실패 근접도(RIR) (LOAD)

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| LOAD-01 | 근비대와 최대 근력, 모든 세트를 실패까지 | **근비대는 부하에 관계없이 비슷**하다: 저부하(≤ 60% 1RM)와 고부하(> 60%) 차이 없음(21편). 네트워크 MA에서도 저(> 15RM)·중(9–15RM)·고(≤ 8RM) 부하 간 근비대 차이 없음(P=0.113–0.469). 반면 **1RM은 고부하가 유리**: 고부하 vs 저부하 SMD 0.60–0.63, 중부하 vs 저부하 0.34–0.35, 고 vs 중 0.26–0.28(P=0.068). | MA 2편(21편 / 28편·747명) | Schoenfeld BJ, Grgic J, Ogborn D, Krieger JW. 2017. Strength and Hypertrophy Adaptations Between Low- vs. High-Load Resistance Training: A Systematic Review and Meta-analysis. *J Strength Cond Res* 31(12):3508-3523. doi:10.1519/JSC.0000000000002200 · Lopez P, Radaelli R, Taaffe DR, et al. 2021. Resistance Training Load Effects on Muscle Hypertrophy and Strength Gain: Systematic Review and Network Meta-analysis. *Med Sci Sports Exerc* 53(6):1206-1216. doi:10.1249/MSS.0000000000002585 | 현재 기본값(compound 5–12, isolation 10–20회)이 근비대 근거 범위 안에 있다는 확인. 반복 범위를 넓게 허용해도 된다는 근거. 1RM을 올리고 싶다면 일부 세트를 ≤ 8RM으로(조언만). |
| LOAD-02 | 근비대·근력, 실패 vs 비실패 | 실패까지 한 세트의 이득은 **사소**: ES 0.19(95% CI 0.00–0.37, p=0.045). 순간 실패만 따로 보면 0.12(−0.13~0.37), 유의하지 않음. 관계가 비선형일 수 있다. 다른 MA: 전체로는 근력 ES −0.09, 근비대 ES 0.22, 모두 유의하지 않음. volume을 맞추지 않은 연구에서는 근력에 비실패가 유리(ES −0.32). **훈련자에서는 실패가 근비대에 약간 유리**(ES 0.15, 95% CI 0.03–0.26). | MA 2편(각 15편) | Refalo MC, Helms ER, Trexler ET, Hamilton DL, Fyfe JJ. 2023. Influence of Resistance Training Proximity-to-Failure on Skeletal Muscle Hypertrophy: A Systematic Review with Meta-analysis. *Sports Med* 53(3):649-665. doi:10.1007/s40279-022-01784-y · Grgic J, Schoenfeld BJ, Orazem J, Sabol F. 2022. Effects of resistance training performed to repetition failure or non-failure on muscular strength and hypertrophy: A systematic review and meta-analysis. *J Sport Health Sci* 11(2):202-211. doi:10.1016/j.jshs.2021.01.007 | 조언만: "모든 세트를 실패까지 갈 필요 없다." |
| LOAD-03 | RIR 용량-반응(연구 설명에서 추정한 RIR) | **근비대는 실패에 가까울수록 커진다**(preprint 기울기: RIR 1당 SMC −0.019, 95% CI −0.035~−0.004). **근력은 RIR에 거의 무관**(기울기 +0.003, CI −0.012~0.018). | MA(탐색적 다층 메타회귀). 근비대 26편, 근력 55편(**preprint 수치**) | Robinson ZP, Pelland JC, Remmert JF, et al. 2024. Exploring the Dose-Response Relationship Between Estimated Resistance Training Proximity to Failure, Strength Gain, and Muscle Hypertrophy: A Series of Meta-Regressions. *Sports Med* 54(9):2209-2231. doi:10.1007/s40279-024-02069-2 | 조언만(RIR은 기록되지 않는다). 기존 조언 문구 RIR 1–3과 맞다. |
| LOAD-04 | RIR 자기 추정의 정확도 | 실패까지 남은 반복을 평균 **0.95회 적게** 예측(95% CI 0.17–1.73), 사람 간 SD 1.45회, 이질성 매우 큼(I² 97.9%). 실패에 가까울수록, **≤ 12회** 세트일수록, 뒤 세트일수록 정확. 훈련 경력은 정확도와 무관. | MA(scoping review + 탐색적 MA), 12편·414명 | Halperin I, Malleron T, Har-Nir I, et al. 2022. Accuracy in Predicting Repetitions to Task Failure in Resistance Exercise: A Scoping Review and Exploratory Meta-analysis. *Sports Med* 52(2):377-390. doi:10.1007/s40279-021-01559-x | 조언 문구에 "RIR 추정은 ±1–2회 오차가 흔하다"를 덧붙이는 근거. RIR을 입력으로 받더라도 정확한 값으로 다루지 않는다. |

**충돌**

- 실패 근접도와 근비대: Robinson 2024는 실패에 가까울수록 계속 좋아진다고, Refalo 2023은 순간 실패의 이득이 없고 비선형일 수 있다고,
  Grgic 2022는 전체 차이는 없지만 훈련자는 실패가 약간 유리하다고 본다. 세 연구 모두 **근력은 RIR·실패에 영향받지 않는다**는 점은 같다.

---

## 4. 근육별 주당 훈련 빈도 (FREQ)

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| FREQ-01 | 근비대, **volume을 맞춘** 비교 | 주당 빈도는 근비대에 **유의하거나 의미 있는 영향이 없다**(훈련자, 상·하체 모두). volume을 맞추지 않으면 고빈도가 약간 유리(주로 volume 증가 효과). 최신 메타회귀(Pelland 2026)도 근비대에 대한 빈도 효과는 "무시할 만한 효과와 양립"(preprint: 주당 1회 추가당 +0.32%, 95% CrI −0.14~0.82, 기울기 > 0일 확률 91.3%). ACSM 2026: 1일/주 vs > 5일/주도 volume을 맞추면 차이 없음. 이전 MA(2016, 10편)는 주 2회가 1회보다 효과 크기가 컸다고 했지만(0.49 vs 0.30, P=0.002; 3회 > 2회는 판단 불가) 이후 더 큰 분석들이 이를 사실상 대체했다. | MA(25편) + MA(67편) + PS + 이전 MA(10편) | Schoenfeld BJ, Grgic J, Krieger J. 2019. How many times per week should a muscle be trained to maximize muscle hypertrophy? A systematic review and meta-analysis of studies examining the effects of resistance training frequency. *J Sports Sci* 37(11):1286-1295. doi:10.1080/02640414.2018.1555906 · Pelland 2026(VOL-02) · Currier 2026 ACSM(REST-08) · Schoenfeld BJ, Ogborn D, Krieger JW. 2016. Effects of Resistance Training Frequency on Measures of Muscle Hypertrophy: A Systematic Review and Meta-Analysis. *Sports Med* 46(11):1689-1697. doi:10.1007/s40279-016-0543-8 | `결정적 규칙 가능`: 빈도는 주당 set을 나누는 수단으로만 쓴다. 현재 region 규칙(주 1–2회)은 근거와 충돌하지 않는다. 세션당 한 근육에 set이 너무 몰리면(예: > 10) 나누기를 권하는 것은 근거가 약한 실용 규칙(판단). "근육당 주 2회"는 volume을 채우기 쉬운 실용 기본값으로만 쓴다. |
| FREQ-02 | 근력 | 근력은 빈도와 함께 커진다는 결과와 아니라는 결과가 함께 있다. Grgic 2018: ES 1회 0.74, 2회 0.82, 3회 0.93, 4회 이상 1.08이지만 volume을 맞추면 효과 없음(p=0.421) → volume 효과. Pelland preprint: 주당 훈련일 1일당 +3.27%(95% CrI 2.74–3.84), fractional 빈도 1→2에서 12.72%→17.32%, 그 뒤 수확 체감. ACSM 2026: **≥ 2일/주**에서 근력 향상, volume을 맞추면 효과 감소. ACSM 2009(구판) 전체 주당 훈련일: 초급 2–3일, 중급 3–4일(split이면 4일로 주요 근육군 각 2회, 근거 B), 상급 4–5일. | MA(22편, 대부분 비훈련자) + MA(preprint) + PS | Grgic J, Schoenfeld BJ, Davies TB, et al. 2018. Effect of Resistance Training Frequency on Gains in Muscular Strength: A Systematic Review and Meta-Analysis. *Sports Med* 48(5):1207-1220. doi:10.1007/s40279-018-0872-x · Pelland 2024 preprint · Currier 2026 ACSM · ACSM 2009(REST-07) | 조언만: "근력을 위해 같은 동작을 주 2회 이상". 사용자의 주 3회는 ACSM 2009 "중급" 범위 하한. |

---

## 5. 점진적 과부하(증량·반복 증가) (PROG)

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| PROG-01 | 처방 반복 범위가 있는 훈련, 건강한 성인 | 현재 무게로 **목표 반복보다 1–2회 더**를 **연속 2회 세션**에서 해내면 무게를 **2–10%** 올린다(작은 근육 종목은 낮은 쪽, 큰 근육 종목은 높은 쪽). 처방 구간(예: 8–12RM) 안에서 진행해도 된다. | PS, 근거 범주 B(단일 인용 근거, 증량 폭끼리 비교한 시험 없음) | ACSM 2009(REST-07과 같음) | `결정적 규칙 가능`: 현재 double progression 규칙의 증량 조건과 폭의 출처. "연속 2회" 조건을 쓰는지 확인할 것. 폭은 isolation 2–5%, compound 5–10%로 나누는 것은 이 문서의 해석(판단). |
| PROG-02 | 무게 진행 vs 반복 진행 | 두 방식 모두 비슷하게 효과적. 훈련자 8주(n=43): 대퇴직근 두께는 반복 진행이 약간(2.8 mm, 90% CI −0.5~5.8), 근력은 무게 진행이 약간(2.0 kg, −2.4~7.8) 유리, 모두 불확실. 비훈련자 10주(n=39): 1RM·외측광근 CSA 증가가 비슷. | RCT 2편, 확실성 낮음(판단) | Plotkin D, Coleman M, Van Every D, et al. 2022. Progressive overload without progressing load? The effects of load or repetition progression on muscular adaptations. *PeerJ* 10:e14142. doi:10.7717/peerj.14142 · Chaves TS, Scarpelli MC, Bergamasco JGA, et al. 2024. Effects of Resistance Training Overload Progression Protocols on Strength and Muscle Mass. *Int J Sports Med* 45(7):504-510. doi:10.1055/a-2256-5857 | 반복 증가도 "진행"으로 인정하는 근거(double progression의 반복 단계). |
| PROG-03 | 진행 필요성 | 무게를 올린 쪽(반복 범위 상단 도달 시 증량)이 같은 무게 유지보다 삼두 근두께 증가가 약 2배(+22.9% vs +11.6%, 비훈련 여성 n=55, 8주). 진행 없이도 근비대는 생겼다. ACSM 2026은 "건강 이득에는 진행이 필요 없고, 장기적으로 계속 발전하려는 사람에게 과부하가 필요할 것"이라고 본다. | RCT(개체 내) + PS | Kassiano W, Santos-Melo V, Manske I, et al. 2026. Progressive Overload Affects the Magnitude of Muscle Hypertrophy. *Med Sci Sports Exerc* 58(7):1556-1565. doi:10.1249/MSS.0000000000003968 · Currier 2026 ACSM | 조언 근거: 근비대 목표에서는 진행 규칙을 유지하는 것이 맞다. |

---

## 6. 단백질 섭취·분배, 에너지 결핍 (PRO)

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| PRO-01 | 저항 훈련 + 단백질, 건강한 성인 | 하루 단백질이 **1.62 g/kg/일**을 넘으면 제지방 증가 이득이 더 커지지 않았다(분기점, 95% CI 1.03–2.20, p=0.079로 통계적 유의성은 없음). 저자들은 최대 효과를 원하면 **약 2.2 g/kg/일**을 권한다. 보충 효과: 제지방 +0.30 kg, 1RM +2.49 kg, 훈련자에서 더 큼, 나이가 많을수록 작음. 다른 MA(RCT 74편): 65세 미만에서 하루 **≥ 1.6 g/kg**일 때 제지방 증가 SMD 0.30(95% CI 0.17–0.43, 23편, GRADE 중간), 저항 훈련 병행 전체 SMD 0.22(62편, GRADE 중간). | MA 2편(RCT 49편·1,863명 / RCT 74편, GRADE 중간) | Morton RW, Murphy KT, McKellar SR, et al. 2018. A systematic review, meta-analysis and meta-regression of the effect of protein supplementation on resistance training-induced gains in muscle mass and strength in healthy adults. *Br J Sports Med* 52(6):376-384. doi:10.1136/bjsports-2017-097608 · Nunes EA, Colenso-Semple L, McKellar SR, et al. 2022. Systematic review and meta-analysis of protein intake to support muscle mass and function in healthy adults. *J Cachexia Sarcopenia Muscle* 13(2):795-810. doi:10.1002/jcsm.12922 | `결정적 규칙 가능`: 단백질 하루 목표 범위 **1.6–2.2 g/kg 체중**. 체중은 InBody 측정값만 쓴다(매일 체중 없음). 체중이 없으면 목표를 계산하지 않는다. |
| PRO-02 | 단백질 하루 범위, 운동하는 사람 | 대부분의 운동인에게 **1.4–2.0 g/kg/일**. | PS(ISSN) | Jäger R, Kerksick CM, Campbell BI, et al. 2017. International Society of Sports Nutrition Position Stand: protein and exercise. *J Int Soc Sports Nutr* 14:20. doi:10.1186/s12970-017-0177-8 | PRO-01과 겹치는 구간 1.6–2.0이 가장 보수적인 합의 구간(판단). |
| PRO-03 | 끼니당 단백질과 간격 | ISSN: 끼니당 약 **0.25 g/kg 또는 20–40 g**, **3–4시간 간격**, 한 번에 류신 700–3,000 mg. Schoenfeld & Aragon: 근비대 최대화를 위해 **0.4 g/kg/끼 × 최소 4끼**(하루 ≥ 1.6 g/kg), 2.2 g/kg/일이면 끼니당 상한 0.55 g/kg. 급성 연구: 전신 저항 운동 후 100 g 섭취가 25 g보다 근단백질 합성이 크고 12시간 이상 지속(젊은 남성 n=36; 장기 근비대 결과는 아님). | PS(ISSN) + NR + RCT(급성 tracer) | Jäger 2017(PRO-02) · Schoenfeld BJ, Aragon AA. 2018. How much protein can the body use in a single meal for muscle-building? Implications for daily protein distribution. *J Int Soc Sports Nutr* 15:10. doi:10.1186/s12970-018-0215-1 · Trommelen J, van Lieshout GAA, Nyakayiru J, et al. 2023. The anabolic response to protein ingestion during recovery from exercise has no upper limit in magnitude and duration in vivo in humans. *Cell Rep Med* 4(12):101324. doi:10.1016/j.xcrm.2023.101324 | `결정적 규칙 가능`(메뉴 추천 보조): 끼니당 목표 0.25–0.4 g/kg(체중 75 kg 가정 시 약 19–30 g, 계산값). 하루 목표가 우선이고 분배는 보조. 끼니당 상한은 엄격한 규칙으로 쓰지 않는다(한 끼에 많이 먹어도 버려지는 것은 아니다). |
| PRO-04 | 에너지 결핍 + 저항 훈련 | 에너지 결핍은 제지방 증가를 방해하지만(ES −0.57, p=0.02) 근력은 아니다(ES −0.31, p=0.28). 약 **500 kcal/일 결핍에서 제지방 증가가 사라졌다** → 저자 권고: 근육을 늘리려면 **500 kcal/일보다 큰 결핍을 피한다**. | MA(메타회귀), RCT ≥ 3주 | Murphy C, Koehler K. 2022. Energy deficiency impairs resistance training gains in lean mass but not strength: A meta-analysis and meta-regression. *Scand J Med Sci Sports* 32(1):125-137. doi:10.1111/sms.14075 | `결정적 규칙 가능`(조정 권고의 상한): 감량 권고 폭은 −500 kcal/일보다 작게. goals.md의 ±100–150 kcal 조정과 충돌하지 않는다. LDL·체중 감량(LDL-10)과 근육 증가 목표가 부딪히는 지점이다. |
| PRO-05 | 감량기 단백질, 훈련자 | ISSN: 저칼로리 기간 제지방 유지에 **2.3–3.1 g/kg/일**(체중 기준)이 필요할 수 있다. Helms 등(내추럴 보디빌딩 대회 준비): **2.3–3.1 g/kg 제지방량**/일, 감량 속도 **주당 체중의 0.5–1%**, 지방 15–30% 에너지. | PS(ISSN) + NR | Jäger 2017(PRO-02) · Helms ER, Aragon AA, Fitschen PJ. 2014. Evidence-based recommendations for natural bodybuilding contest preparation: nutrition and supplementation. *J Int Soc Sports Nutr* 11:20. doi:10.1186/1550-2783-11-20 | 조언만(감량기 전용). 제지방량은 InBody 값을 쓸 수 있으나 기준(체중 vs 제지방량)이 출처마다 다르다. |

**충돌**

- 끼니당 단백질: ISSN 0.25 g/kg(20–40 g) vs Schoenfeld & Aragon 0.4 g/kg(최대 0.55). Trommelen 2023은 급성 합성에 상한이 없다고 본다(장기 결과 아님).
- 감량기 단백질의 분모: ISSN은 체중 기준, Helms는 제지방량 기준(같은 2.3–3.1이라도 실제 g 수가 체지방률만큼 다르다).
- 하루 목표: Morton의 1.62는 통계적으로 유의하지 않은 분기점이고 CI 상한이 2.20, ISSN 1.4–2.0은 1.6 아래까지 포함한다.

---

## 7. LDL-C가 높을 때의 식단 (LDL)

현재 값 해석에 필요한 분류: LDL-C 157 mg/dL ≈ 4.06 mmol/L(환산), 총콜레스테롤 227 mg/dL.

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| LDL-01 | 한국 성인 지질 분류(KSoLA) | LDL-C: 적정 < 100, 정상 100–129, **경계 130–159**, 높음 160–189, 매우 높음 ≥ 190 mg/dL. 총콜레스테롤: 경계 200–239, 높음 ≥ 240. 국내 역학 정의의 고LDL혈증은 LDL-C ≥ 160 또는 지질저하제 사용. → 157은 **경계(높음 직전)**, 227은 **경계**. | GL(요약본, 등급 표시 없음) | 한국지질·동맥경화학회(KSoLA) 진료지침위원회. 2022. Korean Guidelines for the Management of Dyslipidemia, 5th ed.(영문 요약). https://lipid.or.kr/eng/pub/images/guidlines_2022.pdf · Jin ES, et al. 2023. Dyslipidemia Fact Sheet in South Korea, 2022. *Diabetes Metab J* 47(5):632-642. doi:10.4093/dmj.2023.0135 | 조언만, 의사 상담/재검. 검사값을 입력받는 기능을 만든다면 분류 표시는 결정적으로 가능하지만 위험도 판정은 하지 않는다. |
| LDL-02 | KSoLA 위험도별 LDL-C 목표 | 관상동맥질환 < 55, 뇌졸중·말초동맥질환 등 < 70, **중등도 위험(주요 위험인자 ≥ 2개) < 130, 저위험(≤ 1개) < 160** mg/dL. 주요 위험인자: 남성 ≥ 45세, 조기 심혈관질환 가족력, 혈압 ≥ 140/90 또는 치료 중, 흡연, HDL-C < 40. 중등도·저위험에서 스타틴은 생활습관 교정을 수 주~수개월 해도 LDL-C가 계속 높을 때 고려. | GL(요약본) | KSoLA 2022(LDL-01과 같음) | 조언만, 의사 상담/재검. 위험인자 정보(가족력, 혈압, 흡연, HDL)가 muscle50에 없으므로 위험도 분류를 하지 않는다. |
| LDL-03 | 유럽 위험도별 LDL-C 목표 | 저위험 < 3.0 mmol/L(< 116 mg/dL), 중등도 위험 < 2.6 mmol/L(< 100 mg/dL). 2025 focused update에서 **목표값은 바뀌지 않았다**. 2025 update: SCORE2/SCORE2-OP(40–89세) 사용, Lp(a)는 성인이면 **일생에 한 번 이상** 측정 고려(> 50 mg/dL 또는 ≥ 105 nmol/L면 높음). | GL(Class/Level은 이미지라 미확인) | Mach F, Baigent C, Catapano AL, et al. 2020. 2019 ESC/EAS Guidelines for the management of dyslipidaemias. *Eur Heart J* 41(1):111-188. doi:10.1093/eurheartj/ehz455 · Mach F, Koskinas KC, Roeters van Lennep JE, et al. 2025. 2025 Focused Update of the 2019 ESC/EAS Guidelines for the management of dyslipidaemias. *Eur Heart J* 46(42):4359-4378. doi:10.1093/eurheartj/ehaf190 | 조언만, 의사 상담/재검. |
| LDL-04 | 미국(2026 신지침, 2018 대체): 젊은 성인·저위험 1차 예방 | 18–39세 젊은 성인에게는 누적 LDL 노출을 줄이기 위한 식단·신체활동·체중 권고를 제공(COR 1, LOE B-NR). 30–59세 저위험(10년 위험 < 3%)이고 **LDL-C < 160 mg/dL이며 30년 위험 < 10%면 생활습관 상담**(COR 1, LOE A). **LDL-C 160–189** 또는 30년 위험 ≥ 10%면 중등도 강도 스타틴이 합리적(COR 2a, LOE C-LD). Lp(a)는 모든 성인에서 한 번 이상 측정 권고(COR 1; ≥ 125 nmol/L 또는 ≥ 50 mg/dL이면 높음). | GL(COR/LOE 확인) | Blumenthal RS, Morris PB, et al. 2026. 2026 ACC/AHA/AACVPR/ABC/ACPM/ADA/AGS/APhA/ASPC/NLA/PCNA Guideline on the Management of Dyslipidemia. *JACC* 87:2624-2757. doi:10.1016/j.jacc.2025.11.016 (Circulation 동시 게재 doi:10.1161/CIR.0000000000001423) | 조언만, 의사 상담/재검. 157은 160 기준 바로 아래라 재검 결과에 따라 분류가 바뀔 수 있다는 점을 안내할 수 있다. 구지침(Grundy 2019, doi:10.1161/CIR.0000000000000625)은 20–39세에 평생 위험 추정과 생활습관을 우선, LDL ≥ 190이면 고강도 스타틴. |
| LDL-05 | 포화지방·트랜스지방·총지방·탄수화물 | KSoLA: **< 7% 에너지**, 단일·다중불포화지방으로 대체, 총지방 ≤ 30%. ESC 2019: **< 10%**, 고콜레스테롤혈증이면 **< 7%**로 더 낮춤. ACC/AHA 2019·2026: 포화·트랜스지방을 불포화지방으로 **대체**(2019: COR IIa, B-NR; 2026 식단 패턴: COR 1, B-R), **숫자 목표 없음**. **트랜스지방**: 모든 지침이 피한다(KSoLA "avoid", ESC "any consumption 피하기", ACC/AHA 2019 COR III-Harm, B-NR; ESC 본문에서 "< 1%" 숫자는 확인 못 함). KSoLA 기타: 총탄수화물 ≤ 65% 에너지, 총당류 < 10–20%, 건강 체중을 유지할 에너지. | GL 3개 | KSoLA 2022 · Mach 2020 ESC/EAS · Arnett DK, et al. 2019. 2019 ACC/AHA Guideline on the Primary Prevention of Cardiovascular Disease. *Circulation* 140:e596-e646. doi:10.1161/CIR.0000000000000678 · Blumenthal 2026 | 현재 데이터에 없음 → 조언만(필드 추가 필요): 음식 영양값은 kcal·단백질·탄수·지방 4개뿐이다. 포화지방 필드가 생기면 하루 포화지방 에너지 비율 목표 **< 7%**(KSoLA·ESC 고콜레스테롤혈증 공통 값)를 결정적으로 쓸 수 있다. 예: 2,400 kcal면 < 18.7 g(계산값). 그때도 값이 없는 음식이 있으면 "부분 합계"로만 표시하고 판정하지 않는다. 트랜스지방과 탄수 비율은 조언만(트랜스지방 값이 식단 데이터에 거의 없고, 탄수 비율은 근비대 목표와 충돌하지 않는다). |
| LDL-06 | 포화지방을 줄였을 때의 LDL 변화량 | 에너지 1%를 포화지방에서 다른 영양소로 바꿀 때 LDL-C 변화: 다중불포화 −0.055 mmol/L(≈ −2.1 mg/dL, 환산), 단일불포화 −0.042(≈ −1.6), 탄수화물 −0.033(≈ −1.3). ESC 2019: 포화지방 에너지 1%당 LDL-C 0.8–1.6 mg/dL 상승. | MA(메타회귀, 재인용) + GL | Mensink RP. 2016. Effects of saturated fatty acids on serum lipids and lipoproteins: a systematic review and regression analysis. WHO. (수치는 Academy of Nutrition and Dietetics EAL 2023 표 재인용: https://www.andeal.org/vault/2440/web/files/Saturated%20Fat/2023%20Guideline/2023-05_DLM-SF_Summary-Reduction-Replacement_SFandBloodLipids_SR_Table.pdf) · Mach 2020 ESC/EAS | 조언만: "포화지방을 에너지의 5%p 줄이고 불포화지방으로 바꾸면 LDL이 대략 8–10 mg/dL 낮아질 수 있다"(계산값, 개인차 큼). |
| LDL-07 | 식이 콜레스테롤(달걀 포함) | ESC 2019: **< 300 mg/일**, 특히 혈중 콜레스테롤이 높은 사람. KSoLA 2022: 고콜레스테롤혈증이면 줄인다(숫자 없음). ACC/AHA 2019: 줄이면 도움(IIa, B-NR, 숫자 없음). ACC/AHA 2026: 포화지방 제한이 콜레스테롤 제한보다 LDL을 더 일관되게 낮춘다. 크기: 식이 콜레스테롤 100 mg/일 증가당 LDL-C +1.90(선형)~4.58 mg/dL(모델별, 55편). 달걀·식이 콜레스테롤 시험 14편 순변화 +6.7 mg/dL(95% CI 1.7–11.7), 코호트에서 관상동맥질환과 유의한 연관 없음. | GL 4개 + MA 2편 | Mach 2020 · KSoLA 2022 · Arnett 2019 · Blumenthal 2026 · Vincent MJ, Allen B, Palacios OM, Haber LT, Maki KC. 2019. Meta-regression analysis of the effects of dietary cholesterol intake on LDL and HDL cholesterol. *Am J Clin Nutr* 109(1):7-16. doi:10.1093/ajcn/nqy273 · Berger S, Raman G, Vishwanathan R, Jacques PF, Johnson EJ. 2015. Dietary cholesterol and cardiovascular disease: a systematic review and meta-analysis. *Am J Clin Nutr* 102(2):276-294. doi:10.3945/ajcn.114.100305 | 조언만: 우선순위는 포화지방(LDL-05)이 먼저, 콜레스테롤은 다음. 현재 데이터에 콜레스테롤 필드가 없다(필드 추가 필요). 생기면 "< 300 mg(ESC)"를 참고값으로 표시 가능. |
| LDL-08 | 식이섬유·수용성 섬유 | KSoLA: 식이섬유 **≥ 25 g/일**. ESC 2019: 총 식이섬유 **25–40 g/일, 그중 수용성 ≥ 7–13 g**; 베타글루칸 3–10 g/일로 LDL-C 3–5% 감소. 메타분석: 귀리 베타글루칸 중앙 **3.5 g/일 → LDL-C −0.19 mmol/L(≈ −7.3 mg/dL, 환산)**(RCT 58편, I² 79%). 차전자피(psyllium) 중앙 **약 10.2 g/일 → −0.33 mmol/L(≈ −12.8 mg/dL)**(RCT 28편, GRADE 중간). 수용성 섬유 1 g당 LDL −0.057 mmol/L(2–10 g/일 범위). | GL 2개 + MA 3편 | KSoLA 2022 · Mach 2020 · Ho HVT, Sievenpiper JL, Zurbau A, et al. 2016. The effect of oat β-glucan on LDL-cholesterol, non-HDL-cholesterol and apoB for CVD risk reduction: a systematic review and meta-analysis of randomised-controlled trials. *Br J Nutr* 116(8):1369-1382. doi:10.1017/S000711451600341X · Jovanovski E, Yashpal S, Komishon A, et al. 2018. Effect of psyllium (Plantago ovata) fiber on LDL cholesterol and alternative lipid targets, non-HDL cholesterol and apolipoprotein B: a systematic review and meta-analysis of randomized controlled trials. *Am J Clin Nutr* 108(5):922-932. doi:10.1093/ajcn/nqy115 · Brown L, Rosner B, Willett WW, Sacks FM. 1999. Cholesterol-lowering effects of dietary fiber: a meta-analysis. *Am J Clin Nutr* 69(1):30-42. doi:10.1093/ajcn/69.1.30 | 현재 데이터에 없음 → 조언만(필드 추가 필요): 식이섬유 필드가 생기면 하루 목표 **≥ 25 g**을 결정적으로 쓸 수 있다. 지금은 메뉴 추천에서 귀리·잡곡·콩류를 우선하는 조언 근거. |
| LDL-09 | 식물성 스테롤/스타놀 | ESC 2019: 하루 **2 g**으로 총콜레스테롤·LDL-C **7–10%** 감소. ESC 2025: 최대 2 g/일로 **약 10%** 감소, **심혈관 사건 감소를 보인 연구는 없다**. EAS 합의: 2 g/일에 8–10%. 용량-반응 MA: 0.6–3.3 g/일에 평균 6–12%. 홍국(red yeast rice): ESC 2019 최대 20% 감소라 했으나 2025 update는 임상 이득 근거가 없다고 보고, 안전성 미확인 보충제 사용을 지지하지 않는다. | GL + PS(EAS) + MA(124편) | Mach 2020 · Mach 2025 · Gylling H, Plat J, Turley S, et al. 2014. Plant sterols and plant stanols in the management of dyslipidaemia and prevention of cardiovascular disease. *Atherosclerosis* 232(2):346-360. doi:10.1016/j.atherosclerosis.2013.11.043 · Ras RT, Geleijnse JM, Trautwein EA. 2014. LDL-cholesterol-lowering effect of plant sterols and stanols across different dose ranges: a meta-analysis of randomised controlled studies. *Br J Nutr* 112(2):214-219. doi:10.1017/S0007114514000750 | 조언만(보충 식품. 사용 여부는 의사와 상의). |
| LDL-10 | 체중 감량 | ESC 2019: (비만인에서) **체중 10 kg 감량당 LDL-C 약 8 mg/dL(0.2 mmol/L) 감소**. ACC/AHA 2026: 과체중·비만이면 **≥ 5% 감량** 권고(COR 1, B-NR), LDL-C 감소는 **kg당 0.3–1.7 mg/dL**로 크지 않다. | GL 2개 | Mach 2020 · Blumenthal 2026 | 조언만. 근육 증가 목표와 부딪힌다: 체중보다 체지방 감소가 의미 있고, 결핍은 PRO-04 상한(< 500 kcal/일) 안에서. BMI 26.1에서 체중 감량만으로 기대할 LDL 감소는 작다(예: 5 kg이면 약 1.5–8.5 mg/dL, 계산값). |
| LDL-11 | 식단 패턴(portfolio, 견과, 콩) | Portfolio diet(식물성 스테롤 + 점성 섬유 + 콩 단백 + 견과): LDL-C **약 17%(−0.73 mmol/L ≈ −28 mg/dL)** 감소, GRADE 높음(7개 비교·439명). 견과 하루 1회분당 LDL-C **−4.8 mg/dL**(61편, ≥ 60 g/일에서 더 큼). 콩 단백 중앙 25 g/일 → LDL-C **−4.76 mg/dL(약 3–4%)**. ACC/AHA 2026: 과일·채소·견과·콩류·통곡·섬유를 강조하고 포화·트랜스지방을 불포화지방으로 바꾸는 식단(COR 1, B-R). | MA 3편 + GL | Chiavaroli L, Nishi SK, Khan TA, et al. 2018. Portfolio Dietary Pattern and Cardiovascular Disease: A Systematic Review and Meta-analysis of Controlled Trials. *Prog Cardiovasc Dis* 61(1):43-53. doi:10.1016/j.pcad.2018.05.004 · Del Gobbo LC, Falk MC, Feldman R, Lewis K, Mozaffarian D. 2015. Effects of tree nuts on blood lipids, apolipoproteins, and blood pressure: systematic review, meta-analysis, and dose-response of 61 controlled intervention trials. *Am J Clin Nutr* 102(6):1347-1356. doi:10.3945/ajcn.115.110965 · Blanco Mejia S, Messina M, Li SS, et al. 2019. A Meta-Analysis of 46 Studies Identified by the FDA Demonstrates that Soy Protein Decreases Circulating LDL and Total Cholesterol Concentrations in Adults. *J Nutr* 149(6):968-981. doi:10.1093/jn/nxz020 · Blumenthal 2026 | 조언만. 메뉴 추천에서 단백질원으로 콩·두부, 간식으로 견과를 우선할 근거(단백질 목표와 같은 방향). |

**충돌**

- **저위험 LDL-C 목표**: KSoLA < 160, ESC < 116(2025에도 같음), ACC/AHA 2026은 저위험에 숫자 목표 없이 "< 160이고 30년 위험 < 10%면 상담,
  160–189면 스타틴 합리적". 157은 KSoLA·ACC/AHA 기준선 160 바로 아래, ESC 저위험 목표 위다.
- **포화지방**: KSoLA < 7%, ESC < 10%(고콜레스테롤혈증이면 < 7%), ACC/AHA는 숫자 없이 "대체". AHA의 예전 < 5–6% 권고는 확인하지 못했다.
- **식이 콜레스테롤**: ESC < 300 mg/일, KSoLA·ACC/AHA 2019는 숫자 없는 "줄이기", ACC/AHA 2026은 중요도를 낮췄다.
- **식이섬유**: KSoLA ≥ 25 g, ESC 25–40 g(수용성 ≥ 7–13 g).
- **식물성 스테롤 2 g/일 효과**: ESC 2019 7–10%, ESC 2025 약 10%, EAS 8–10%, Ras 6–12%(0.6–3.3 g). 사건 감소 근거는 없다.
- **체중 kg당 LDL 감소**: ESC 약 0.8 mg/dL/kg(10 kg당 8에서 계산), ACC/AHA 2026 0.3–1.7 mg/dL/kg.
- **Lp(a) 기준**: ESC 2025 > 50 mg/dL(≥ 105 nmol/L), ACC/AHA ≥ 50 mg/dL 또는 ≥ 125 nmol/L.

---

## 8. 운동과 지질, 간 수치(AST/ALT)와 음주·체중 (EXL / LIV)

### 8.1 운동이 지질에 미치는 영향

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| EXL-01 | 운동 훈련 전체(유산소·저항·병행) | 전체 통합: LDL **−7.22 mg/dL(−0.19 mmol/L, 95% CI −9.08~−5.35)**, 총콜레스테롤 −5.90, HDL +2.11, TG −8.01 mg/dL. **병행·유산소는 LDL을 낮췄지만 저항 훈련 단독은 낮추지 않았다.** 주당 유산소 세션 1회 추가당 총콜레스테롤 −7.68 mg/dL. 예측 구간으로 보면 지질 개선은 연구의 약 4분의 1에서만 나타난다. | MA, RCT 148편·8,673명(trial sequential analysis 포함) | Smart NA, Downes D, van der Touw T, et al. 2025. The Effect of Exercise Training on Blood Lipids: A Systematic Review and Meta-analysis. *Sports Med* 55(1):67-78. doi:10.1007/s40279-024-02115-z | 조언만: "LDL에는 달리기·수영 같은 유산소를 꾸준히 하는 것이 도움이 될 수 있지만 효과 크기는 식단보다 작다." |
| EXL-02 | 점진적 저항 훈련 단독, 성인 | LDL-C **−6.1 mg/dL(95% CI −11.2~−1.0, 약 −4.6%)**, 총콜레스테롤 −5.5, non-HDL −8.7, TG −8.1 mg/dL, HDL +0.7(유의하지 않음). 다른 MA(효과 크기만): LDL ES −0.451. | MA, RCT 29편·1,329명 / MA | Kelley GA, Kelley KS. 2009. Impact of progressive resistance training on lipids and lipoproteins in adults: a meta-analysis of randomized controlled trials. *Prev Med* 48(1):9-19. doi:10.1016/j.ypmed.2008.10.010 · Costa RR, Buttelli ACK, Vieira AF, et al. 2019. Effect of Strength Training on Lipid and Inflammatory Outcomes: Systematic Review With Meta-Analysis and Meta-Regression. *J Phys Act Health* 16(6):477-491. doi:10.1123/jpah.2018-0317 | 조언만. EXL-01과 충돌(아래). |
| EXL-03 | 유산소와 HDL, 신체활동 권고량 | HDL +2.53 mg/dL. HDL을 올리는 최소 주당 운동량 **약 900 kcal 또는 120분/주**, 세션당 10분 추가마다 약 +1.4 mg/dL. 지침 권고: KSoLA 유산소 **주 ≥ 5일, 30–60분/일**(감량 목적 50–60분), 강도 HRR 40–75%, 저항 운동 주 2–3일(1RM 50–85%). ACC/AHA 2026: 중강도 **≥ 150분/주** 또는 고강도 75–150분/주 + 저항 운동 주 ≥ 2일. | MA(25편) + GL 2개 | Kodama S, et al. 2007. Effect of aerobic exercise training on serum levels of high-density lipoprotein cholesterol: a meta-analysis. *Arch Intern Med* 167(10):999-1008. doi:10.1001/archinte.167.10.999 · KSoLA 2022 · Blumenthal 2026 | `결정적 규칙 가능`(활동 집계 표시용): 주간 유산소 분 합계(달리기+수영)를 150분 기준과 비교해 표시. 단, 수영 간섭 규칙(근력 우선)과 함께 본다. |

**충돌**: 저항 훈련과 LDL. Smart 2025(148편)는 저항 훈련 단독의 LDL 감소를 찾지 못했고, Kelley 2009(29편)는 −6.1 mg/dL, Costa 2019는 ES −0.45를
보고했다. Smart 2025의 예측 구간은 효과가 연구 간에 크게 다르다는 것을 보여 준다.

### 8.2 간 수치, 음주, 체중

현재 값: AST 91 / ALT 39 IU/L(AST가 ALT보다 높음). 아래 LIV-01·02가 보여 주듯 힘든 근력 운동 뒤에도 이런 모양이 나올 수 있지만,
**원인 판단은 의사가 한다.** muscle50은 이 값으로 판정하지 않는다.

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| LIV-01 | 웨이트 트레이닝 뒤의 간 수치(건강한 남성, 웨이트 비숙련, 약 1시간·10종목·3세트 약 12회·약 70%) | 14명 **모두 운동 3·4·5일 뒤 AST가 기준 상한을 넘었다.** 최고치 중앙 도달 시간: AST 96시간, ALT 120시간, CK 96시간. AST·ALT·CK·myoglobin은 **최소 7일 동안** 높게 남았다(중앙 정상화 시간 "192시간"은 7일째에도 높았던 경우에 붙인 값). AST/ALT 비는 6시간~7일 동안 모두 > 1이었고, 10–12일에는 12명이 < 1(ALT가 아직 기준 위). 반감기 차이(ALT 47시간, AST 17시간)로 설명. 저자 권고: 임상시험 시작 전 **최소 1주 웨이트 트레이닝 제한**. 일상 진료에서도 웨이트 트레이닝을 간 수치 상승 원인으로 고려하라고 함. 최고치: AST 16.0, ALT 4.1 µkat/L(상한 0.7; ≈ AST 960, ALT 246, 상한 42 U/L, 환산). | EXP(대조군 없음), n=15 등록·14 분석, 평균 24.5세, 확실성 낮음(판단) | Pettersson J, Hindorf U, Persson P, et al. 2008. Muscular exercise can cause highly pathological liver function tests in healthy men. *Br J Clin Pharmacol* 65(2):253-259. doi:10.1111/j.1365-2125.2007.03001.x | 조언만, 의사 상담/재검: "간 수치 검사 전 **최소 7일** 힘든 근력 운동을 쉬고, 검사 때 CK도 함께 확인을 요청하자." 근거가 웨이트 비숙련자 대상이라 꾸준히 훈련하는 사람에서의 크기·기간은 다를 수 있다(확인 못 함). 10–12일 무렵에는 ALT만 남아 간 원인처럼 보일 수 있다. |
| LIV-02 | 근육 손상과 AST/ALT 비, CK 개인차 | 급성 근육 손상(극단적 운동, 다발성 근염, 발작)에서 AST/ALT 비가 **> 3**이었다가 AST가 빨리 떨어지면서 며칠 뒤 **1에 가까워졌다**(사례 16명). 최대 편심성 팔꿈치 굴곡 24회 뒤 최고 CK가 사람마다 **236–25,244 IU/L**로 크게 달랐고, CK 최고치는 AST·ALT 최고치와 강하게 상관(r 0.79–0.95). | EXP(후향 사례 / 실험 n=10) | Nathwani RA, Pais S, Reynolds TB, Kaplowitz N. 2005. Serum alanine aminotransferase in skeletal muscle diseases. *Hepatology* 41(2):380-382. doi:10.1002/hep.20548 · Nosaka K, Clarkson PM. 1996. Variability in serum creatine kinase response after eccentric exercise of the elbow flexors. *Int J Sports Med* 17(2):120-127. doi:10.1055/s-2007-972819 | 조언만: 운동 뒤 수치 크기는 사람마다 크게 달라 "운동 때문"인지는 CK와 재검으로만 가릴 수 있다. |
| LIV-03 | 간 수치 이상의 평가(ACG 지침) | 건강한 정상 ALT: **남성 29–33 IU/L**, 여성 19–25. 이상 수치는 **재검 및/또는 확인 검사**(강한 권고, 근거 수준 매우 낮음). 운동·스포츠의 강한 근육 사용은 **AST 위주의 상승**을 일으킬 수 있고, 흔한 원인을 배제한 뒤 **CK 및/또는 aldolase**로 근육 원인을 확인. 알코올성 간질환은 흔히 **AST:ALT ≥ 2:1**(AST·ALT가 300을 넘는 경우는 드묾), > 3:1이면 가능성 더 높음. 남성 **주 210 g 넘게** 마시면서 AST > ALT면 위험군으로 본다. | GL(ACG) | Kwo PY, Cohen SM, Lim JK. 2017. ACG Clinical Guideline: Evaluation of Abnormal Liver Chemistries. *Am J Gastroenterol* 112(1):18-35. doi:10.1038/ajg.2016.517 | 조언만, 의사 상담/재검. AST/ALT 비만으로 원인을 말하지 않는다(근육 손상과 알코올 모두 AST > ALT). 사용자의 음주(월 1회)는 주 210 g 기준과 거리가 멀다는 사실 정도만 안내 가능. |
| LIV-04 | 음주 | WHO 유럽(2023): 건강에 영향이 없는 **안전한 음주량은 없다**; 알코올 관련 암의 약 절반이 과음 기준 미만 음주자에서 발생. 미국 DGA 2025–2030: "덜 마실수록 건강에 좋다", **잔 수 숫자 없음**(2020–2025판의 남성 하루 ≤ 2잔은 삭제). KSoLA 2022(지질): 하루 ≤ 1–2잔. | 공식 성명 + GL | WHO Regional Office for Europe. 2023-01-04. No level of alcohol consumption is safe for our health. https://www.who.int/europe/news/item/04-01-2023-no-level-of-alcohol-consumption-is-safe-for-our-health · U.S. Dietary Guidelines for Americans 2025–2030. https://www.dietaryguidelines.gov · KSoLA 2022 | 조언만. |
| LIV-05 | 체중·운동과 지방간(MASLD) | 과체중·비만 MASLD에서 체중 **≥ 5% 감량은 간 지방 감소, 7–10%는 간 염증 개선, ≥ 10%는 섬유화 개선**(근거 수준 2, 강한 권고). 신체활동 **중강도 > 150분/주 또는 고강도 75분/주**(근거 수준 1, 강한 권고). | GL(EASL-EASD-EASO 2024, executive summary) | EASL, EASD, EASO. 2024. EASL-EASD-EASO Clinical Practice Guidelines on the management of metabolic dysfunction-associated steatotic liver disease (MASLD). *Diabetologia* 67:2375-2392. doi:10.1007/s00125-024-06196-3 | 조언만. MASLD 진단이 있는 경우에만 해당하는 숫자다(사용자는 진단 정보 없음). |

---

## 9. 근력 운동 중 손목 광학 심박: 정확도, 지연, 세트 시작 때의 심박 반응 (HR)

strength-set-timing 스펙(버튼을 늦게 눌러 REST로 기록된 운동 구간을 심박으로 찾기)에 필요한 근거다. **핵심 결론: 근력 세트에서 Garmin
손목 심박의 지연(초)을 잰 연구는 찾지 못했다.** 따라서 지연 상수를 문헌에서 가져올 수 없다(아래 HR-04).

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| HR-01 | 손목 PPG vs ECG/가슴 스트랩, 활동별; 근력 운동 중 여러 기기 | 평균 차이: 안정 −0.01 bpm, 트레드밀 −0.51 bpm, **저항 운동 −7.26 bpm(95% CI −10.46~−4.07)**. 저항 운동에서는 심박이 10 bpm 오를 때마다 과소 측정이 약 3 bpm 커진다. 근력 운동 타당도 연구(4종목 × 3세트 10RM, 세트 직후 판독, n=50): 운동 강도가 높을수록 모든 기기에서 과소 측정이 커졌고, 가장 나은 기기(이어폰형)의 MAPE 6.24%(타당성 기준 ≤ 10%). | MA(다층), 44편·738개 효과·15개 브랜드 + EXP(타당도) | Zhang Y, Weaver RG, Armstrong B, Burkart S, Zhang S, Beets MW. 2020. Validity of Wrist-Worn photoplethysmography devices to measure heart rate: A systematic review and meta-analysis. *J Sports Sci* 38(17):2021-2034. doi:10.1080/02640414.2020.1767348 · Boudreaux BD, Hebert EP, Hollander DB, et al. 2018. Validity of Wearable Activity Monitors during Cycling and Resistance Exercise. *Med Sci Sports Exerc* 50(3):624-633. doi:10.1249/MSS.0000000000001471 | 심박 상승 판단은 **절대값이 아니라 상대 변화(기울기, 직전 최저점 대비 상승폭)**로 한다. 세트 중 심박이 실제보다 낮게 나오므로 상승폭 기준을 크게 잡지 않는다. Garmin 기기의 저항 운동 값(Boudreaux)은 유료 본문이라 확인 못 함. |
| HR-02 | Garmin 손목 심박, 근력 운동(Polar H10 기준) 및 유산소(ECG 기준) | 데드리프트 4×6: 손목 안쪽·중고강도 **MAPE 약 28%**, 손목 바깥쪽·저강도 약 9%. 런지·프레스 슈퍼세트: 평균 심박 MAPE **36.5–81.6%**. 유산소 운동에서 ECG 일치도(rc): 가슴 스트랩 Polar H7 0.996, Apple Watch 0.92, **Garmin Forerunner 235 0.81**; 저자는 정확한 심박이 꼭 필요하면 전극형 가슴 스트랩을 쓰라고 한다. | CONF(학회 초록 2편, 각 n=21) + EXP(타당도, n=50), 확실성 낮음 | Kerwin et al. 2025. *Int J Exerc Sci Conf Proc* 14(5):63. https://digitalcommons.wku.edu/ijesab/vol14/iss5/63 · Thornton et al. 2023. *Int J Exerc Sci Conf Proc* 14(3):138. https://digitalcommons.wku.edu/ijesab/vol14/iss3/138 · Gillinov S, Etiwy M, Wang R, et al. 2017. Variable Accuracy of Wearable Heart Rate Monitors during Aerobic Exercise. *Med Sci Sports Exerc* 49(8):1697-1703. doi:10.1249/MSS.0000000000001284 | Garmin 손목 심박은 근력 운동에서 오차가 매우 클 수 있다. 추정에는 반드시 신뢰도(높음/중간/낮음)와 "추정 안 함" 경로를 둔다. 보정을 믿을 만하게 하려면 가슴 스트랩을 쓰는 방법이 있다(조언만). |
| HR-03 | 손목 PPG와 ECG/가슴 스트랩의 시간 어긋남, 활동 시작 | 예비 분석에서 ECG와 PPG 심박 신호 사이에 **0–43초의 지연**이 발견됐다. 지연은 일정하지 않았고(고정인 경우도, 변하는 경우도 있음) 원인(타임스탬프, 기기 처리, 놓친 박동, 맥파 도달 지연)은 밝혀지지 않았다. 오차 분석 전에 신호를 정렬해 제거했다. 활동 중 절대 오차는 안정 시보다 30% 컸다. 다른 연구(Fitbit Inspire 2 vs Polar H10, 2부 건강한 성인 n=10): 활동이 시작된 **첫 1분 동안** PPG 심박 상승이 자주 늦었다(초 단위 숫자 없음). | EXP 2편(n=53 / n=10) | Bent B, Goldstein BA, Kibbe WA, Dunn JP. 2020. Investigating sources of inaccuracy in wearable optical heart rate sensors. *npj Digit Med* 3:18. doi:10.1038/s41746-020-0226-6 · Vermunicht P, Buyck C, Naessens S, et al. 2025. Optimization and pre-use suitability selection for wrist photoplethysmography-based heart rate monitoring in patients with cardiac disease. *Eur Heart J Digit Health* 6(5):1024-1035. doi:10.1093/ehjdh/ztaf084 (논문 전체 주제는 심장질환자) | **지연을 상수 하나로 둘 근거가 없다.** 0–43초는 근력 운동 측정값이 아니고, 범위가 넓고 일정하지 않다. 설계 제안은 HR-04. |
| HR-04 | 운동 시작 때의 실제 심박 반응(생리) | 가벼운 자전거(50 W) 시작 시 심박이 **즉시 빠르게 오르고 약 10초 뒤 첫 정점**(미주신경 억제로 설명), 정상 상태까지 60–90초(n=6, 약물 차단 실험). 정적 손·손가락 수축에서는 **첫 심장 주기(R-R)부터** 최대 8% 짧아졌다. 다른 연구는 운동 시작 4초 뒤 심박을 지표로 쓴다. | EXP(소규모 생리 실험) | Fagraeus L, Linnarsson D. 1976. Autonomic origin of heart rate fluctuations at the onset of muscular exercise. *J Appl Physiol* 40(5):679-682. doi:10.1152/jappl.1976.40.5.679 · Secher NH. 1985. Heart rate at the onset of static exercise in man with partial neuromuscular blockade. *J Physiol* 368:481-490. doi:10.1113/jphysiol.1985.sp015870 · Zaniqueli D, Morra EA, Dantas EM, et al. 2014. Heart rate at 4 s after the onset of exercise in endurance-trained men. *Can J Physiol Pharmacol* 92(6):476-480. doi:10.1139/cjpp-2014-0042 | 실제 심박은 세트 시작 후 **수 초 안에** 오르기 시작한다(생리 지연은 작다). 그러므로 기록된 심박 상승 시점과 실제 시작의 차이는 대부분 **기기 지연**이다. `결정적 규칙 가능`(설계 제안): 지연 상수를 문헌에서 가져오지 말고, 버튼을 제때 누른 **정상 세트**(1회당 시간이 정상인 ACTIVE 세트)에서 "ACTIVE 시작 → 심박 상승 시작"의 차이를 재어 그 중앙값과 범위를 사용자·기기별 상수로 쓴다. 표본이 적으면 "not estimated". |
| HR-05 | 세트 중·세트 끝의 심박과 혈압(레그프레스·저항 운동) | 세트가 끝날 때 수축기 혈압과 **심박이 함께 오른다**(교차 n=10). 레그프레스(연속 PPG, n=7)에서 최고 심박 145 ± 20 bpm(70% 1RM), 수축기 혈압은 처음 약 20–25초 동안 12–22 mmHg 떨어졌다가 세트 끝까지 올랐다. | EXP(소규모) | Machado CLF, Bgeginski R, De Castro C, Wilhelm EN, Pinto RS. 2020. Acute Hemodynamic Responses to Repetitions to Failure Using Different Resistance Exercises and Protocols in Normotensive Men: A crossover study. *Clin Exp Hypertens* 42(5):401-408. doi:10.1080/10641963.2019.1676772 · de Sousa NM, Magosso RF, Dipp T, et al. 2014. Continuous blood pressure response at different intensities in leg press exercise. *Eur J Prev Cardiol* 21(11):1324-1331. doi:10.1177/2047487313497863 | 심박 정점은 세트 **끝 무렵이나 끝난 직후**에 온다. 세트 끝 시각(다음 버튼)을 기준점으로 쓰는 것이 시작 추정보다 안정적일 수 있다(판단). |

**충돌·적용 한계**

- 지연 크기: Bent 2020은 0–43초로 넓고 일정하지 않으며 근력 운동이 아니다. Vermunicht 2025는 "첫 1분 동안 자주 늦다"는 서술뿐이다.
- 생리 근거(HR-04)는 가벼운 자전거와 정적 손 수축에서 나온 것이고 바벨 세트가 아니다.

---

## 10. 수면과 근력 훈련·근육 (SLEEP)

2026-10-25 추가. 현재 muscle50 회복 규칙에는 수면 상수가 이미 있다(`domain/recovery_assessment.py`: 그날 밤 수면 < 5시간이면 hold,
< 4시간이면 reduce, sleep score < 50이면 hold). **아래 근거는 이 숫자들을 뒷받침하지도, 반박하지도 않는다**(SLEEP-05).

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| SLEEP-01 | 급성 수면 부족(포함 기준: 24시간 중 수면 ≤ 6시간) 뒤의 운동 수행, 대부분 남성 | 전체 수행 **−7.56%**(95% CI −11.9~−3.13), 운동 전 깨어 있던 시간 1시간당 약 −0.4%(완전 박탈·늦은 기상 제한 프로토콜). **근력**(25편, n=289): 전체 **−2.85%**(CI −4.47~−1.23), 완전 박탈 −3.00%(유의), 부분 제한 −2.77%(p=0.167, 유의하지 않음), 늦게 자기 −1.16%(p=0.102), 일찍 깨기 −4.45%(p=0.068). 아침 측정 −1.78%(p=0.017), 오후·저녁 측정 −4.58%(p=0.004). **근지구력 −9.85%**(p=0.048). 연속된 밤의 효과는 분석하지 못했다고 저자가 밝힘. | MA(다층), 69편·227개 결과·959명(남 89%) | Craven J, McCartney D, Desbrow B, et al. 2022. Effects of Acute Sleep Loss on Physical Performance: A Systematic and Meta-Analytical Review. *Sports Med* 52(11):2669-2690. doi:10.1007/s40279-022-01706-y | 조언만: "잠을 못 잔 날 최대 근력은 조금(약 3%) 떨어지고, 반복을 많이 하는 세트와 지구력은 더 떨어진다." "≤ 6시간"은 연구를 고른 기준이지 권고 기준이 아니다. |
| SLEEP-02 | 연속된 부분 수면 제한(3–5시간) 뒤의 리프팅 | 3시간 × 3밤(남성 n=8, 저녁 측정): 최대 바이셉스 컬은 그대로, 최대 벤치·레그프레스·데드리프트는 감소, 최대하(submaximal) 리프트는 **둘째 밤 뒤부터** 유의하게 나빠짐. 3시간 × 2밤(훈련자 남성 n=15, 17시): 벤치 평균 파워 −11.2%, 레그프레스 평균 파워 −5.7%, 악력 −2.7%, RPE 상승, 13시 1시간 낮잠으로 악력·벤치가 정상 수면 수준으로 회복. 5시간 × 9밤(훈련자 여성 n=10): volume load는 **< 1%** 감소에 그쳤지만 하체 다관절 종목 바 속도가 최대 15% 느려지고 세션 RPE +11%. SR(17편): 수면 박탈은 근력에 영향이 작고, 연속된 밤의 제한은 다관절(단관절 아님) 종목의 힘을 줄일 수 있다(밤 수·시간 숫자 없음). | RCT(교차) 3편 + SR(질 moderate~weak) | Reilly T, Piercy M. 1994. The effect of partial sleep deprivation on weight-lifting performance. *Ergonomics* 37(1):107-115. doi:10.1080/00140139408963628 · Brotherton EJ, Moseley SE, Langan-Evans C, et al. 2019. *Chronobiol Int* 36(3):407-426. doi:10.1080/07420528.2018.1552702 · Knowles OE, Drinkwater EJ, Roberts SSH, et al. 2022. *Med Sci Sports Exerc* 54(12):2167-2177. doi:10.1249/MSS.0000000000003000 · Knowles OE, Drinkwater EJ, Urwin CS, Lamon S, Aisbett B. 2018. Inadequate sleep and muscle strength: Implications for resistance training. *J Sci Med Sport* 21(9):959-968. doi:10.1016/j.jsams.2018.01.012 | 조언만. muscle50은 바 속도·RPE를 기록하지 않고, 저하가 volume load(무게 × 반복)에는 거의 안 보이므로 "수면 부족 뒤 반복 감소"로 수면 영향을 판정하는 규칙은 근거가 없다. "2밤"은 3시간이라는 극단적 프로토콜의 결과라 일반 기준으로 쓰지 않는다. |
| SLEEP-03 | 수면 부족과 근단백질 합성 | 하룻밤 완전 박탈(남녀 n=13, 운동 없음): 식후 근단백질 합성 **−18%**(0.072 vs 0.059 %/h, p=.040), 코르티솔 +21%, 테스토스테론 −24%, 분해 지표는 변화 없음. 4시간 × 5밤(젊은 남성 n=24, 군당 약 8명): 근원섬유 단백질 합성 1.24 vs 8시간 군 1.53 %/일(약 19% 낮음, 계산값), 같은 기간 고강도 인터벌 운동 3회를 한 4시간 군은 1.61로 유지. 수면 부족이 합성 경로를 낮추고 분해 경로를 높인다는 것은 가설 논문이 먼저 제시했다(자료 없음). | RCT(교차) + 병행군 실험(무작위 배정 여부 초록에 없음) + 가설 논문 | Lamon S, Morabito A, Arentson-Lantz E, et al. 2021. The effect of acute sleep deprivation on skeletal muscle protein synthesis and the hormonal environment. *Physiol Rep* 9(1):e14660. doi:10.14814/phy2.14660 · Saner NJ, Lee MJ, Pitchford NW, et al. 2020. *J Physiol* 598(8):1523-1536. doi:10.1113/JP278828 · Dattilo M, Antunes HK, Medeiros A, et al. 2011. Sleep and muscle recovery: endocrinological and molecular basis for a new and promising hypothesis. *Med Hypotheses* 77(2):220-222. doi:10.1016/j.mehy.2011.04.017 | 조언만. 짧고 극단적인 프로토콜이고 저항 운동을 포함하지 않았다. 습관적으로 1–2시간 덜 자는 사람(평균 약 5시간 47분)에서 16회 저항 훈련 효과가 줄지 않았다는 비무작위 연구도 있다(Borba DA, et al. 2024. *Sleep Sci* 17(3):e244-e254. doi:10.1055/s-0044-1787297, n=24). |
| SLEEP-04 | 수면 부족 + 칼로리 제한(체성분) | 과체중 성인 n=10, 14일 감량, 수면 기회 5.5 vs 8.5시간: 빠진 체중 중 **지방 비율 −55%**(0.6 vs 1.4 kg), **제지방 손실 +60%**(2.4 vs 1.5 kg, P=0.002). 8주 감량(n=36), 평일 5밤 약 57분 덜 자기(주당 순손실 169 ± 75분): 체중·제지방·지방 손실은 비슷했고, 빠진 양 중 지방 비율만 칼로리 제한 단독이 더 컸다(p=0.016). 주말 몰아 자기로 완전히 되돌리지 못할 수 있다고 저자가 봄. | RCT(교차, 소표본) + RCT(병행) | Nedeltcheva AV, Kilkus JM, Imperial J, Schoeller DA, Penev PD. 2010. Insufficient sleep undermines dietary efforts to reduce adiposity. *Ann Intern Med* 153(7):435-441. doi:10.7326/0003-4819-153-7-201010050-00006 · Wang X, Sparks JR, Bowyer KP, Youngstedt SD. 2018. *Sleep* 41(5):zsy027. doi:10.1093/sleep/zsy027 | 조언만: 감량기(MAINT-05)에는 수면을 지키는 것이 근육 보존에 중요할 수 있다. 제지방량은 근육량과 같지 않고, 두 연구의 크기가 크게 다르다. |
| SLEEP-05 | 수면 시간 권고와 "훈련을 바꿀 기준" | 성인 건강 목표: AASM/SRS 합의 **규칙적으로 ≥ 7시간/밤**(< 7시간이 지속되면 나쁜 건강 결과와 연관), NSF **7–9시간**(젊은 성인·성인). 두 권고 모두 훈련 조정은 다루지 않는다. 선수 수면 전문가 합의(Walsh 2021 BJSM, IOC 문서 아님): 7–9시간 같은 일률 기준은 이상적이지 않다고 보고 **개인화**를 권하며, 1–3밤 부분 제한이 수행에 주는 영향은 "불분명"하다고 쓴다. 훈련 조정 규칙은 없다. 수면 연장: 평소 약 7시간 자는 선수에서 **46–113분 연장**, 부분 제한 뒤 **20–90분 낮잠**이 수행 회복에 도움(SR 25편, 통합 없음; 다른 SR 10편·218명도 연장이 가장 유익). | GL/합의 2개(RAND 방법) + 전문가 합의 + SR 2편 | Watson NF, et al. 2015. Recommended Amount of Sleep for a Healthy Adult: A Joint Consensus Statement of the American Academy of Sleep Medicine and Sleep Research Society. *Sleep* 38(6):843-844. doi:10.5665/sleep.4716 (*J Clin Sleep Med* 11(6):591-592, doi:10.5664/jcsm.4758) · Hirshkowitz M, et al. 2015. National Sleep Foundation's sleep time duration recommendations. *Sleep Health* 1(1):40-43. doi:10.1016/j.sleh.2014.12.010 · Walsh NP, Halson SL, Sargent C, et al. 2021. Sleep and the athlete: narrative review and 2021 expert consensus recommendations. *Br J Sports Med* 55(7):356-368. doi:10.1136/bjsports-2020-102025 · Cunha LA, Costa JA, Marques EA, et al. 2023. *Sports Med Open* 9(1):58. doi:10.1186/s40798-023-00599-z · Bonnar D, Bartel K, Kakoschke N, Lang C. 2018. *Sports Med* 48(3):683-703. doi:10.1007/s40279-017-0832-x | **근거가 주는 숫자는 건강 목표 ≥ 7시간뿐이다.** `결정적 규칙 가능`(표시용): 수면이 7시간 미만인 밤 수를 보여 주는 것. **훈련을 바꾸는 기준(몇 시간 미만, 몇 밤)은 근거가 없다** → 현재 상수(< 5시간 hold, < 4시간 reduce, score < 50)는 근거 규칙이 아니라 **설계 선택**으로 문서에 표시하고, 바꾸려면 사용자 설정으로 둔다. |

**충돌**

- 수면 박탈과 최대 근력: Knowles 2018 SR은 "영향 작음", Craven 2022 MA는 완전 박탈에서 −3.00%(유의)·부분 제한은 유의하지 않음, Reilly & Piercy는 3밤 뒤
  최대 다관절 리프트 감소.
- 측정 시각: Craven은 오후·저녁 측정에서 저하가 더 컸고(−4.58% vs 아침 −1.78%), Walsh 2021은 저녁 측정(17–19시)이 영향을 줄일 수 있다고 쓴다(서로 반대 방향).
- 감량기 제지방: Nedeltcheva(5.5시간, 14일, n=10)는 제지방 손실 +60%, Wang(약 1시간 덜, 8주, n=36)은 제지방 손실이 비슷했다.
- 근단백질 합성 감소(Lamon, Saner: 짧고 극단적, 저항 운동 없음) vs 습관적 단시간 수면자에서 훈련 효과 유지(Borba 2024, 비무작위).

---

## 11. 동시 훈련(유산소 + 근력) 간섭 (CONC)

2026-10-25 추가. 사용자는 달리기와 수영을 함께 한다. 현재 muscle50 추천은 **수영 간섭만** 다루고(`SWIM_OVERLAP_MUSCLES`, 강한 수영 뒤 어깨·광배
set 감소) **달리기는 고려하지 않는다**.

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| CONC-01 | 같은 근력 프로그램에 유산소를 더한 경우 vs 근력만, 건강한 성인, ≥ 4주 | **근비대 SMD −0.01**(95% CI −0.16~0.18, 15편), **최대 근력 −0.06**(−0.20~0.09, 37편): 간섭 없음. **폭발적 근력 −0.28**(−0.48~−0.08, 18편)만 작게 불리, 이상치 1편을 빼면 −0.25(−0.50~0.01, p=0.059)로 유의하지 않음. 달리기 vs 자전거, 주 5회 이상 vs 미만, 비훈련 vs 활동적, 40세 기준 나이는 조절 효과 없음. 근섬유 단위 MA(15편): 전체 근섬유 비대 SMD −0.23(−0.46~−0.00, p=0.050), **달리기일 때 1형 섬유 −0.81**(−1.26~−0.36), 자전거는 아님. | MA 2편(43편 / 15편), 질 PEDro | Schumann M, Feuerbacher JF, Sünkeler M, et al. 2022. Compatibility of Concurrent Aerobic and Strength Training for Skeletal Muscle Size and Function: An Updated Systematic Review and Meta-Analysis. *Sports Med* 52(3):601-612. doi:10.1007/s40279-021-01587-7 · Lundberg TR, Feuerbacher JF, Sünkeler M, Schumann M. 2022. The Effects of Concurrent Aerobic and Strength Training on Muscle Fiber Hypertrophy: A Systematic Review and Meta-Analysis. *Sports Med* 52(10):2391-2403. doi:10.1007/s40279-022-01688-x | 조언 근거: "달리기·수영을 병행해도 근육 크기와 최대 근력 증가는 대체로 줄지 않는다." 근비대 목표에서 유산소를 줄이라는 결정적 규칙은 근거가 없다. |
| CONC-02 | 이전 메타분석(2012), 유산소 종류·양 | 군 내 전후 효과 크기: 근비대 근력만 1.23 / 동시 0.85, 근력 1.76 / 1.44, 파워 0.91 / 0.55(차이 약 0.3–0.4는 이 문서의 뺄셈, 원문 보고값 아님, CI 없음). **달리기와 함께할 때는 근비대·근력이 유의하게 줄었지만 자전거는 아니었다.** 유산소 **빈도(r −0.26~−0.35)와 시간(r −0.29~−0.75)**이 늘수록 간섭이 컸다. | MA, 21편·422개 효과 크기 | Wilson JM, Marin PJ, Rhea MR, Wilson SM, Loenneke JP, Anderson JC. 2012. Concurrent training: a meta-analysis examining interference of aerobic and resistance exercises. *J Strength Cond Res* 26(8):2293-2307. doi:10.1519/JSC.0b013e31823a3e2d | 조언만: "다리 운동 주간에는 달리기 횟수와 시간을 늘리지 않는다." 숫자 기준(분, 횟수)은 없다. |
| CONC-03 | 훈련 상태별 하체 1RM, 같은 세션 vs 다른 세션 | 하체 1RM(27편): **훈련자 ES −0.35**(−0.59~−0.11), 중간 훈련자 −0.20(−0.42~0.02), 비훈련자 0.03(−0.29~0.35), 모든 군 I²=0. 훈련자에서 **같은 세션(< 20분 간격) −0.66**(−1.08~−0.25) vs **다른 세션(> 2시간) −0.10**(−0.43~0.23, p=0.55). | MA, 27편 | Petré H, Hemmingsson E, Rosdahl H, Psilander N. 2021. Development of Maximal Dynamic Strength During Concurrent Resistance and Endurance Training in Untrained, Moderately Trained, and Trained Individuals: A Systematic Review and Meta-analysis. *Sports Med* 51(5):991-1010. doi:10.1007/s40279-021-01426-9 | 사용자는 훈련 경험자라 이 결과(간섭은 주로 같은 세션에서)가 가장 직접 해당한다. CONC-04와 함께 쓴다. |
| CONC-04 | 유산소와 근력 사이 간격 | 장기: 같은 세션(≤ 20분)에서 폭발적 근력 SMD −0.31(−0.62~−0.01), **≥ 3시간 떨어진 세션은 유의한 효과 없음**(Schumann 2022). 럭비 선수 7주 RCT(n=58, 근력 먼저): 0시간 간격이 6·24시간보다 벤치·하프 스쿼트 증가가 작았고, 저자는 **6시간 미만 간격을 피하라**고 권함(magnitude-based inference, 숫자 효과 크기 없음). 급성: 유산소 **4·8시간 뒤** 레그프레스 반복 수가 줄었고 **24시간 뒤** 회복, 벤치프레스는 영향 없음(유산소에 쓴 근육에만 국한), 인터벌·지속 유산소 차이 없음(남성 n=16). | MA 하위분석 + RCT + EXP(교차) | Schumann 2022(CONC-01) · Robineau J, Babault N, Piscione J, Lacome M, Bigard AX. 2016. Specific Training Effects of Concurrent Aerobic and Strength Exercises Depend on Recovery Duration. *J Strength Cond Res* 30(3):672-683. doi:10.1519/JSC.0000000000000798 · Sporer BC, Wenger HA. 2003. Effects of aerobic exercise on strength performance following various periods of recovery. *J Strength Cond Res* 17(4):638-644. doi:10.1519/1533-4287(2003)017<0638:eoaeos>2.0.co;2 | `결정적 규칙 가능`(간격 상수는 설계 선택): 같은 날 달리기와 하체 근력의 시작 시각 차이가 **< 3시간**이면 "간섭 가능, 근력 먼저 또는 간격 벌리기" 안내(3시간은 Schumann, 2시간은 Petré, 6시간은 Robineau로 출처마다 다르다). 하체 근력 **8시간 이내 전**에 달리기를 했다면 "반복 수가 평소보다 적을 수 있음"을 알리고 반복 감소를 증량 실패로 세지 않는 규칙도 가능(Sporer, 급성 근거). Garmin 활동 시작 시각이 있어 계산할 수 있다. |
| CONC-05 | 같은 세션 안의 순서 | **근력 먼저**가 유산소 먼저보다 하체 동적 근력 **+6.91%**(95% CI 1.96–11.87, p=0.006, 10편), 하체 근비대는 1.15%(−1.56~3.87)로 차이 없음, 정적 근력 차이 없음. 다른 MA: 하체 1RM **+3.96 kg**(0.81–7.10), VO2max는 순서 차이 없음. | MA 2편 | Eddens L, van Someren K, Howatson G. 2018. The Role of Intra-Session Exercise Sequence in the Interference Effect: A Systematic Review with Meta-Analysis. *Sports Med* 48(1):177-188. doi:10.1007/s40279-017-0784-1 · Murlasits Z, Kneffel Z, Thalib L. 2018. The physiological effects of concurrent strength and endurance training sequence: A systematic review and meta-analysis. *J Sports Sci* 36(11):1212-1219. doi:10.1080/02640414.2017.1364405 | `결정적 규칙 가능`: 같은 세션(또는 CONC-04의 짧은 간격)이면 "근력 먼저" 안내. 근비대에는 순서 효과가 없으므로 강한 경고는 아님. |
| CONC-06 | 유산소 강도(쉬운 달리기 vs 인터벌)와 종류(수영 포함) | 강도 차이를 지지하는 유의한 검정이 없다: 중간 훈련자에서 HIIT와 지속 훈련의 하체 1RM 효과 차이 없음(Petré 2021), 고도 훈련자 6주 RCT에서 스쿼트 +12 ± 8%(지속) vs +14 ± 10%(HIIT)로 같음(n=16), 급성 MA(훈련자 남성 15편)에서 저강도 SMD 0.65 vs 중·고강도 0.65(하위군 차이 p=0.979), **30분 초과 1.02 vs 30분 이하 0.59**(p=0.204), 자전거 0.79 vs 달리기 0.28(p<0.0001). HIIT + 근력 vs 근력만: 하체 근력 ES −0.248(p=0.049), 근비대·상체 근력은 비슷. **수영**을 동시 훈련 유산소로 쓴 사람 대상 정량 자료는 찾지 못했다(서술 리뷰만: 회복 간격이 결과를 좌우할 수 있음). | MA 3편 + RCT + NR | Petré 2021(CONC-03) · Petré H, Löfving P, Psilander N. 2018. The Effect of Two Different Concurrent Training Programs on Strength and Power Gains in Highly-Trained Individuals. *J Sports Sci Med* 17(2):167-173. PMID 29769816(DOI 확인 못 함) · Markov A, Chaabene H, Hauser L, et al. 2022. Acute Effects of Aerobic Exercise on Muscle Strength and Power in Trained Male Individuals: A Systematic Review with Meta-analysis. *Sports Med* 52(6):1385-1398. doi:10.1007/s40279-021-01615-6 · Sabag A, Najafi A, Michael S, et al. 2018. The compatibility of concurrent high intensity interval training and resistance training for muscular strength and hypertrophy: a systematic review and meta-analysis. *J Sports Sci* 36(21):2472-2483. doi:10.1080/02640414.2018.1464636 · Arsoniadis G, Botonis P, Bogdanis GC, Terzis G, Toubekis A. 2022. *Sports (Basel)* 10(3):29. doi:10.3390/sports10030029 | **"다리 운동 전후 달리기는 쉽게"라는 강도 규칙은 근거가 없다** → 조언만 또는 사용자 설정. 근거가 조금이라도 지지하는 쪽은 강도보다 **양**이다: "다리 운동 전후 달리기는 짧게(예: 30분 이하는 출처의 비교 구간일 뿐 기준 아님)". 현재 수영 간섭 규칙(강한 수영 뒤 어깨·광배 set 감소)은 문헌 숫자가 아니라 사용자 데이터로 맞춘 설계 선택이다. |

**충돌**

- 종류: 장기 자료(Wilson 2012, Lundberg 2022 1형 섬유)는 **달리기**가 더 불리, 급성 자료(Markov 2022: 자전거 0.79 vs 달리기 0.28)와 HIIT MA의 경향(자전거 −0.377 vs
  달리기 −0.176, 모두 유의하지 않음)은 **자전거**가 더 불리, Schumann 2022는 종류 효과 없음.
- 크기: Wilson 2012의 군 내 차이(약 0.3–0.4)는 의미 있어 보이지만, Schumann 2022는 근비대·최대 근력에서 간섭을 찾지 못했고, Petré 2021은 훈련자에서만 찾았다.
- 강도: 서술 리뷰(Methenitis S. 2018. *Sports (Basel)* 6(4):127. doi:10.3390/sports6040127)는 짧은 HIIT·SIT가 간섭을 줄인다고, Markov 2022의 결론은 강도가 높을수록
  나쁘다고 쓰지만 어느 쪽도 유의한 검정으로 뒷받침되지 않는다. 분자 수준 간섭은 사람 급성 연구에서 관찰되지 않았다는 리뷰도 있다(Fyfe JJ, Bishop DJ, Stepto NK. 2014.
  *Sports Med* 44(6):743-762. doi:10.1007/s40279-014-0162-1).
- 간격 기준: Schumann ≥ 3시간(vs ≤ 20분), Petré > 2시간(vs < 20분), Robineau 6·24시간(vs 0시간), Sporer 8시간까지 반복 감소·24시간 회복. 하나의 숫자로 합치지 않는다.

---

## 12. 볼륨을 줄였을 때·칼로리 결핍 중의 근육과 근력 유지 (MAINT)

2026-10-25 추가. 감량기 단백질과 결핍 크기는 6절(PRO-04, PRO-05)에도 있다.

| ID | 조건 | 규칙(숫자 범위) | 근거 강도 | 출처 | muscle50 적용 메모 |
|---|---|---|---|---|---|
| MAINT-01 | 유지 용량, 에너지 균형, **젊은 성인**(20–35세)과 노인 | 16주 훈련(주 3회) 뒤 32주 유지: 원래 용량의 **1/3과 1/9 모두 젊은 성인에서 근비대를 유지**했고(노인은 유지 못 함), 1/3 용량은 젊은 성인에서 근섬유를 더 키웠다. 근력은 훈련을 완전히 멈춘 군에서도 대부분 유지(마지막 시점에 약간 감소). 1/9 용량은 다리 3종목 **각 1세트, 주 1회**(약 주당 다리 3세트; 2차 출처 Iversen 2021의 설명과 이 문서의 계산). 리뷰 결론: 젊은 성인은 **주 1회·종목당 1세트**로 근력과 근육 크기를 **최대 32주** 유지할 수 있다, **상대 강도(부하)를 유지하는 한**. 노인은 근육 크기 유지에 주 2회·종목당 2–3세트가 필요할 수 있다. | RCT(n=70, 이전 비훈련자) + NR(유지 용량 리뷰, 등급 없음) | Bickel CS, Cross JM, Bamman MM. 2011. Exercise dosing to retain resistance training adaptations in young and older adults. *Med Sci Sports Exerc* 43(7):1177-1187. doi:10.1249/MSS.0b013e318207c15d · Spiering BA, Mujika I, Sharp MA, Foulis SA. 2021. Maintaining Physical Performance: The Minimal Dose of Exercise Needed to Preserve Endurance and Strength Over Time. *J Strength Cond Res* 35(5):1449-1458. doi:10.1519/JSC.0000000000003964 | `결정적 규칙 가능`(바쁜 주·여행 같은 "유지 모드"의 하한): 근육군별 **주 1회, 종목당 ≥ 1세트, 평소 무게 유지**. 단 사용자 목표는 근육 증가이므로 기본 추천이 아니라 하한 안내로만 쓴다. Spiering의 32주는 Bickel 2단계와 같은 근거일 가능성이 높아 두 출처를 독립 확인으로 세지 않는다. |
| MAINT-02 | 유지에서 무엇을 지킬지(강도 vs 볼륨·빈도) | 유지에는 **운동 강도가 핵심 변수**(Spiering 2021). 중년·노인 MA(RCT 15편, n=383): 훈련 기간 < 24주이고 중단 기간 ≤ 훈련 기간이면 **고강도 군만** 근력 이득을 유지, 중단 기간이 훈련 기간보다 길면 고강도여도 유지 못 함. | NR + MA | Spiering 2021(MAINT-01) · Yang Y, Chen SC, Chen CN, et al. 2022. Training Session and Detraining Duration Affect Lower Limb Muscle Strength Maintenance in Middle-Aged and Older Adults: A Systematic Review and Meta-Analysis. *J Aging Phys Act* 30(3):552-566. doi:10.1123/japa.2020-0493 | `결정적 규칙 가능`: 세트를 줄이는 추천(회복 hold/reduce, 수영 간섭)에서는 **무게를 낮추지 않고 세트 수를 줄인다**는 원칙. 현재 reduce 규칙(증량 없이 무게 유지, 종목당 1 set 감소, 최소 2 set, `docs/training-recommendation.md`)은 이 방향과 맞다. |
| MAINT-03 | 시간이 부족할 때의 최소 유효량, 완전 중단 | 근육 증가를 위한 최소: 근육군당 **주 ≥ 4세트, 6–15RM**(실패까지 하면 15–40회도 가능), 더 키우려면 **≥ 10세트**. 주당 volume이 빈도보다 중요. 젊은 성인은 주 1회 짧은 세션으로 유지 가능할 것. 완전히 멈추면 얻은 근육은 **짧게(< 3주)** 유지된다(1차 연구 인용). | NR(시간 효율 리뷰) | Iversen VM, Norum M, Schoenfeld BJ, Fimland MS. 2021. No Time to Lift? Designing Time-Efficient Training Programs for Strength and Hypertrophy: A Narrative Review. *Sports Med* 51(10):2079-2095. doi:10.1007/s40279-021-01490-1 | VOL-03(최소 유효량 약 4 fractional set)과 같은 값. "주당 < 4 set이면 부족" 표시의 보강 근거. "< 3주"는 1차 연구를 직접 읽지 않았으므로 조언만. |
| MAINT-04 | 훈련 중단(detraining)의 크기 | 중단 시 최대하 근력 SMD −0.62(−0.80~−0.45), 최대 힘 −0.46(−0.54~−0.37), 최대 파워 −0.20(−0.28~−0.13), **중단 기간이 길수록 더 큼**(용량-반응), 65세 초과·비활동자에서 더 큼(103편). 노인 근육 크기(6편): 12–24주 중단 d −0.60(−1.21~0.01, 유의하지 않음), 31–52주 −1.11(−1.75~−0.47). | MA 2편 | Bosquet L, Berryman N, Dupuy O, et al. 2013. Effect of training cessation on muscular performance: a meta-analysis. *Scand J Med Sci Sports* 23(3):e140-e149. doi:10.1111/sms.12047 · Grgic J. 2022. Use It or Lose It? A Meta-Analysis on the Effects of Resistance Training Cessation (Detraining) on Muscle Size in Older Adults. *Int J Environ Res Public Health* 19(21):14048. doi:10.3390/ijerph192114048 | 조언만: "쉬는 기간이 길수록 근력이 더 빠지지만 몇 주 쉬는 것은 큰 손실이 아니다." 며칠·몇 주 기준 숫자는 이 MA 초록에 없다. |
| MAINT-05 | 칼로리 제한 중 근력 훈련(제지방 보존)과 감량 속도 | 결핍은 제지방 증가를 막지만 근력은 아니다(약 500 kcal/일 결핍에서 제지방 증가 사라짐, PRO-04). 비만 노인 감량 중 저항 훈련(주 3회, 12–24주)은 감량으로 인한 제지방 손실의 **93.5%를 막았다**(0.819 kg, 0.364–1.273; RCT 6편), 지방 감소는 식단 단독과 비슷. 엘리트 선수(n=24, 모두 주 4회 근력 훈련): 목표 주당 0.7% 감량 군은 **제지방 +2.1%**, 목표 1.4%(실제 약 1.0%/주) 군은 −0.2%로 변화 없음 → 저자 권고 **주 0.7%**. 보디빌딩 리뷰: 주당 체중의 **0.5–1%**. 감량은 근육량을 줄이지만 근력은 대체로 유지(비만 대상 서술 리뷰). | MA + RCT + NR 2편 | Murphy & Koehler 2022(PRO-04) · Sardeli AV, Komatsu TR, Mori MA, Gáspari AF, Chacon-Mikahil MPT. 2018. Resistance Training Prevents Muscle Loss Induced by Caloric Restriction in Obese Elderly Individuals: A Systematic Review and Meta-Analysis. *Nutrients* 10(4):423. doi:10.3390/nu10040423 · Garthe I, Raastad T, Refsnes PE, Koivisto A, Sundgot-Borgen J. 2011. Effect of two different weight-loss rates on body composition and strength and power-related performance in elite athletes. *Int J Sport Nutr Exerc Metab* 21(2):97-104. doi:10.1123/ijsnem.21.2.97 · Helms, Aragon, Fitschen 2014(PRO-05) · Cava E, Yeat NC, Mittendorfer B. 2017. Preserving Healthy Muscle during Weight Loss. *Adv Nutr* 8(3):511-519. doi:10.3945/an.116.014506 | `결정적 규칙 가능`(표시용): InBody 두 측정 사이의 주당 체중 변화율을 계산해 **> 1%/주 감소**면 "근육 보존에 불리할 수 있는 속도" 표시, 0.5–1%는 권장 범위(매일 체중 없음, InBody 2–4주 간격 기준). 감량 권고 폭은 −500 kcal/일보다 작게(PRO-04). |
| MAINT-06 | 감량기의 근력 훈련 처방(볼륨·빈도·반복) | 훈련자 감량기 SR(15편): 근육군당 **주 ≥ 10세트** 프로그램에서 제지방 손실이 적거나 없었고(대부분 여성), 볼륨을 늘린 연구가 줄인 연구보다 손실이 적어 보였지만, 볼륨을 계산할 수 있었던 연구가 4편뿐이라 **결론 내리기 부족**(평균 단백질 남 3.06, 여 3.35 g/kg 제지방). 훈련자 남성 RCT(n=38, 6주, 30 kcal/kg, 단백질 2.8 g/kg 제지방): **종목당 5세트 vs 3세트 차이 없음**(제지방 −0.51 ± 2.30 vs −0.92 ± 1.59 kg, p=0.966). 보디빌딩 훈련 리뷰: 근육군 **주 ≥ 2회**, 대부분 **6–12회·70–80% 1RM**, 세션당 근육군 약 40–70회, 유산소는 지방 감소에 필요한 최소 빈도·시간. 감량기 단백질 **2.3–3.1 g/kg 제지방**, 결핍이 크고 마를수록 위쪽(SR 6편). | SR + RCT + NR + SR | Roth C, Schoenfeld BJ, Behringer M. 2022. Lean mass sparing in resistance-trained athletes during caloric restriction: the role of resistance training volume. *Eur J Appl Physiol* 122(5):1129-1151. doi:10.1007/s00421-022-04896-5 · Roth C, Schwiete C, Happ K, et al. 2023. Resistance training volume does not influence lean mass preservation during energy restriction in trained males. *Scand J Med Sci Sports* 33(1):20-35. doi:10.1111/sms.14237 · Helms ER, Fitschen PJ, Aragon AA, Cronin J, Schoenfeld BJ. 2015. Recommendations for natural bodybuilding contest preparation: resistance and cardiovascular training. *J Sports Med Phys Fitness* 55(3):164-178. PMID 24998610(DOI 없음) · Helms ER, Zinn C, Rowlands DS, Brown SR. 2014. A systematic review of dietary protein during caloric restriction in resistance trained lean athletes: a case for higher intakes. *Int J Sport Nutr Exerc Metab* 24(2):127-138. doi:10.1123/ijsnem.2013-0054 | 조언만(또는 사용자 설정): "감량기에도 무게와 평소 세트 수(근육군당 주 약 10세트 이상)를 유지하고 세트를 줄이지 않는다." 3 → 5세트 증가는 이득이 없었으므로 감량기에 세트를 늘리는 결정적 규칙은 근거가 없다. 감량기 여부를 muscle50이 알 수 없으므로(체중 매일 없음, 목표 kcal만 있음) 자동 전환하지 않는다. |

**충돌**

- 유지 연구(MAINT-01–03)는 **에너지 균형**에서 한 것이고, 감량기 연구(MAINT-05–06)는 훨씬 많은 훈련(주 3–4회, 종목당 3–5세트, 근육군 주 2회 이상)을 썼다.
  "주 1회 1세트로 유지"를 감량기에 그대로 옮기지 않는다.
- 근력 유지와 중단: Bickel은 완전 중단에서도 근력이 32주 동안 대부분 남았다고, Bosquet은 중단 기간에 비례해 근력이 줄었다고 보고했다. 노인 근육 크기는 Grgic에서
  12–24주 중단에 유의한 감소가 없었지만(넓은 CI) Bickel에서는 유지 훈련을 해도 줄었다.
- 감량기 볼륨: Roth 2022 SR은 ≥ 10세트·볼륨 증가 쪽을 시사하지만(근거 4편, 주로 여성), Roth 2023 RCT(남성)는 5세트가 3세트보다 낫지 않았고 두 군 모두 제지방이 줄었다.
- 감량 속도: Garthe의 빠른 군은 목표 1.4%/주에 못 미친 약 1.0%/주였으므로 "제지방 증가 없음"은 Helms 범위(0.5–1%)의 위쪽 끝에서 나온 결과다.
- 감량기 단백질: 마른 선수 대상 2.3–3.1 g/kg 제지방(Helms) vs 비만 대상 "충분하되 과하지 않게"(Cava).

---

## 확인 못 한 것

아래는 원문(초록 또는 본문)에서 숫자를 확인하지 못해 표에 넣지 않았거나, 표의 수치에 남은 불확실성이다.

1. **Pelland 정식판(Sports Med 2026)의 세부 수치**: 정식판 본문을 읽지 못했다. VOL-03, FREQ-02의 기울기·구간은 2024-09 preprint 값이다.
   검색 요약에 보인 "근비대 약 31 fractional set, 근력 약 3 set 이후 이득 없음"은 다른 preprint(회당 volume) 내용이며 확인하지 못했다.
2. **Robinson 2024 정식판의 기울기와 연구 수**: preprint 값(근비대 26편, 근력 55편)만 확인. 검색 요약의 다른 연구 수(55/67)는 확인 못 함.
3. **Schoenfeld 2016(휴식)의 효과 크기와 최종 표본 수**: 초록에 없음, 본문 미확인.
4. **Schoenfeld 2017(volume)에서 훈련자 연구가 2편뿐이라는 주장**: 검색 요약만.
5. **Murphy & Koehler 2022의 포함 연구 수**: 초록에 없음.
6. **Nunes 2022의 "약 1.5 g/kg"**: 초록·본문에서 찾지 못함. Nunes 초록의 하체 근력 CI는 오탈자로 보여 본문 표(0.40, 0.23–0.57)를 기준으로 했다(표에는 근력 수치를 넣지 않음).
7. **ISSN/ACSM의 감량기 단백질을 제지방량 기준으로 낸 별도 권고**: 확인 못 함.
8. **compound vs isolation 휴식을 직접 비교한 장기 근비대 RCT**, **2023–2026년의 장기 휴식 RCT**, **자율 휴식 SR**, **NSCA 휴식 권고 원문**, **증량 방식 비교 메타분석**: 찾지 못했다.
9. **Hammert의 하체 휴식 RCT**: 찾지 못함.
10. **KSoLA 2022의 식이 콜레스테롤 < 300 mg/일**: 요약본에 숫자 없음. KSoLA 5판의 학술지 게재본·DOI, 권고 등급, 치료 전략 표 각 칸의 내용도 확인 못 함. 2024–2025 KSoLA 지침 개정은 찾지 못함.
11. **ESC/EAS 2019·2025 권고 등급(Class/Level)**과 **트랜스지방 "< 1% 에너지"**: 확인 못 함.
12. **AHA의 포화지방 < 5–6% 권고**(2013 생활습관 지침 계열): heart.org 접근 실패로 확인 못 함.
13. **Mensink 2016 WHO 보고서 원문**: 접근 실패, LDL-06은 재인용 수치(다중불포화 행은 표 열이 섞여 있어 "아마도"로 읽었다).
14. **Dattilo & Kris-Etherton 1992의 kg당 LDL 감소(약 0.8 mg/dL)**: 초록에 LDL 기울기가 없다. kg당 수치는 ESC·ACC/AHA 2026 값만 썼다.
15. **2018 AHA/ACC 지침의 개별 권고 등급**(예: 20–39세 가족력 + LDL ≥ 160에서 스타틴 고려): 확인 못 함. 2026 ACC/AHA 지침의 정확한 발표일(검색 요약상 2026-03-13)도 확인 못 함.
16. **근력 세트에서 Garmin 손목 심박의 초 단위 지연**: 연구를 찾지 못했다. Boudreaux 2018의 Garmin Vivosmart HR 저항 운동 MAPE(유료 본문)도 확인 못 함.
17. **세트 안에서 마지막 반복에 심박이 정점이라는 박동 단위 자료**: 찾지 못했다(세트 끝 상승, 강도별 최고치만 확인).
18. **Smart 2025의 운동 종류별 LDL 수치**(유산소·저항·병행 각각): 본문 문장만 있고 숫자는 확인 못 함. 일반 성인 대상 유산소 단독 LDL 메타분석 수치도 확인 못 함(당뇨 대상 Kelley 2007 약 −5%만 확인).
19. **꾸준히 훈련하는 사람에서 운동 후 AST/ALT 상승의 크기·기간**(반복 운동 적응): Pettersson은 웨이트 비숙련자 대상이며, 훈련자 자료는 찾지 않았다/확인 못 함. 달리기·수영 같은 지구성 운동 후 간 수치 변화도 확인하지 않았다.
20. **한국의 음주 권고(보건복지부·국가암정보센터 등)**, **EASL 2024 전문의 MetALD 음주 기준**, **WHO 성명의 Lancet Public Health DOI**: 확인 못 함.
21. **CDC 음주 페이지와 Vermunicht 2025, Bent 2020의 일부 MAE 수치**: 웹 추출기 결과로만 읽었고 원문 텍스트로 재확인하지 못했다.
22. **수면**: Gwyther 2022(Psychol Sport Exerc) 수면 중재 메타분석, Knowles 2018 SR 안의 세부 결과(하룻밤 제한이 세션 총 부하를 줄이고 카페인이 회복시켰다는 내용)는 검색
    요약으로만 봤다. IOC 자체의 선수 수면 합의문은 찾지 못했다(Walsh 2021은 IOC 문서가 아님). AASM/SRS 권고 문장은 웹 추출기를 통해 읽었다(원문 텍스트 재확인 못 함).
23. **수면으로 훈련을 바꾸는 근거 기준**("Y시간 미만이 X밤이면 부하를 줄인다"): 지침·합의·메타분석 어디에서도 찾지 못했다. 현재 muscle50의 < 5시간·< 4시간·score < 50
    상수에 해당하는 문헌 근거도 없다.
24. **동시 훈련**: Wilson 2012 본문 안의 달리기·자전거별 효과 크기(유료 본문), Sabag 2018과 Murlasits 2018의 포함 연구 수·참가자 수, "쉬운 달리기"의 숫자 기준(심박 구간,
    %HRmax), 수영을 유산소로 쓴 사람 대상 정량 자료, Petré 2018(J Sports Sci Med)의 DOI는 확인 못 함.
25. **유지·감량기**: Bickel 2011의 정확한 세트·일수(본문 유료, Iversen 2021의 설명을 2차로 사용), Bosquet 2013의 "약 3주까지 근력 유지"(초록에 없음), Spiering 2021의 근거
    표(본문 유료), Iversen 2021이 인용한 "주 1회 3–4세트로 근력 유지" 1차 연구, Weinheimer 2010(Nutr Rev), Encarnação 2024 detraining 메타분석은 읽지 못했다.
    Helms 2015(J Sports Med Phys Fitness)는 DOI가 없어 PubMed 기록으로만 확인했다.
