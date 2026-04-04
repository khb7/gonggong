

```markdown
# [cite_start]조달청 공공데이터 개방 OpenAPI 참고자료 [cite: 1, 2]

## [cite_start]목 차 [cite: 3, 4]
1. [cite_start]서비스 명세 [cite: 5]
   [cite_start]1.1 나라장터 공공데이터개방표준서비스 [cite: 6]
      가. [cite_start]서비스 개요 [cite: 7]
      나. [cite_start]오퍼레이션 목록 [cite: 8]

---

## [cite_start]개정 이력 [cite: 9]

| 버전 | 변경일 | 변경 구분 | 변경사유 |
|:---:|:---:|:---|:---|
| 1.0 | 2025 | 최초 개정 | [cite_start]최초 개정 [cite: 10] |
| 1.1 | 2025.08 | 항목추가 | [cite_start]데이터셋 개방표준에 따른 계약정보, 요청메시지 : [기관구분코드:insttDivCd , 기관코드:insttCd] 항목 추가 [cite: 10] |

---

## [cite_start]1. 서비스 명세 [cite: 11]

### [cite_start]1.1 나라장터 공공데이터개방표준서비스 [cite: 12]

#### 가. [cite_start]서비스 개요 [cite: 13]

| 구분 | 항목 | 내용 | 기타 |
|---|---|---|---|
| **서비스 정보** | 서비스 ID | [cite_start]PubDataOpnStdService | [cite: 14] |
| | 서비스명(국문) | [cite_start]나라장터 공공데이터개방표준서비스 | [cite: 14] |
| | 서비스명(영문) | [cite_start]PubDataOpnStdService | [cite: 14] |
| | 서비스 설명 | [cite_start]나라장터 입찰, 낙찰, 계약정보 데이터를 행안부 고시 공공데이터 개방표준에 따라 제공하는 공공데이터개방표준서비스 | [cite: 14] |
| **서비스 보안** | 서비스 인증/권한 | [O] 서비스 Key, [ ] 인증서 (GPKI) | [cite_start][ ] Basic (ID/PW), [ ] 없음, [ ] WS-Security [cite: 14] |
| | 메시지 레벨 암호화 | [cite_start][ ] 전자서명, [ ] 암호화, [O] 없음 | [cite: 14] |
| | 전송 레벨 암호화 | [cite_start][ ] SSL, [O] 없음 | [cite: 14] |
| **적용 기술 수준** | 인터페이스 표준 | [O] REST (GET) | [cite_start][ ] SOAP 1.2 (RPC-Encoded, Document Literal, Document Literal Wrapped), [ ] RSS 1.0, [ ] RSS 2.0, [ ] Atom 1.0, [ ] 기타 [cite: 14] |
| | 교환 데이터 표준 | [cite_start][O] XML, [O] JSON, [ ] MIME, [ ] MTOM | [cite: 14] |
| **서비스 URL** | [cite_start]개발환경 | http://apis.data.go.kr/1230000/ao/PubDataOpnStdService | [cite: 14] |
| | [cite_start]운영환경 | http://apis.data.go.kr/1230000/ao/PubDataOpnStdService | [cite: 14] |
| **서비스 WADL** | 개발환경 | [cite_start]N/A | [cite: 14] |
| | 운영환경 | [cite_start]N/A | [cite: 14] |
| **서비스 배포 정보** | 서비스 버전 | [cite_start]1.0 | [cite: 14] |
| | 서비스 시작일 | 2025-01-06 | [cite_start]배포 일자: 2025-01-06 [cite: 14] |
| | 서비스 이력 | [cite_start]N/A | [cite: 14] |
| **메시지 교환 유형** | | [O] Request-Response, [ ] Publish-Subscribe | [cite_start][ ] Fire-and-Forgot, [ ] Notification [cite: 14] |
| **메시지 로깅 수준** | 성공 | [cite_start][O] Header, [ ] Body | [cite: 14] |
| | 실패 | [cite_start][O] Header, [O] Body | [cite: 14] |
| **사용 제약 사항** | 비고 | [cite_start]N/A | [cite: 14] |
| **서비스 제공자** | | [cite_start]김재혁 / 조달청 전자조달기획과 / 042-724-7677 / dobin@korea.kr | [cite: 14] |
| **데이터 갱신주기**| | [cite_start]수시 | [cite: 14] |

#### 나. [cite_start]오퍼레이션 목록 [cite: 15]

| 일련번호 | 서비스명(국문) | 오퍼레이션명(영문) | 오퍼레이션명(국문) | 메시지명(영문) |
|:---:|---|---|---|---|
| 1 | 나라장터 공공데이터개방표준서비스 | `getDataSetOpnStdBidPblancInfo` | 데이터셋 개방표준에 따른 입찰공고정보 | [cite_start]N/A [cite: 16] |
| 2 | | `getDataSetOpnStdScsbidInfo` | 데이터셋 개방표준에 따른 낙찰정보 | [cite_start]N/A [cite: 16] |
| 3 | | `getDataSetOpnStdCntrctInfo` | 데이터셋 개방표준에 따른 계약정보 | [cite_start]N/A [cite: 16] |

---

### [cite_start][데이터셋 개방표준에 따른 입찰공고정보] 오퍼레이션 명세 [cite: 17]

#### 1) 오퍼레이션 정보
| 항목 | 내용 | 항목 | 내용 |
|---|---|---|---|
| **오퍼레이션 번호** | 1 | **오퍼레이션명(국문)** | [cite_start]데이터셋 개방표준에 따른 입찰공고정보 [cite: 18] |
| **오퍼레이션 유형** | 조회(목록) | **오퍼레이션명(영문)** | [cite_start]`getDataSetOpnStdBidPblancInfo` [cite: 18] |
| **오퍼레이션 설명** | 검색조건을 입찰공고일시로 하여 입찰공고번호, 입찰공고차수, 나라장터공고여부, 입찰공고명, 입찰공고상태명, 입찰공고일자, 입찰공고시각, 업무구분명, 국제입찰여부 등 나라장터에 등록된 입찰공고정보 조회 | **Call Back URL** | [cite_start]N/A [cite: 18] |
| **최대 메시지 사이즈** | 4000bytes | [cite_start]| [cite: 18] |
| **평균 응답 시간** | 500 ms | **초당 최대 트랜잭션**| [cite_start]30 tps [cite: 18] |

#### [cite_start]2) 요청 메시지 명세 [cite: 19]
[cite_start]※ 항목구분 : 필수(1), 옵션(0), 1건 이상 복수건(1..n), 0건 또는 복수건(0..n) [cite: 21]

| 항목명(영문) | 항목명(국문) | 항목크기 | 항목구분 | 샘플데이터 | 항목설명 |
|---|---|:---:|:---:|---|---|
| `numOfRows` | 한 페이지 결과 수 | 4 | 0 | 10 | [cite_start]한 페이지 결과 수 [cite: 20] |
| `pageNo` | 페이지 번호 | 4 | 0 | 1 | [cite_start]페이지 번호 [cite: 20] |
| `ServiceKey` | 서비스키 | 400 | 1 | 인증키 | [cite_start]공공데이터포털에서 받은 인증키 [cite: 20] |
| `type` | 타입 | 4 | 0 | json | [cite_start]오픈API 리턴 타입을 JSON으로 받고 싶을 경우 'json' 으로 지정함 [cite: 20] |
| `bidNtceBgnDt` | 입찰공고시작일시 | 12 | 0 | 202507010000 | [cite_start]검색하고자하는 입찰공고일시범위 시작 'YYYYMMDDHHMM' (입찰공고일시 범위는 1개월로 제한) [cite: 20] |
| `bidNtceEndDt` | 입찰공고종료일시 | 12 | 0 | 202507012359 | [cite_start]검색하고자하는 입찰공고일시범위 종료 'YYYYMMDDHHMM' (입찰공고일시 범위는 1개월로 제한) [cite: 20] |

#### [cite_start]3) 응답 메시지 명세 [cite: 22]
[cite_start]※ 항목구분 : 필수(1), 옵션(0), 1건 이상 복수건(1..n), 0건 또는 복수건(0..n) [cite: 24]

| 항목명(영문) | 항목명(국문) | 항목크기 | 항목구분 | 항목설명 |
|---|---|:---:|:---:|---|
| `resultCode` | 결과코드 | 2 | 1 | [cite_start]결과코드 [cite: 23] |
| `resultMsg` | 결과메세지 | 50 | 1 | [cite_start]결과메세지 [cite: 23] |
| `numOfRows` | 한 페이지 결과 수 | 4 | 1 | [cite_start]한 페이지 결과 수 [cite: 23] |
| `pageNo` | 페이지 번호 | 4 | 1 | [cite_start]페이지 번호 [cite: 23] |
| `totalCount` | 전체 결과 수 | 4 | 1 | [cite_start]전체 결과 수 [cite: 23] |
| `bidNtceNo` | 입찰공고번호 | 13 | 1 | 입찰공고를 관리하기 위한 번호 (형식: 년도(4)+월(2)+순번(5)). [cite_start]차세대나라장터 번호체계 개편: R+년도(2)+BK+순번(8) 총 13자리 구성 (2025년 공고건부터 적용) [cite: 23] |
| `bidNtceOrd` | 입찰공고차수 | 2 | 0 | [cite_start]정정(변경)공고 및 재공고 등이 발생되었을 경우 증가되는 수 [cite: 23] |
| `refNtceNo` | 참조공고번호 | 40 | 0 | [cite_start]기타 전자조달시스템에서 관리하는 공고번호 또는 G2B 입찰공고번호 [cite: 23] |
| `refNtceOrd` | 참조공고차수 | 3 | 0 | [cite_start]참조공고번호에 대한 공고 차수 [cite: 23] |
| `ppsNtceYn` | 나라장터공고여부 | 1 | 1 | [cite_start]나라장터를 통해서도 입찰공고를 하는지 여부 [cite: 23] |
| `bidNtceNm` | 입찰공고명 | 1000 | 1 | [cite_start]공사명 또는 사업명 등 입찰공고 내용 요약 이름 [cite: 23] |
| `bidNtceSttusNm` | 입찰공고상태명 | 100 | 1 | [cite_start]일반, 긴급공고, 정정, 재공고입찰, 취소공고 구분 명칭 [cite: 23] |
| `bidNtceDate` | 입찰공고일자 | 10 | 1 | [cite_start]입찰공고서를 공고한 일자 [cite: 23] |
| `bidNtceBgn` | 입찰공고시각 | 5 | 1 | [cite_start]입찰공고서를 공고한 시각 [cite: 23] |
| `bsnsDivNm` | 업무구분명 | 20 | 1 | [cite_start]물품, 용역, 공사, 외자로 구분 [cite: 23] |
| `intrntnlBidYn`| 국제입찰여부 | 1 | 0 | [cite_start]국제입찰대상인지의 여부 [cite: 23] |
| `cmmnCntrctYn` | 공동계약여부 | 1 | 0 | [cite_start]공동계약(2인 이상) 여부 (단독계약은 N) [cite: 23] |
| `cmmnReciptMethdNm` | 공동수급방식명 | 100 | 0 | [cite_start]공동수급체가 도급을 받아 이행하는 방식을 구분하는 명 [cite: 23] |
| `elctrnBidYn` | 전자입찰여부 | 1 | 1 | [cite_start]전자입찰방식인지 일반입찰방식인지 여부 [cite: 23] |
| `cntrctCnclsSttusNm` | 계약체결형태명 | 30 | 1 | [cite_start]총액계약, 단가계약, 제3자단가계약 구분 명 [cite: 23] |
| `cntrctCnclsMthdNm` | 계약체결방법명 | 30 | 1 | [cite_start]일반경쟁, 제한경쟁, 지명경쟁, 수의계약 등 계약체결 방법 명 [cite: 23] |
| `bidwinrDcsnMthdNm` | 낙찰자결정방법명 | 30 | 0 | [cite_start]낙찰자를 결정하는 방법 (예: 최저가 낙찰제) [cite: 23] |
| `ntceInsttNm` | 공고기관명 | 200 | 1 | [cite_start]공고하는 기관의 명 [cite: 23] |
| `ntceInsttCd` | 공고기관코드 | 7 | 0 | [cite_start]행정안전부 부여 기관코드 [cite: 23] |
| `ntceInsttOfclDeptNm` | 공고기관담당자부서명 | 100 | 0 | [cite_start]공고기관 담당부서명 [cite: 23] |
| `ntceInsttOfclNm` | 공고기관담당자명 | 35 | 0 | [cite_start]공고기관 담당자명 [cite: 23] |
| `ntceInsttOfclTel` | 공고기관담당자전화번호| 13 | 0 | [cite_start]공고기관 담당자 전화번호 [cite: 23] |
| `ntceInsttOfclEmailAdrs`| 공고기관담당자이메일 | 100 | 0 | [cite_start]공고기관 담당자 이메일주소 [cite: 23] |
| `dmndInsttNm` | 수요기관명 | 200 | 1 | [cite_start]계약을 의뢰한 수요기관 명 [cite: 23] |
| `dmndInsttCd` | 수요기관코드 | 7 | 0 | [cite_start]수요기관 행정안전부 기관코드 [cite: 23] |
| `dmndInsttOfclDeptNm` | 수요기관담당자부서명 | 100 | 0 | [cite_start]수요기관 담당부서명 [cite: 23] |
| `dmndInsttOfclNm` | 수요기관담당자명 | 35 | 0 | [cite_start]수요기관 담당자명 [cite: 23] |
| `dmndInsttOfclTel` | 수요기관담당자전화번호| 13 | 0 | [cite_start]수요기관 담당자 전화번호 [cite: 23] |
| `dmndInsttOfclEmailAdrs`| 수요기관담당자이메일 | 100 | 0 | [cite_start]수요기관 담당자 이메일주소 [cite: 23] |
| `presnatnOprtnYn` | 설명회실시여부 | 1 | 0 | [cite_start]설명회(현장/입찰/과업) 실시 여부 [cite: 23] |
| `presnatnOprtnDate` | 설명회실시일자 | 10 | 0 | [cite_start]설명회 실시 일자 [cite: 23] |
| `presnatnOprtnTm` | 설명회실시시각 | 5 | 0 | [cite_start]설명회 실시 시각 [cite: 23] |
| `presnatnOprtnPlce` | 설명회실시장소 | 100 | 0 | [cite_start]설명회 실시 장소 [cite: 23] |
| `bidPrtcptQlfctRgstClseDate`| 입찰참가자격등록마감일자| 10 | 0 | [cite_start]입찰참가자격 등록 완료 시점(일자) [cite: 23] |
| `bidPrtcptQlfctRgstClseTm`| 입찰참가자격등록마감시각| 5 | 0 | [cite_start]입찰참가자격 등록 완료 시점(시각) [cite: 23] |
| `cmmnReciptAgrmntClseDate`| 공동수급협정마감일자 | 10 | 0 | [cite_start]공동수급협정서 등록 마감 시점(일자) [cite: 23] |
| `cmmnReciptAgrmntClseTm`| 공동수급협정마감시각 | 5 | 0 | [cite_start]공동수급협정서 등록 마감 시점(시각) [cite: 23] |
| `bidBeginDate` | 입찰개시일자 | 10 | 0 | [cite_start]입찰서 제출 개시 일자 [cite: 23] |
| `bidBeginTm` | 입찰개시시각 | 5 | 0 | [cite_start]입찰서 제출 개시 시각 [cite: 23] |
| `bidClseDate` | 입찰마감일자 | 10 | 0 | [cite_start]입찰서 제출 마감 일자 [cite: 23] |
| `bidClseTm` | 입찰마감시각 | 5 | 0 | [cite_start]입찰서 제출 마감 시각 [cite: 23] |
| `opengDate` | 개찰일자 | 10 | 1 | [cite_start]조달업체가 제출한 입찰서를 개찰하는 일자 [cite: 23] |
| `opengTm` | 개찰시각 | 5 | 1 | [cite_start]조달업체가 제출한 입찰서를 개찰하는 시각 [cite: 23] |
| `opengPlce` | 개찰장소 | 100 | 1 | [cite_start]조달업체가 제출한 입찰서를 개찰하는 장소 [cite: 23] |
| `asignBdgtAmt`| 배정예산금액(설계금액) | 22 | 0 | [cite_start]사업 배정 예산액 또는 설계금액 (원) [cite: 23] |
| `presmptPrce` | 추정가격 | 25 | 0 | [cite_start]예정가격 결정 전 산정된 가격 (부가세/관급자재비 제외, 원) [cite: 23] |
| `rsrvtnPrceDcsnMthdNm`| 예정가격결정방법명 | 20 | 0 | [cite_start]복수예가, 단일예가 등 결정방식 명 [cite: 23] |
| `rgnLmtYn` | 지역제한여부 | 1 | 0 | [cite_start]입찰 시 지역제한 여부 [cite: 23] |
| `prtcptPsblRgnNm` | 참가가능지역명 | 200 | 0 | [cite_start]참여가능 지역 명칭 (콤마 나열) [cite: 23] |
| `indstrytyLmtYn`| 업종제한여부 | 1 | 0 | [cite_start]입찰 시 업종(면허) 제한 여부 [cite: 23] |
| `bidprcPsblIndstrytyNm`| 투찰가능업종명 | 4000| 0 | [cite_start]제한되는 업종 명칭 (콤마 나열) [cite: 23] |
| `bidNtceUrl` | 입찰공고URL | 500 | 0 | [cite_start]해당 입찰공고 확인 가능한 URL 주소 [cite: 23] |
| `dataBssDate` | 데이터기준일자 | 10 | 1 | [cite_start]데이터 작성 기준일자 [cite: 23] |

#### [cite_start]4) 요청 / 응답 메시지 예제 [cite: 25]
[cite_start]**REST(URI) 요청 예시** [cite: 26]
```text
[http://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo?numOfRows=10&pageNo=1&bidNtceBgnDt=202507010000&bidNtceEndDt=202507010000&ServiceKey=인증키](http://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdBidPblancInfo?numOfRows=10&pageNo=1&bidNtceBgnDt=202507010000&bidNtceEndDt=202507010000&ServiceKey=인증키)

```

**응답 메시지 (XML)** 

```xml
<response>
    <header>
        <resultCode>00</resultCode>
        <resultMsg>정상</resultMsg>
    </header>
    <body>
        <items>
            <item>
                <bidNtceNo>R25BK00933743</bidNtceNo>
                <bidNtceOrd>000</bidNtceOrd>
                <refNtceNo>R25BK00933743</refNtceNo>
                <refNtceOrd>000</refNtceOrd>
                <ppsNtceYn>Y</ppsNtceYn>
                <bidNtceNm>2025년 경기미 가공저장시설 스마트화 지원사업 현미 색채선별기 구매(긴급)</bidNtceNm>
                <bidNtceSttusNm>일반공고</bidNtceSttusNm>
                <bidNtceDate>2025-07-01</bidNtceDate>
                <bidNtceBgn>07:49</bidNtceBgn>
                <bsnsDivNm>물품</bsnsDivNm>
                <intrntnlBidYn>N</intrntnlBidYn>
                <cmmnCntrctYn>Y</cmmnCntrctYn>
                <cmmnReciptMethdNm></cmmnReciptMethdNm>
                <elctrnBidYn>Y</elctrnBidYn>
                <cntrctCnclsSttusNm>총액계약</cntrctCnclsSttusNm>
                <cntrctCnclsMthdNm>제한경쟁</cntrctCnclsMthdNm>
                <bidwinrDcsnMthdNm>적격심사제</bidwinrDcsnMthdNm>
                <ntceInsttNm>신김포농업협동조합 양촌미곡사업소</ntceInsttNm>
                <ntceInsttCd>Z013176</ntceInsttCd>
                <ntceInsttOfclDeptNm></ntceInsttOfclDeptNm>
                <ntceInsttOfclNm>박형준</ntceInsttOfclNm>
                <ntceInsttOfclTel>***-***-*****</ntceInsttOfclTel>
                <ntceInsttOfclEmailAdrs>nh241040-1@nonghyup.com</ntceInsttOfclEmailAdrs>
                <dmndInsttNm>신김포농업협동조합 양촌미곡사업소</dmndInsttNm>
                <dmndInsttCd>Z013176</dmndInsttCd>
                <dmndInsttOfclDeptNm></dmndInsttOfclDeptNm>
                <dmndInsttOfclNm>박형준</dmndInsttOfclNm>
                <dmndInsttOfclTel>***********</dmndInsttOfclTel>
                <dmndInsttOfclEmailAdrs></dmndInsttOfclEmailAdrs>
                <presnatnOprtnYn></presnatnOprtnYn>
                <presnatnOprtnDate></presnatnOprtnDate>
                <presnatnOprtnTm></presnatnOprtnTm>
                <presnatnOprtnPlce></presnatnOprtnPlce>
                <bidPrtcptQlfctRgstClseDate>2025-07-07</bidPrtcptQlfctRgstClseDate>
                <bidPrtcptQlfctRgstClseTm>14:00</bidPrtcptQlfctRgstClseTm>
                <cmmnReciptAgrmntClseDate></cmmnReciptAgrmntClseDate>
                <cmmnReciptAgrmntClseTm></cmmnReciptAgrmntClseTm>
                <bidBeginDate>2025-07-01</bidBeginDate>
                <bidBeginTm>10:00</bidBeginTm>
                <bidClseDate>2025-07-08</bidClseDate>
                <bidClseTm>15:00</bidClseTm>
                <opengDate>2025-07-08</opengDate>
                <opengTm>16:00</opengTm>
                <opengPlce>국가종합전자조달시스템(나라장터)</opengPlce>
                <asignBdgtAmt>97240000</asignBdgtAmt>
                <presmptPrce>88400000</presmptPrce>
                <rsrvtnPrceDcsnMthdNm>단일예가</rsrvtnPrceDcsnMthdNm>
                <rgnLmtYn>N</rgnLmtYn>
                <prtcptPsblRgnNm>...(이하생략 나라장터참조)</prtcptPsblRgnNm>
                <indstrytyLmtYn>N</indstrytyLmtYn>
                <bidprcPsblIndstrytyNm></bidprcPsblIndstrytyNm>
                <bidNtceUrl>[https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R25BK00933743&amp;bidPbancOrd=000](https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R25BK00933743&amp;bidPbancOrd=000)</bidNtceUrl>
                <dataBssDate>2025-08-07</dataBssDate>
            </item>
        </items>
        <numOfRows>10</numOfRows>
        <pageNo>1</pageNo>
        <totalCount>1417</totalCount>
    </body>
</response>

```

---

[데이터셋 개방표준에 따른 낙찰정보] 오퍼레이션 명세 

#### 1) 오퍼레이션 정보

| 항목 | 내용 | 항목 | 내용 |
| --- | --- | --- | --- |
| **오퍼레이션 번호** | 2 | **오퍼레이션명(국문)** | 데이터셋 개방표준에 따른 낙찰정보 

 |
| **오퍼레이션 유형** | 조회(목록) | **오퍼레이션명(영문)** | <br>`getDataSetOpnStdScsbidInfo` 

 |
| **오퍼레이션 설명** | 검색조건을 개찰일시, 업무구분명으로 입찰공고번호, 입찰공고차수, 입찰공고명, 업무구분명, 계약체결형태명, 계약체결방법명, 낙찰자결정방법명, 공고기관명, 공고기관코드 등 나라장터에 등록된 낙찰정보 조회 | **Call Back URL** | N/A 

 |
| **최대 메시지 사이즈** | 4000bytes |  |  |
| **평균 응답 시간** | 500 ms | **초당 최대 트랜잭션** | 30 tps 

 |

2) 요청 메시지 명세 

※ 항목구분 : 필수(1), 옵션(0), 1건 이상 복수건(1..n), 0건 또는 복수건(0..n) 

| 항목명(영문) | 항목명(국문) | 항목크기 | 항목구분 | 샘플데이터 | 항목설명 |
| --- | --- | --- | --- | --- | --- |
| `numOfRows` | 한 페이지 결과 수 | 4 | 0 | 10 | 한 페이지 결과 수 

 |
| `pageNo` | 페이지 번호 | 4 | 0 | 1 | 페이지 번호 

 |
| `ServiceKey` | 서비스키 | 400 | 1 | 인증키 | 공공데이터포털에서 받은 인증키 

 |
| `type` | 타입 | 4 | 0 | json | 오픈API 리턴 타입을 JSON으로 받고 싶을 경우 'json' 으로 지정 

 |
| `bsnsDivCd` | 업무구분코드 | 2 | 1 | 3 | 업무구분코드가 1이면 물품, 2면 외자, 3이면 공사, 5면 용역 

 |
| `opengBgnDt` | 개찰시작일시 | 12 | 0 | 202507010000 | 검색하고자하는 개찰일시범위 시작 'YYYYMMDDHHMM' (개찰일시 범위는 1주일로 제한) 

 |
| `opengEndDt` | 개찰종료일시 | 12 | 0 | 202507022359 | 검색하고자하는 개찰일시범위 종료 'YYYYMMDDHHMM' (개찰일시 범위는 1주일로 제한) 

 |

3) 응답 메시지 명세 

※ 항목구분 : 필수(1), 옵션(0), 1건 이상 복수건(1..n), 0건 또는 복수건(0..n) 

| 항목명(영문) | 항목명(국문) | 항목크기 | 항목구분 | 항목설명 |
| --- | --- | --- | --- | --- |
| `resultCode` | 결과코드 | 2 | 1 | 결과코드 

 |
| `resultMsg` | 결과메세지 | 50 | 1 | 결과메세지 

 |
| `numOfRows` | 한 페이지 결과 수 | 4 | 1 | 한 페이지 결과 수 

 |
| `pageNo` | 페이지 번호 | 4 | 1 | 페이지 번호 

 |
| `totalCount` | 전체 결과 수 | 4 | 1 | 전체 결과 수 

 |
| `bidNtceNo` | 입찰공고번호 | 13 | 1 | 입찰공고를 관리하기 위한 번호. (차세대나라장터 체계 13자리, 2025년 적용) 

 |
| `bidNtceOrd` | 입찰공고차수 | 3 | 0 | 정정 및 재공고 발생 시 증가되는 차수 

 |
| `bidNtceNm` | 입찰공고명 | 1000 | 1 | 입찰공고 내용 요약 이름 

 |
| `bsnsDivNm` | 업무구분명 | 20 | 1 | 물품, 용역, 공사, 외자로 구분함 

 |
| `cntrctCnclsSttusNm` | 계약체결형태명 | 30 | 1 | 총액계약, 단가계약, 제3자단가계약 등 형태 

 |
| `cntrctCnclsMthdNm` | 계약체결방법명 | 30 | 1 | 일반경쟁, 제한경쟁, 지명경쟁, 수의계약 등 방법 

 |
| `bidwinrDcsnMthdNm` | 낙찰자결정방법명 | 30 | 0 | 낙찰자를 결정하는 방법 

 |
| `ntceInsttNm` | 공고기관명 | 200 | 1 | 수요기관의 의뢰를 받아 공고하는 기관의 명 

 |
| `ntceInsttCd` | 공고기관코드 | 7 | 0 | 행정안전부 부여 기관코드 

 |
| `dmndInsttNm` | 수요기관명 | 200 | 1 | 계약을 의뢰한 수요기관 명 

 |
| `dmndInsttCd` | 수요기관코드 | 7 | 0 | 수요기관 행정안전부 기관코드 

 |
| `sucsfLwstlmtRt` | 낙찰하한율 | 22 | 0 | 낙찰가능한 최소한의 예정가격 대비 투찰율 (%) 

 |
| `presmptPrce` | 추정가격 | 25 | 0 | 예정가격 결정 전 산정 가격 (원) 

 |
| `rsrvtnPrce` | 예정가격 | 21 | 0 | 낙찰자 및 계약금액 결정기준 가액 (원) 

 |
| `bssAmt` | 기초금액 | 21 | 0 | 예정가격 작성 과정 기준금액 (원) 

 |
| `opengDate` | 개찰일자 | 10 | 1 | 입찰서 개찰 일자 

 |
| `opengTm` | 개찰시각 | 5 | 1 | 입찰서 개찰 시각 

 |
| `opengRsltDivNm` | 개찰결과구분명 | 30 | 1 | 개찰완료, 유찰, 재입찰 등 결과 구분 명 

 |
| `opengRank` | 개찰순위 | 4 | 0 | 개찰 결과에 따른 업체별 순위 또는 협상순위 

 |
| `bidprcCorpBizrno` | 투찰업체사업자등록번호 | 12 | 0 | 투찰업체 사업자등록번호 

 |
| `bidprcCorpNm` | 투찰업체명 | 100 | 0 | 투찰업체 명 

 |
| `bidprcCorpCeoNm` | 투찰업체대표자명 | 35 | 0 | 투찰업체 대표자 명 

 |
| `bidprcAmt` | 투찰금액 | 21 | 0 | 투찰한 금액 (원) 

 |
| `bidprcRt` | 투찰율 | 10 | 0 | 예정가격 대비 투찰금액 비율 (%) 

 |
| `bidprcDate` | 투찰일자 | 10 | 0 | 투찰업체가 투찰한 일자 

 |
| `bidprcTm` | 투찰시각 | 5 | 0 | 투찰업체가 투찰한 시각 

 |
| `sucsfYn` | 낙찰여부 | 1 | 0 | 낙찰 여부 (Y/N) 

 |
| `dqlfctnRsn` | 부적격사유 | 30 | 0 | 부적격 판명 시 사유 

 |
| `fnlSucsfAmt` | 최종낙찰금액 | 21 | 0 | 최종 낙찰된 금액 (개찰완료 시 필수) 

 |
| `fnlSucsfRt` | 최종낙찰율 | 10 | 0 | 예정가격대비 최종낙찰금액 비율 (%) 

 |
| `fnlSucsfDate` | 최종낙찰일자 | 10 | 0 | 최종낙찰 일자 

 |
| `fnlSucsfCorpNm` | 최종낙찰업체명 | 100 | 0 | 최종낙찰 업체 명 

 |
| `fnlSucsfCorpCeoNm` | 최종낙찰업체대표자명 | 35 | 0 | 최종낙찰 업체 대표자명 

 |
| `fnlSucsfCorpOfclNm` | 최종낙찰업체담당자명 | 35 | 0 | 최종낙찰 업체 담당자명 

 |
| `fnlSucsfCorpBizrno` | 최종낙찰업체사업자등록번호 | 12 | 0 | 최종낙찰 업체 사업자등록번호 

 |
| `fnlSucsfCorpAdrs` | 최종낙찰업체주소 | 200 | 0 | 최종낙찰 업체 주소 

 |
| `fnlSucsfCorpContactTel` | 최종낙찰업체연락처 | 13 | 0 | 최종낙찰 업체 연락 전화번호 

 |
| `dataBssDate` | 데이터기준일자 | 10 | 1 | 데이터 작성 기준일자 

 |

4) 요청 / 응답 메시지 예제 

**REST(URI) 요청 예시** 

```text
[http://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo?numOfRows=10&pageNo=1&opengBgnDt=201701010000&opengEndDt=201701062359&bsnsDivCd=1&ServiceKey=인증키](http://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdScsbidInfo?numOfRows=10&pageNo=1&opengBgnDt=201701010000&opengEndDt=201701062359&bsnsDivCd=1&ServiceKey=인증키)

```

**응답 메시지 (XML)** 

```xml
<response>
    <header>
        <resultCode>00</resultCode>
        <resultMsg>정상</resultMsg>
    </header>
    <body>
        <items>
            <item>
                <bidNtceNo>R25BK00925778</bidNtceNo>
                <bidNtceOrd>000</bidNtceOrd>
                <bidNtceNm>[부여]국도40호 가탑삼거리 교차로개선사업</bidNtceNm>
                <bsnsDivNm>공사</bsnsDivNm>
                <cntrctCnclsSttusNm>총액계약</cntrctCnclsSttusNm>
                <cntrctCnclsMthdNm>수의계약</cntrctCnclsMthdNm>
                <bidwinrDcsnMthdNm>소액수의견적</bidwinrDcsnMthdNm>
                <ntceInsttNm>충청남도 건설본부 건설사업부 동부사무소</ntceInsttNm>
                <ntceInsttCd>6441502</ntceInsttCd>
                <dmndInsttNm>충청남도 건설본부 건설사업부 동부사무소</dmndInsttNm>
                <dmndInsttCd>6441502</dmndInsttCd>
                <sucsfLwstlmtRt>89.745</sucsfLwstlmtRt>
                <presmptPrce>124209091</presmptPrce>
                <rsrvtnPrce>135898725</rsrvtnPrce>
                <bssAmt>136630000</bssAmt>
                <opengDate>2025-07-01</opengDate>
                <opengTm>10:00</opengTm>
                <opengRsltDivNm>개찰완료</opengRsltDivNm>
                <opengRank>1</opengRank>
                <bidprcCorpBizrno>3088103521</bidprcCorpBizrno>
                <bidprcCorpNm>대륜건설(주)</bidprcCorpNm>
                <bidprcCorpCeoNm>손현구</bidprcCorpCeoNm>
                <bidprcAmt>122845000</bidprcAmt>
                <bidprcRt>90.394</bidprcRt>
                <bidprcDate>2025-06-27</bidprcDate>
                <bidprcTm>08:19</bidprcTm>
                <sucsfYn>Y</sucsfYn>
                <dqlfctnRsn>정상</dqlfctnRsn>
                <fnlSucsfAmt>122845000</fnlSucsfAmt>
                <fnlSucsfRt>90.394</fnlSucsfRt>
                <fnlSucsfDate>2025-07-02</fnlSucsfDate>
                <fnlSucsfCorpNm>대륜건설(주)</fnlSucsfCorpNm>
                <fnlSucsfCorpCeoNm>손현구</fnlSucsfCorpCeoNm>
                <fnlSucsfCorpOfclNm></fnlSucsfCorpOfclNm>
                <fnlSucsfCorpBizrno>308-81-03521</fnlSucsfCorpBizrno>
                <fnlSucsfCorpAdrs>충청남도 부여군 부여읍 성왕로161 </fnlSucsfCorpAdrs>
                <fnlSucsfCorpContactTel>042-826-6220</fnlSucsfCorpContactTel>
                <dataBssDate>2025-08-08</dataBssDate>
            </item>
        </items>
        <numOfRows>10</numOfRows>
        <pageNo>1</pageNo>
        <totalCount>315130</totalCount>
    </body>
</response>

```

---

[데이터셋 개방표준에 따른 계약정보] 오퍼레이션 명세 

#### 1) 오퍼레이션 정보

| 항목 | 내용 | 항목 | 내용 |
| --- | --- | --- | --- |
| **오퍼레이션 번호** | 3 | **오퍼레이션명(국문)** | 데이터셋 개방표준에 따른 계약정보 

 |
| **오퍼레이션 유형** | 조회(목록) | **오퍼레이션명(영문)** | <br>`getDataSetOpnStdCntrctInfo` 

 |
| **오퍼레이션 설명** | 검색조건을 계약체결일자로 계약번호, 통합계약번호, 계약차수, 계약명, 업무구분명, 계약체결형태명, 계약체결방법명, 장기계속구분명, 공동계약여부, 계약체결일자, 계약기간, 계약금액 등 나라장터에 등록된 계약정보 조회 | **Call Back URL** | N/A 

 |
| **최대 메시지 사이즈** | 4000bytes |  |  |
| **평균 응답 시간** | 500 ms | **초당 최대 트랜잭션** | 30 tps 

 |

2) 요청 메시지 명세 

※ 항목구분 : 필수(1), 옵션(0), 1건 이상 복수건(1..n), 0건 또는 복수건(0..n) 

| 항목명(영문) | 항목명(국문) | 항목크기 | 항목구분 | 샘플데이터 | 항목설명 |
| --- | --- | --- | --- | --- | --- |
| `numOfRows` | 한 페이지 결과 수 | 4 | 1 | 10 | 한 페이지 결과 수 

 |
| `pageNo` | 페이지 번호 | 4 | 1 | 1 | 페이지 번호 

 |
| `ServiceKey` | 서비스키 | 400 | 1 | 인증키 | 공공데이터포털에서 받은 인증키 

 |
| `type` | 타입 | 4 | 0 | json | 오픈API 리턴 타입을 JSON으로 받고 싶을 경우 'json' 으로 지정 

 |
| `cntrctCnclsBgnDate` | 계약체결시작일자 | 8 | 0 | 20250305 | 검색하고자하는 계약체결일자 시작 'YYYYMMDD' (1개월 제한) 

 |
| `cntrctCnclsEndDate` | 계약체결종료일자 | 8 | 0 | 20250305 | 검색하고자하는 계약체결일자 종료 'YYYYMMDD' (1개월 제한) 

 |
| `insttDivCd` | 기관구분값 | 1 | 0 | 1 | 검색하고자 하는 기관구분값 (1: 계약기관, 2: 수요기관) 

 |
| `insttCd` | 기관코드 | 7 | 0 | 4490000 | 기관구분코드에 따른 계약기관코드 또는 수요기관코드 

 |

3) 응답 메시지 명세 

※ 항목구분 : 필수(1), 옵션(0), 1건 이상 복수건(1..n), 0건 또는 복수건(0..n) 

| 항목명(영문) | 항목명(국문) | 항목크기 | 항목구분 | 항목설명 |
| --- | --- | --- | --- | --- |
| `resultCode` | 결과코드 | 2 | 1 | 결과코드 

 |
| `resultMsg` | 결과메세지 | 50 | 1 | 결과메세지 

 |
| `numOfRows` | 한 페이지 결과 수 | 4 | 1 | 한 페이지 결과 수 

 |
| `pageNo` | 페이지 번호 | 4 | 1 | 페이지 번호 

 |
| `totalCount` | 전체 결과 수 | 4 | 1 | 전체 결과 수 

 |
| `cntrctNo` | 계약번호 | 35 | 1 | 계약서를 식별하기 위한 관리번호 

 |
| `untyCntrctNo` | 통합계약번호 | 13 | 0 | 통합 관리를 위해 채번되는 번호 

 |
| `cntrctOrd` | 계약차수 | 2 | 1 | 계약의 변경 시 변경된 차수 

 |
| `cntrctNm` | 계약명 | 500 | 1 | 계약내용 요약 이름 

 |
| `bsnsDivNm` | 업무구분명 | 20 | 1 | 물품, 용역, 공사, 외자, 비축 구분 

 |
| `cntrctCnclsSttusNm` | 계약체결형태명 | 30 | 1 | 총액계약, 단가계약, 제3자단가계약 

 |
| `cntrctCnclsMthdNm` | 계약체결방법명 | 30 | 1 | 일반경쟁, 제한경쟁, 지명경쟁, 수의계약 등 

 |
| `lngtrmCtnuDivNm` | 장기계속구분명 | 30 | 0 | 단기계약, 장기계속계약 등 구분 명 

 |
| `cmmnCntrctYn` | 공동계약여부 | 1 | 0 | 공동계약(2인 이상) 여부 (N: 단독) 

 |
| `cntrctCnclsDate` | 계약체결일자 | 10 | 1 | 계약이 성립된 체결일자 

 |
| `cntrctPrd` | 계약기간 | 70 | 1 | 계약의 효력이 있는 기간 

 |
| `cntrctAmt` | 계약금액 | 25 | 1 | 당해연도 계약금액 또는 장기계속 금차계약금액 (원) 

 |
| `ttalCntrctAmt` | 총계약금액 | 25 | 0 | 장기계속계약 전체 계약금액(총부기금액) 

 |
| `cntrctInfoUrl` | 계약정보URL | 500 | 0 | 계약정보 확인 URL 주소 

 |
| `bidNtceNo` | 입찰공고번호 | 13 | 0 | 차세대나라장터 번호체계 (13자리, T/R 여부 포함) 

 |
| `bidNtceOrd` | 입찰공고차수 | 3 | 0 | 정정 및 재공고 발생 시 증가 차수 

 |
| `bidNtceNm` | 입찰공고명 | 1000 | 0 | 입찰공고 내용 요약 이름 

 |
| `opengDate` | 개찰일자 | 10 | 0 | 입찰서를 개찰하는 일자 

 |
| `opengTm` | 개찰시각 | 5 | 0 | 입찰서를 개찰하는 시각 

 |
| `rsrvtnPrce` | 예정가격 | 21 | 0 | 계약금액 결정기준 미리 작성된 가액 

 |
| `prvtcntrctRsn` | 수의계약사유 | 1000 | 0 | 특정인 선정 계약 시 사유 내용 

 |
| `bidNtceUrl` | 입찰공고URL | 500 | 0 | 입찰공고 확인 URL 주소 

 |
| `cntrctInsttDivNm` | 계약기관구분명 | 200 | 1 | 국가기관, 지자체 등 구분 명 

 |
| `cntrctInsttNm` | 계약기관명 | 200 | 1 | 계약 주체 기관 명 

 |
| `cntrctInsttCd` | 계약기관코드 | 7 | 0 | 행정안전부 부여 기관코드 

 |
| `cntrctInsttChrgDeptNm` | 계약기관담당부서명 | 100 | 0 | 계약기관 담당 부서명 

 |
| `cntrctInsttOfclNm` | 계약기관담당자명 | 100 | 0 | 계약기관 담당자명 

 |
| `cntrctInsttOfclTel` | 계약기관담당자전화번호 | 13 | 0 | 계약기관 담당자 전화번호 

 |
| `cntrctInsttOfcl` | 계약기관담당자이메일 | 100 | 0 | 계약기관 담당자 이메일주소 

 |
| `dmndInsttDivNm` | 수요기관구분명 | 200 | 1 | 국가기관, 지자체 등 구분 명 

 |
| `dmndInsttNm` | 수요기관명 | 200 | 1 | 조달 요청 의뢰 기관 명 

 |
| `dmndInsttCd` | 수요기관코드 | 7 | 0 | 행정안전부 부여 기관코드 

 |
| `dmndInsttOfclDeptNm` | 수요기관담당자부서명 | 100 | 0 | 수요기관 계약담당 부서명 

 |
| `dmndInsttOfclNm` | 수요기관담당자명 | 35 | 0 | 수요기관 담당자명 

 |
| `dmndInsttOfclTel` | 수요기관담당자전화번호 | 13 | 0 | 수요기관 담당자 전화번호 

 |
| `dmndInsttOfclEmailAdrs` | 수요기관담당자이메일 | 100 | 0 | 수요기관 담당자 이메일 

 |
| `rprsntCorpNm` | 대표업체명 | 100 | 1 | 상대 중 대표 업체 명 

 |
| `dmstcCorpYn` | 국내업체여부 | 1 | 0 | 국내업체 여부 (Y/N) 

 |
| `rprsntCorpCeoNm` | 대표업체대표자명 | 35 | 0 | 대표업체 대표자 성명 

 |
| `rprsntCorpOfclNm` | 대표업체담당자명 | 35 | 0 | 대표업체 담당자명 

 |
| `rprsntCorpBizrno` | 대표업체사업자등록번호 | 12 | 0 | 대표업체 사업자등록번호 

 |
| `rprsntCorpAdrs` | 대표업체주소 | 200 | 0 | 대표업체 사업장 주소 

 |
| `rprsntCorpContactTel` | 대표업체연락전화번호 | 13 | 0 | 대표업체 연락 전화번호 

 |
| `dataBssDate` | 데이터기준일자 | 10 | 1 | 데이터 작성 기준일자 

 |

4) 요청 / 응답 메시지 예제 

**REST(URI) 요청 예시** 

```text
[http://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdCntrctInfo?numOfRows=10&pageNo=1&cntrctCnclsBgnDate=20250305&cntrctCnclsEndDate=20250305&ServiceKey=인증키](http://apis.data.go.kr/1230000/ao/PubDataOpnStdService/getDataSetOpnStdCntrctInfo?numOfRows=10&pageNo=1&cntrctCnclsBgnDate=20250305&cntrctCnclsEndDate=20250305&ServiceKey=인증키)

```

**응답 메시지 (XML)** 

```xml
<response>
    <header>
        <resultCode>00</resultCode>
        <resultMsg>정상</resultMsg>
    </header>
    <body>
        <items>
            <item>
                <cntrctNo>R25TA00247713</cntrctNo>
                <untyCntrctNo>R25TE01743533</untyCntrctNo>
                <cntrctOrd>00</cntrctOrd>
                <cntrctNm>2025년 시내버스 노후LED 전광판 교체사업</cntrctNm>
                <bsnsDivNm>물품</bsnsDivNm>
                <cntrctCnclsSttusNm>총액계약</cntrctCnclsSttusNm>
                <cntrctCnclsMthdNm>지명경쟁</cntrctCnclsMthdNm>
                <lngtrmCtnuDivNm>단년도계약</lngtrmCtnuDivNm>
                <cmmnCntrctYn>N</cmmnCntrctYn>
                <cntrctCnclsDate>2025-03-05</cntrctCnclsDate>
                <cntrctPrd>2025.03.05.</cntrctPrd>
                <cntrctAmt>214345450</cntrctAmt>
                <ttalCntrctAmt></ttalCntrctAmt>
                <cntrctInfoUrl>[https://www.g2b.go.kr/link/FIUA027_01/single/?ctrtNo=R25TA00247713&amp;ctrtChgOrd=00&amp;prcmBsneSeCd=조070001&amp;srchName=ctrtCrst&amp;openUrl=Y](https://www.g2b.go.kr/link/FIUA027_01/single/?ctrtNo=R25TA00247713&amp;ctrtChgOrd=00&amp;prcmBsneSeCd=조070001&amp;srchName=ctrtCrst&amp;openUrl=Y)</cntrctInfoUrl>
                <bidNtceNo>R25BK00646279</bidNtceNo>
                <bidNtceOrd>000</bidNtceOrd>
                <bidNtceNm>2025년 시내버스 노후LED 전광판 교체사업</bidNtceNm>
                <opengDate>2025-02-26</opengDate>
                <opengTm>15:00</opengTm>
                <rsrvtnPrce>235387050</rsrvtnPrce>
                <prvtcntrctRsn>중소벤처기업부장관이 지정 공고한 물품 [지방계약법 022조 000항 010호 000목]</prvtcntrctRsn>
                <bidNtceUrl>[https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R25BK00646279&amp;bidPbancOrd=000](https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R25BK00646279&amp;bidPbancOrd=000)</bidNtceUrl>
                <cntrctInsttDivNm>지방자치단체</cntrctInsttDivNm>
                <cntrctInsttNm>충청남도 천안시</cntrctInsttNm>
                <cntrctInsttCd>4490000</cntrctInsttCd>
                <cntrctInsttChrgDeptNm>천안시 회계과</cntrctInsttChrgDeptNm>
                <cntrctInsttOfclNm>안선후</cntrctInsttOfclNm>
                <cntrctInsttOfclTel>0415215289</cntrctInsttOfclTel>
                <cntrctInsttOfcl>cact@korea.kr</cntrctInsttOfcl>
                <dmndInsttDivNm>지방자치단체</dmndInsttDivNm>
                <dmndInsttNm>충청남도 천안시</dmndInsttNm>
                <dmndInsttCd>4490000</dmndInsttCd>
                <dmndInsttOfclDeptNm>천안시 회계과</dmndInsttOfclDeptNm>
                <dmndInsttOfclNm>안선후</dmndInsttOfclNm>
                <dmndInsttOfclTel>0415215289</dmndInsttOfclTel>
                <dmndInsttOfclEmailAdrs>cact@korea.kr</dmndInsttOfclEmailAdrs>
                <rprsntCorpNm>주식회사 티이케이</rprsntCorpNm>
                <dmstcCorpYn>Y</dmstcCorpYn>
                <rprsntCorpCeoNm>윤민아</rprsntCorpCeoNm>
                <rprsntCorpOfclNm>윤민아</rprsntCorpOfclNm>
                <rprsntCorpBizrno>783-81-03488</rprsntCorpBizrno>
                <rprsntCorpAdrs>충청남도 천안시 서북구 백석공단1로</rprsntCorpAdrs>
                <rprsntCorpContactTel>0419065360</rprsntCorpContactTel>
                <dataBssDate>2025-08-05</dataBssDate>
            </item>
        </items>
        <numOfRows>10</numOfRows>
        <pageNo>1</pageNo>
        <totalCount>8302</totalCount>
    </body>
</response>

```

---

OPEN API 에러코드별 조치방안 

| Code | 코드값 | 설명 | 조치방안 |
| --- | --- | --- | --- |
| `01` | Application Error | 제공기관 서비스 제공 상태가 원활하지 않습니다. | 서비스 제공기관의 관리자에게 문의하시기 바랍니다. 

 |
| `02` | DB Error | 제공기관 서비스 제공 상태가 원활하지 않습니다. | 서비스 제공기관의 관리자에게 문의하시기 바랍니다. 

 |
| `03` | No Data | 데이터 없음 에러 | - 

 |
| `04` | HTTP Error | 제공기관 서비스 제공 상태가 원활하지 않습니다. | 서비스 제공기관의 관리자에게 문의하시기 바랍니다. 

 |
| `05` | service time out | 제공기관 서비스 제공 상태가 원활하지 않습니다. | 서비스 제공기관의 관리자에게 문의하시기 바랍니다. 

 |
| `06` | 날짜Format 에러 | 날짜 Default, Format Error | 날짜형식을 확인 하시기 바랍니다. 

 |
| `07` | 입력범위값 초과 에러 | 요청하신 OpenAPI의 파라미터 입력값 범위가 초과 되었습니다. | 기술문서를 다시 한번 확인하여 주시기 바랍니다. 

 |
| `08` | 필수값 입력 에러 | 요청하신 OpenAPI의 필수 파라미터가 누락되었습니다. | 기술문서를 다시 한번 확인하여 주시기 바랍니다. 

 |
| `10` | 잘못된 요청 파라미터 에러 | OpenAPI 요청시 ServiceKey 파라미터가 없음 | - OpenAPI 요청시 ServiceKey 파라미터 누락 확인

<br>

<br>- OpenAPI 요청 URL 확인 

 |
| `11` | 필수 요청 파라미터가 없음 | 요청하신 OpenAPI의 필수 파라미터가 누락되었습니다. | 기술문서를 다시 한번 확인하시어 주시기 바랍니다. 

 |
| `12` | 해당 오픈API 서비스가 없거나 폐기됨 | OpenAPI 호출시 URL이 잘못됨 | - 폐기 서비스인지 확인

<br>

<br>- 개발가이드에서 URL 확인 

 |
| `20` | 서비스 접근 거부 | 활용승인이 되지 않은 OpenAPI호출 | - 활용신청정보 승인상태 확인

<br>

<br>- 승인 후 2~3일 소요 (이메일 발송) 

 |
| `22` | 서비스 요청 제한 횟수 초과 에러 | 일일 활용건수가 초과함(활용건수 증가 필요) | - 일일 트래픽량 확인

<br>

<br>- 운영계정일 경우 변경신청으로 트래픽량 증가 필요 

 |
| `30` | 등록되지 않은 서비스 키 | 잘못된 서비스키를 사용하였거나 서비스키를 URL인코딩하지 않음 | - 발급받은 서비스키 재확인

<br>

<br>- URL 인코딩 여부 확인 

 |
| `31` | 기한 만료된 서비스 키 | OpenAPI 사용기간이 만료됨 (활용연장신청 후 사용가능) | - 활용기간 확인

<br>

<br>- 연장신청 승인 후 재사용 

 |
| `32` | 등록되지 않은 도메인명 또는 IP주소 | 활용신청한 서버의 IP와 실제 OpenAPI호출한 서버가 다를 경우 | - 등록된 도메인/IP 확인

<br>

<br>- 변경신청을 통해 정보 수정 

 |
